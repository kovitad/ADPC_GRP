"""Longdo event feed (ADR-0048): flood events only, Bangkok time, families, never "dry"."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from core.flood_evidence.incidents import Params, build_incidents
from core.flood_evidence.longdo_events import contributor_family, parse_events
from core.flood_evidence.observation import SourceFormatError

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "longdo" / "events_20261003.json"
BODY = FIXTURE.read_bytes()
# 15:30 Bangkok time on 3 October: every fixture flood event is still active then.
AT = datetime(2026, 10, 3, 8, 30, tzinfo=UTC)


def test_only_active_flood_events_inside_the_region_are_kept() -> None:
    drafts = parse_events(BODY, AT)
    ids = {d.external_id for d in drafts}
    raw = json.loads(BODY)
    accident = next(e for e in raw if e["icon"] != "flood")
    assert f"longdo:{accident['eid']}" not in ids
    assert "longdo:999999" not in ids  # the Chiang Mai copy
    assert len(drafts) == 6


def test_times_are_bangkok_time_and_expired_events_are_dropped() -> None:
    drafts = {d.external_id: d for d in parse_events(BODY, AT)}
    itic = next(d for d in drafts.values() if d.underlying_sources == ("itic",)
                and d.observed_at.hour == 7)
    assert itic.observed_at == datetime(2026, 10, 3, 7, 51, tzinfo=UTC)  # 14:51 in Bangkok
    later = datetime(2026, 10, 3, 9, 0, tzinfo=UTC)  # 16:00 Bangkok: the 15:51 event has ended
    assert itic.external_id not in {d.external_id for d in parse_events(BODY, later)}


def test_passable_is_still_flooding_and_not_passable_is_closed() -> None:
    drafts = parse_events(BODY, AT)
    closed = [d for d in drafts if d.state["closed_all"]]
    passable = [d for d in drafts if d.state["passable_stated"]]
    assert len(closed) == 1 and len(passable) == 2
    assert all(not d.state["cleared"] for d in drafts)


def test_contributors_become_families_and_names_are_not_kept() -> None:
    drafts = parse_events(BODY, AT)
    assert {d.underlying_sources[0] for d in drafts} == {"doh", "itic", "longdo_user"}
    text = json.dumps([[d.state, d.provider_judgement, d.external_id] for d in drafts],
                      ensure_ascii=False)
    assert "someone" not in text and "DOH Admin" not in text and "redacted" not in text
    assert contributor_family("itic.someone") == "itic"


@pytest.mark.parametrize("body", [b"not json", b'{"a": 1}', b'[{"eid": "1"}]'])
def test_a_changed_feed_shape_is_refused(body) -> None:
    with pytest.raises(SourceFormatError):
        parse_events(body, AT)


def test_a_doh_report_next_to_a_floodboard_road_makes_an_incident_high() -> None:
    event = next(d for d in parse_events(BODY, AT) if d.underlying_sources == ("doh",))
    lon, lat = event.geometry["coordinates"]
    road = {"type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [[lon, lat], [lon + 0.0004, lat]]},
            "properties": {"id": "a" * 16, "cleared": False, "freshness": "current", "depth_cm": 20,
                           "closed_all": False, "underlying_sources": ["traffy"],
                           "evidence_class": "observed", "provider_verdict": None,
                           "reported_at": AT.isoformat()}}
    report = {"type": "Feature", "geometry": event.geometry,
              "properties": {"id": "r1", "underlying_source": "doh", "depth_cm": None,
                             "cleared": False, "observed_at": AT.isoformat(),
                             "freshness": "current", "evidence_class": "observed"}}
    area = [{"type": "Polygon", "coordinates": [[[lon - 1, lat - 1], [lon + 1, lat - 1],
                                                [lon + 1, lat + 1], [lon - 1, lat + 1],
                                                [lon - 1, lat - 1]]]}]
    [incident] = build_incidents([road], [report], area, AT, Params(bands={
        "current": 30, "recent": 120, "aging": 360, "stale": 720}))
    assert incident["confidence"] == "high" and "doh_report" in incident["reasons"]
