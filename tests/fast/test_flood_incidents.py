"""Incidents (ADR-0041): spec scenarios A-D, independence, conflict, identity and ordering."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import core.flood_evidence.incident_store as store
from core.db import Base
from core.flood_evidence.config import pilot_config
from core.flood_evidence.incidents import Params, build_incidents, priority
from core.flood_evidence.models import (
    FETCH_OK,
    FloodIncident,
    FloodIncidentEvent,
    FloodSourceFetch,
)

CONFIG = pilot_config("bangkok")
NOW = datetime(2026, 10, 3, 4, 0, tzinfo=UTC)
PARAMS = Params(bands=CONFIG.freshness_minutes)
# A square area around Pracha Chuen Road in Bang Sue.
AREA = [{"type": "Polygon", "coordinates": [[[100.53, 13.83], [100.56, 13.83], [100.56, 13.85],
                                               [100.53, 13.85], [100.53, 13.83]]]}]
# The same square cut into two made-up districts at longitude 100.542.
HALVES = [
    ("WEST", {"type": "Polygon", "coordinates": [[[100.53, 13.83], [100.542, 13.83],
                                                  [100.542, 13.85], [100.53, 13.85],
                                                  [100.53, 13.83]]]}),
    ("EAST", {"type": "Polygon", "coordinates": [[[100.542, 13.83], [100.56, 13.83],
                                                  [100.56, 13.85], [100.542, 13.85],
                                                  [100.542, 13.83]]]}),
]
X0, Y0 = 100.5400, 13.8400
STEP = 0.0005  # about 55 m


def road(key: str, dx: float = 0.0, dy: float = 0.0, *, cleared=False, fresh="current",
         sources=("traffy",), derived=False, closed=False, minutes=10):
    x, y = X0 + dx, Y0 + dy
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": [[x, y], [x + 0.0004, y]]},
        "properties": {
            "id": key, "cleared": cleared, "freshness": fresh, "depth_cm": 20,
            "closed_all": closed, "underlying_sources": list(sources),
            "evidence_class": "provider_derived" if derived else "observed",
            "provider_verdict": {"motorbike": "risky", "sedan": "risky", "pickup": "caution",
                                 "truck": "caution"},
            "reported_at": (NOW - timedelta(minutes=minutes)).isoformat(),
        },
    }


def report(key: str, source: str, dx: float = 0.0002, dy: float = 0.0003, *, depth=30,
           cleared=False, minutes=10, fresh="current"):
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [X0 + dx, Y0 + dy]},
        "properties": {
            "id": key, "underlying_source": source, "depth_cm": depth, "cleared": cleared,
            "observed_at": (NOW - timedelta(minutes=minutes)).isoformat(), "freshness": fresh,
            "evidence_class": "observed",
        },
    }


def one(roads, reports):
    found = build_incidents(roads, reports, AREA, NOW, PARAMS)
    assert len(found) == 1
    return found[0]


def test_scenario_a_sensor_and_citizen_together_are_high() -> None:
    incident = one([road("a" * 16, sources=("bma_sensor", "crowd"))],
                   [report("r1", "bma_sensor", depth=37), report("r2", "crowd", depth=40)])
    assert incident["confidence"] == "high"
    assert incident["source_families"] == ["bma", "crowd"]
    assert incident["freshness_basis"] == "newest_report"


def test_scenario_b_sensor_reading_zero_is_a_conflict_not_an_average() -> None:
    incident = one([road("a" * 16, sources=("crowd",))],
                   [report("r1", "crowd", depth=80), report("s1", "bma_sensor", depth=0)])
    assert incident["confidence"] == "conflicting"
    assert incident["conflict"] and "sensor_reads_zero_nearby" in incident["reasons"]
    assert incident["contrary_keys"] == ["s1"]
    assert incident["max_depth_cm"] == 80  # the flooding claim is kept, never averaged with 0


def test_scenario_c_two_independent_citizen_channels_without_a_sensor_are_medium() -> None:
    incident = one([road("a" * 16, sources=("traffy", "crowd"))],
                   [report("r1", "traffy"), report("r2", "crowd")])
    assert incident["confidence"] == "medium"
    assert "bma_reading" not in incident["reasons"]


def test_many_reports_of_one_kind_stay_low() -> None:
    reports = [report(f"t{i}", "traffy", dx=0.0001 * i) for i in range(5)]
    incident = one([road("a" * 16)], reports)
    assert incident["confidence"] == "low"
    assert "several_reports_one_type" in incident["reasons"]


def test_floodboard_cluster_and_news_never_count_as_sources() -> None:
    incident = one([road("a" * 16, sources=("cluster",), derived=True)], [report("n1", "news")])
    assert incident["source_families"] == []
    assert incident["confidence"] == "low"
    assert "floodboard_inferred_only" in incident["reasons"]
    assert incident["report_keys"] == []


def test_freshness_comes_from_the_newest_report_and_falls_back_with_a_label() -> None:
    with_report = one([road("a" * 16, minutes=2)], [report("r1", "traffy", minutes=200)])
    assert with_report["freshness"] == "aging" and with_report["freshness_basis"] == "newest_report"
    alone = one([road("a" * 16, minutes=2)], [])
    assert alone["freshness_basis"] == "floodboard_update"
    assert "freshness_from_floodboard_update" in alone["reasons"]


def test_scenario_d_stale_and_cleared_evidence_starts_no_incident() -> None:
    roads = [road("a" * 16, fresh="stale"), road("b" * 16, dx=0.002, cleared=True)]
    assert build_incidents(roads, [], AREA, NOW, PARAMS) == []


def test_nearby_segments_group_and_far_ones_do_not() -> None:
    roads = [road("a" * 16), road("b" * 16, dx=STEP * 1.2), road("c" * 16, dx=0.01)]
    found = build_incidents(roads, [], AREA, NOW, PARAMS)
    assert sorted(len(i["road_keys"]) for i in found) == [1, 2]


def test_evidence_outside_the_area_is_ignored() -> None:
    outside = road("a" * 16, dx=0.1)
    assert build_incidents([outside], [], AREA, NOW, PARAMS) == []


def test_priority_puts_conflict_then_access_then_hospital_then_least_certain_first() -> None:
    base = {"conflict": False, "confidence": "high", "road_keys": ["z"]}
    queue = sorted([
        {**base, "road_keys": ["high"]},
        {**base, "road_keys": ["low"], "confidence": "low"},
        {**base, "road_keys": ["hospital"], "hospital_near": True},
        {**base, "road_keys": ["access"], "access_to_check": True},
        {**base, "road_keys": ["conflict"], "conflict": True, "confidence": "conflicting"},
    ], key=priority)
    assert [i["road_keys"][0] for i in queue] == ["conflict", "access", "hospital", "low", "high"]


# --- Identity across snapshots --------------------------------------------------------------


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db


@pytest.fixture
def snapshots(session, monkeypatch):
    """Feed update_incidents a chosen list of roads per snapshot, without Floodboard."""

    state = {"roads": []}
    monkeypatch.setattr(store, "demo_outlines", lambda _config: AREA)
    monkeypatch.setattr(store, "demo_areas", lambda _config: HALVES)
    monkeypatch.setattr(store, "demo_subdistrict_areas", lambda _session, _config: HALVES)
    monkeypatch.setattr(store, "current_roads",
                        lambda _s, _c, _at: {"features": state["roads"]})
    monkeypatch.setattr(store, "recent_reports", lambda _s, _c, _at, _h: {"features": []})
    monkeypatch.setattr(store, "latest_exposure", lambda _s, _c, _at: {"assets": []})

    def run(at: datetime, roads):
        state["roads"] = roads
        fetch = FloodSourceFetch(pilot_id="bangkok", source_id="floodboard_roads", url="x",
                                 retrieved_at=at, outcome=FETCH_OK)
        session.add(fetch)
        session.flush()
        result = store.update_incidents(session, CONFIG, fetch)
        session.commit()
        return result

    return run


def _open(session):
    return list(session.scalars(select(FloodIncident).where(FloodIncident.status != "closed")))


def _kinds(session):
    return [e.kind for e in session.scalars(select(FloodIncidentEvent).order_by(
        FloodIncidentEvent.at, FloodIncidentEvent.kind))]


def test_an_incident_keeps_its_id_and_recedes_then_closes(session, snapshots) -> None:
    snapshots(NOW, [road("a" * 16)])
    [incident] = _open(session)
    snapshots(NOW + timedelta(minutes=10), [road("a" * 16), road("b" * 16, dx=STEP)])
    assert [i.id for i in _open(session)] == [incident.id]
    snapshots(NOW + timedelta(minutes=20), [])
    assert session.get(FloodIncident, incident.id).status == "receding"
    snapshots(NOW + timedelta(hours=3), [])
    assert session.get(FloodIncident, incident.id).status == "closed"
    assert _kinds(session) == ["created", "size_changed", "receding", "closed"]


def test_a_recut_segment_nearby_continues_the_same_incident(session, snapshots) -> None:
    snapshots(NOW, [road("a" * 16)])
    [incident] = _open(session)
    # Floodboard re-cut the road: a new hash, slightly shifted.
    snapshots(NOW + timedelta(minutes=10), [road("c" * 16, dx=0.0001)])
    assert [i.id for i in _open(session)] == [incident.id]


def test_two_incidents_that_join_merge_into_the_oldest(session, snapshots) -> None:
    snapshots(NOW, [road("a" * 16)])
    snapshots(NOW + timedelta(minutes=10), [road("a" * 16), road("b" * 16, dx=0.004)])
    older = session.scalar(select(FloodIncident).where(FloodIncident.road_keys.is_not(None))
                           .order_by(FloodIncident.opened_at))
    snapshots(NOW + timedelta(minutes=20),
              [road("a" * 16), road("m" * 16, dx=0.002), road("b" * 16, dx=0.004),
               road("n" * 16, dx=0.001), road("o" * 16, dx=0.003)])
    [survivor] = _open(session)
    assert survivor.id == older.id
    assert "merged" in _kinds(session) and "absorbed" in _kinds(session)


def test_an_incident_that_loses_its_middle_splits_and_one_part_keeps_its_id(
    session, snapshots
) -> None:
    chain = [road(k * 16, dx=i * STEP) for i, k in enumerate("abcd")]
    snapshots(NOW, chain)
    [original] = _open(session)
    # The middle two segments clear: what is left is two groups about 120 m apart.
    snapshots(NOW + timedelta(minutes=10), [chain[0], chain[3]])
    parts = {tuple(i.road_keys): i.id for i in _open(session)}
    assert parts[("a" * 16,)] == original.id
    assert parts[("d" * 16,)] != original.id
    split = session.scalar(select(FloodIncidentEvent).where(FloodIncidentEvent.kind == "split"))
    assert split.detail["from_incident"] == str(original.id)


def test_an_older_snapshot_never_rewrites_history(session, snapshots) -> None:
    assert snapshots(NOW, [road("a" * 16)]) == 1
    assert snapshots(NOW - timedelta(minutes=30), []) is None
    [incident] = _open(session)
    assert incident.status == "active"


# --- District codes (ADR-0056) --------------------------------------------------------------


def test_district_codes_list_every_district_a_geometry_reaches() -> None:
    from core.flood_evidence.geo import district_codes

    inside = road("a" * 16)["geometry"]                 # 100.5400 to 100.5404
    across = road("b" * 16, dx=0.0018)["geometry"]      # 100.5418 to 100.5422
    assert district_codes(inside, HALVES) == ["WEST"]
    assert district_codes(across, HALVES) == ["EAST", "WEST"]


def test_incidents_store_their_district_codes_once_in_the_worker(session, snapshots) -> None:
    snapshots(NOW, [road("a" * 16), road("b" * 16, dx=STEP), road("c" * 16, dx=2 * STEP),
                    road("d" * 16, dx=3 * STEP), road("e" * 16, dx=4 * STEP)])
    [incident] = _open(session)
    assert incident.summary["district_codes"] == ["EAST", "WEST"]
    assert incident.summary["subdistrict_codes"] == ["EAST", "WEST"]
    snapshots(NOW + timedelta(minutes=10), [road("a" * 16)])
    stored = session.get(FloodIncident, incident.id).summary
    assert stored["district_codes"] == ["WEST"]
    assert stored["subdistrict_codes"] == ["WEST"]
