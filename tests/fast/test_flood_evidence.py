"""Flood pilot evidence (ADR-0038): Floodboard parsing, storage, freshness, health and reads."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api.errors import GrpError
from api.flood_pilot import _as_of
from core.db import Base
from core.flood_evidence.config import pilot_config
from core.flood_evidence.floodboard import parse_reports, parse_roads
from core.flood_evidence.freshness import counts_as_current, freshness
from core.flood_evidence.ingest import Pulled, ingest_body, pull_due
from core.flood_evidence.models import (
    FETCH_FORMAT_ERROR,
    FETCH_HTTP_ERROR,
    FETCH_NETWORK_ERROR,
    FETCH_OK,
    FloodObservation,
    FloodSourceFetch,
)
from core.flood_evidence.observation import (
    OBSERVED,
    PROVIDER_DERIVED,
    SourceFormatError,
    state_hash,
)
from core.flood_evidence.situation import (
    HEALTH_DEGRADED,
    HEALTH_NEVER,
    HEALTH_OFFLINE,
    HEALTH_OK,
    current_roads,
    recent_reports,
    situation,
    sources_status,
)
from core.storage import LocalStorage

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "floodboard"
ROADS = (FIXTURES / "roads_20261003.geojson").read_bytes()
REPORTS = (FIXTURES / "reports_20261003.csv").read_bytes()
CONFIG = pilot_config("bangkok")
ROADS_SOURCE = CONFIG.source("floodboard_roads")
REPORTS_SOURCE = CONFIG.source("floodboard_reports")


def _roads_with(change) -> bytes:
    collection = json.loads(ROADS)
    for feature in collection["features"]:
        change(feature)
    return json.dumps(collection).encode()


def _newest_road_time() -> datetime:
    return max(
        datetime.fromtimestamp(f["properties"]["updated"] / 1000, UTC)
        for f in json.loads(ROADS)["features"]
    )


def _newest_report_time() -> datetime:
    rows = csv.DictReader(io.StringIO(REPORTS.decode("utf-8-sig"), newline=""))
    return max(datetime.fromisoformat(r["time_utc"].replace("Z", "+00:00")) for r in rows)


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "storage")


def _ingest(session, storage, source, body, at, outcome=FETCH_OK, status=200):
    fetch = ingest_body(session, storage, CONFIG, source, Pulled(status, body, outcome), at)
    session.commit()
    return fetch


# --- Parsing -------------------------------------------------------------------------------


def test_roads_parse_with_geometry_ids_and_evidence_class() -> None:
    drafts = parse_roads(ROADS)
    assert len(drafts) == 7
    assert len({d.external_id for d in drafts}) == 7
    zone = [d for d in drafts if d.state["road_class"] == "zone"]
    assert zone and all(d.evidence_class == PROVIDER_DERIVED for d in zone)
    assert {d.evidence_class for d in drafts} == {OBSERVED, PROVIDER_DERIVED}
    assert all(set(d.state["verdict"]) == {"motorbike", "sedan", "pickup", "truck"} for d in drafts)
    assert all("conf" in d.provider_judgement for d in drafts)


def test_reports_keep_only_a_hash_of_text_and_no_link() -> None:
    drafts = parse_reports(REPORTS)
    assert len(drafts) == 8
    assert {d.underlying_sources[0] for d in drafts} == {
        "traffy", "crowd", "bma_sensor", "bma_dds", "news"
    }
    for draft in drafts:
        flattened = json.dumps(draft.state) + json.dumps(draft.provider_judgement)
        assert "redacted" not in flattened and "http" not in flattened
    assert all(d.text_sha256 is None or len(d.text_sha256) == 64 for d in drafts)


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b'{"type": "Feature"}',
        _roads_with(lambda f: f["properties"].pop("verdict")),
        _roads_with(lambda f: f["properties"]["verdict"].update(sedan="fine")),
        _roads_with(lambda f: f["properties"].update(depthCm=-5)),
        _roads_with(lambda f: f.update(geometry={"type": "Point", "coordinates": [100.5, 13.7]})),
        _roads_with(lambda f: f["geometry"]["coordinates"][0][0].__setitem__(0, 2.35)),
    ],
)
def test_malformed_roads_are_refused_whole(body: bytes) -> None:
    with pytest.raises(SourceFormatError):
        parse_roads(body)


def test_report_column_change_is_refused() -> None:
    changed = REPORTS.decode("utf-8-sig").replace("depth_cm", "depth", 1).encode()
    with pytest.raises(SourceFormatError):
        parse_reports(changed)


def test_provider_score_and_refresh_time_do_not_change_the_observed_state() -> None:
    base = parse_roads(ROADS)[0]
    decayed = parse_roads(
        _roads_with(
            lambda f: f["properties"].update(conf=0.01, updated=f["properties"]["updated"] + 6e5)
        )
    )[0]
    deeper = parse_roads(_roads_with(lambda f: f["properties"].update(depthCm=77)))[0]
    assert state_hash(base) == state_hash(decayed)
    assert state_hash(base) != state_hash(deeper)


# --- Freshness ------------------------------------------------------------------------------


def test_freshness_bands_follow_the_pilot_config() -> None:
    now = datetime(2026, 10, 3, 12, tzinfo=UTC)
    bands = CONFIG.freshness_minutes
    assert freshness(now - timedelta(minutes=30), now, bands) == "current"
    assert freshness(now - timedelta(minutes=31), now, bands) == "recent"
    assert freshness(now - timedelta(hours=5), now, bands) == "aging"
    assert freshness(now - timedelta(hours=11), now, bands) == "stale"
    assert freshness(now - timedelta(hours=13), now, bands) == "expired"
    assert freshness(now + timedelta(hours=1), now, bands) == "future"
    assert not counts_as_current("stale") and not counts_as_current("expired")


# --- Storage --------------------------------------------------------------------------------


def test_repeating_a_snapshot_refreshes_rather_than_duplicates(session, storage) -> None:
    at = _newest_road_time()
    first = _ingest(session, storage, ROADS_SOURCE, ROADS, at)
    decayed = _roads_with(lambda f: f["properties"].update(conf=0.05))
    second = _ingest(session, storage, ROADS_SOURCE, decayed, at + timedelta(minutes=10))
    assert (first.new_states, second.new_states) == (7, 0)
    assert session.scalar(select(func.count()).select_from(FloodObservation)) == 7
    rows = session.scalars(select(FloodObservation)).all()
    assert {row.last_fetch_id for row in rows} == {second.id}
    assert {row.first_fetch_id for row in rows} == {first.id}
    assert all(row.provider_judgement["conf"] == 0.05 for row in rows)


def test_loading_an_older_capture_later_keeps_the_newest_snapshot(session, storage) -> None:
    at = _newest_road_time()
    newer = _ingest(session, storage, ROADS_SOURCE, ROADS, at + timedelta(minutes=30))
    _ingest(session, storage, ROADS_SOURCE, ROADS, at)
    rows = session.scalars(select(FloodObservation)).all()
    assert {row.last_fetch_id for row in rows} == {newer.id}
    roads = current_roads(session, CONFIG, at + timedelta(minutes=31), include_all=True)
    assert len(roads["features"]) == 7


def test_a_changed_state_is_kept_as_history(session, storage) -> None:
    at = _newest_road_time()
    _ingest(session, storage, ROADS_SOURCE, ROADS, at)
    deeper = _roads_with(lambda f: f["properties"].update(depthCm=55))
    fetch = _ingest(session, storage, ROADS_SOURCE, deeper, at + timedelta(minutes=10))
    assert fetch.new_states == 7
    assert session.scalar(select(func.count()).select_from(FloodObservation)) == 14


def test_raw_bytes_are_kept_and_a_bad_file_stores_no_observation(session, storage) -> None:
    at = _newest_road_time()
    fetch = _ingest(session, storage, ROADS_SOURCE, b"{broken", at)
    assert fetch.outcome == FETCH_FORMAT_ERROR
    assert fetch.storage_key and fetch.sha256
    assert session.scalar(select(func.count()).select_from(FloodObservation)) == 0


def test_pull_due_respects_the_interval_and_records_failures(session, storage) -> None:
    now = datetime(2026, 10, 3, 3, tzinfo=UTC)
    calls: list[str] = []

    def fetcher(source):
        calls.append(source.source_id)
        return Pulled(429, None, FETCH_HTTP_ERROR, "Not HTTP 200")

    pull_due(session, storage, CONFIG, now, fetcher)
    pull_due(session, storage, CONFIG, now + timedelta(minutes=5), fetcher)
    pull_due(session, storage, CONFIG, now + timedelta(minutes=10), fetcher)
    # Roads every 10 minutes; reports and the Longdo event feed every 15.
    assert calls == ["floodboard_roads", "floodboard_reports", "longdo_events",
                     "floodboard_roads"]
    outcomes = session.scalars(select(FloodSourceFetch.outcome)).all()
    assert set(outcomes) == {FETCH_HTTP_ERROR}


# --- Reads ----------------------------------------------------------------------------------


def test_source_health_moves_from_ok_to_degraded_to_offline(session, storage) -> None:
    at = _newest_road_time()
    assert sources_status(session, CONFIG, at)[0]["state"] == HEALTH_NEVER
    _ingest(session, storage, ROADS_SOURCE, ROADS, at)
    assert sources_status(session, CONFIG, at + timedelta(minutes=5))[0]["state"] == HEALTH_OK
    _ingest(
        session, storage, ROADS_SOURCE, None, at + timedelta(minutes=10), FETCH_NETWORK_ERROR, None
    )
    later = at + timedelta(minutes=15)
    health = sources_status(session, CONFIG, later)[0]
    assert health["state"] == HEALTH_DEGRADED
    assert health["last_success_at"] == at.isoformat()
    # The last good roads are still served, with their own age (tweak scenario 1).
    assert current_roads(session, CONFIG, later)["snapshot_retrieved_at"] == at.isoformat()
    assert sources_status(session, CONFIG, at + timedelta(hours=13))[0]["state"] == HEALTH_OFFLINE


def test_current_roads_come_from_the_latest_snapshot_only(session, storage) -> None:
    at = _newest_road_time()
    _ingest(session, storage, ROADS_SOURCE, ROADS, at)
    collection = json.loads(ROADS)
    collection["features"] = collection["features"][:3]
    fewer = json.dumps(collection).encode()
    _ingest(session, storage, ROADS_SOURCE, fewer, at + timedelta(minutes=10))
    roads = current_roads(session, CONFIG, at + timedelta(minutes=11), include_all=True)
    assert len(roads["features"]) == 3


def test_expired_roads_lose_their_verdict_and_do_not_count_now(session, storage) -> None:
    at = _newest_road_time()
    _ingest(session, storage, ROADS_SOURCE, ROADS, at)
    fresh = situation(session, CONFIG, at + timedelta(minutes=5))
    old = situation(session, CONFIG, at + timedelta(hours=13))
    # Only the snapshot retrieval time is old here; the segments' own times decide.
    roads_old = current_roads(session, CONFIG, at + timedelta(hours=13))["features"]
    assert all(f["properties"]["provider_verdict"] is None for f in roads_old
               if f["properties"]["freshness"] == "expired")
    assert old["roads_affected_now"] == 0
    assert fresh["roads_affected_now"] + fresh["roads_flood_not_recent"] >= 1
    assert all(not f["properties"]["cleared"] for f in roads_old)


def test_default_road_view_hides_old_cleared_segments(session, storage) -> None:
    at = _newest_road_time() + timedelta(hours=20)
    _ingest(session, storage, ROADS_SOURCE, ROADS, at)
    default = current_roads(session, CONFIG, at)["features"]
    everything = current_roads(session, CONFIG, at, include_all=True)["features"]
    assert len(everything) == 7
    assert all(not f["properties"]["cleared"] for f in default)
    assert len(default) < len(everything)


def test_reports_are_windowed_and_carry_no_text_or_link(session, storage) -> None:
    at = _newest_report_time() + timedelta(minutes=1)
    _ingest(session, storage, REPORTS_SOURCE, REPORTS, at)
    reports = recent_reports(session, CONFIG, at, 24)
    assert len(reports["features"]) == 8
    text = json.dumps(reports)
    assert "redacted" not in text and "fixture-" not in text and "http" not in text
    assert len(recent_reports(session, CONFIG, at, 1)["features"]) <= 8
    before = recent_reports(session, CONFIG, at - timedelta(days=2), 24)
    assert before["features"] == []


# --- API helpers ----------------------------------------------------------------------------


def test_as_of_refuses_the_future_and_naive_times() -> None:
    with pytest.raises(GrpError):
        _as_of((datetime.now(UTC) + timedelta(hours=1)).isoformat())
    with pytest.raises(GrpError):
        _as_of("2026-10-03T10:00:00")
    assert _as_of("2026-10-02T10:00:00+07:00") == datetime(2026, 10, 2, 3, tzinfo=UTC)


def test_unknown_pilot_has_no_config() -> None:
    assert pilot_config("../etc") is None
    assert CONFIG.hubs == ("adpc",)


def test_demo_area_is_bangkok_and_nonthaburi_and_rain_stays_on_four() -> None:
    from core.flood_evidence.areas import pilot_areas, pilot_subdistricts
    from core.river_watch import bangkok_outlines

    names = {a["admin_code"]: a["name"] for a in bangkok_outlines()}
    assert len(names) == 50
    nonthaburi = ["1201", "1202", "1203", "1204", "1205", "1206"]
    assert sorted(CONFIG.demo_corridor["areas"]) == sorted(names) + nonthaburi
    captured = {a["admin_code"]: a for a in pilot_areas(CONFIG)}
    assert sorted(captured) == sorted(CONFIG.demo_corridor["areas"])
    assert captured["1204"]["name"] == "Bang Bua Thong" and captured["1204"]["outline"]
    subdistricts = pilot_subdistricts(CONFIG)
    assert len(subdistricts) == 232
    assert all(a["parent_code"] in CONFIG.demo_corridor["areas"] for a in subdistricts)
    assert {a["parent_code"] for a in subdistricts} == set(CONFIG.demo_corridor["areas"])
    assert all(a["outline"]["type"] in {"Polygon", "MultiPolygon"} for a in subdistricts)
    assert [names[code] for code in CONFIG.rain_areas] == [
        "Bang Sue", "Chatuchak", "Bang Kapi", "Lat Krabang"
    ]


def test_a_road_is_found_by_its_short_id_in_the_latest_snapshot(session, storage) -> None:
    from core.flood_evidence.situation import road_by_id

    at = _newest_road_time()
    _ingest(session, storage, ROADS_SOURCE, ROADS, at)
    road = current_roads(session, CONFIG, at, include_all=True)["features"][0]
    found = road_by_id(session, CONFIG, at, road["properties"]["id"])
    assert found["geometry"] == road["geometry"]
    assert road_by_id(session, CONFIG, at, "0" * 16) is None


def test_a_longdo_event_relayed_by_floodboard_counts_once_as_the_direct_copy(
    session, storage
) -> None:
    from core.flood_evidence.longdo_events import BANGKOK_TIME

    at = _newest_report_time() + timedelta(minutes=1)
    start = at.astimezone(BANGKOK_TIME).strftime("%Y-%m-%d %H:%M:%S")
    stop = (at + timedelta(hours=3)).astimezone(BANGKOK_TIME).strftime("%Y-%m-%d %H:%M:%S")
    header = REPORTS.decode("utf-8-sig").splitlines()[0]
    relayed = (header + '\n"longdo:42","' + (at - timedelta(minutes=1)).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z") + '","13.80","100.55","longdo","crowd","","false","false",'
        '"false","0.5","",""\n').encode()
    _ingest(session, storage, REPORTS_SOURCE, relayed, at)
    event = json.dumps([{"eid": "42", "title": "น้ำท่วม (ผ่านได้)", "title_en": "Flood",
                         "start": start, "stop": stop, "latitude": "13.80", "longitude": "100.55",
                         "contributor": "DOH Admin", "icon": "flood", "type": "6",
                         "description": "x", "severity": ""}]).encode()
    _ingest(session, storage, CONFIG.source("longdo_events"), event, at)
    reports = [f for f in recent_reports(session, CONFIG, at + timedelta(minutes=1), 6)["features"]
               if f["properties"]["observed_at"].startswith(at.strftime("%Y-%m-%dT%H"))]
    sources = [f["properties"]["underlying_source"] for f in reports]
    assert sources.count("doh") == 1 and "longdo" not in sources
