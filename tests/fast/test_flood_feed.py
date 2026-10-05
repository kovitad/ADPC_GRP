"""The live flood feed for Global Risk (ADR-0052)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

import core.flood_evidence.feed as feed
from core.flood_evidence.config import pilot_config

NOW = datetime(2026, 10, 5, 2, 0, tzinfo=UTC)
ROAD = "a" * 16


def _incident(**extra):
    return {"incident_id": "inc-1", "status": "active", "confidence": "high",
            "reasons": ["two_families", "officer_saw_water"], "source_families": ["bma", "traffy"],
            "road_keys": [ROAD], "report_keys": ["r-traffy", "r-longdo"],
            "district_codes": ["1030", "1029"], "bbox": [100.5, 13.8, 100.51, 13.81],
            "center": [100.505, 13.805], "opened_at": "2026-10-05T01:00:00+00:00",
            "newest_evidence_at": "2026-10-05T01:50:00+00:00", "verification": "unverified",
            **extra}


@pytest.fixture
def stored(monkeypatch):
    state = {"incidents": [_incident()]}
    monkeypatch.setattr(feed, "list_incidents", lambda *_a: {
        "incidents": state["incidents"], "last_processed_at": "2026-10-05T01:55:00+00:00",
        "rule_version": "IncidentGrouping v0.1"})
    monkeypatch.setattr(feed, "current_roads", lambda *_a, **_k: {
        "snapshot_retrieved_at": "2026-10-05T01:55:00+00:00",
        "features": [{"properties": {"id": ROAD, "name": "ถนนวิภาวดี", "name_en": "Vibhavadi Road",
                                     "depth_cm": 20, "reported_at": "2026-10-05T01:40:00+00:00"}}]})
    monkeypatch.setattr(feed, "recent_reports", lambda *_a: {"features": [
        {"properties": {"id": "r-traffy", "underlying_source": "traffy", "depth_cm": 30,
                        "observed_at": "2026-10-05T01:50:00+00:00"}},
        {"properties": {"id": "r-longdo", "underlying_source": "itic", "depth_cm": 90,
                        "observed_at": "2026-10-05T01:58:00+00:00"}}]})
    monkeypatch.setattr(feed, "latest_exposure", lambda *_a: {"assets": [
        {"asset_type": "school", "exposure_state": "potentially_exposed", "road_keys": [ROAD]},
        {"asset_type": "hospital", "exposure_state": "no_report_nearby", "road_keys": []},
        {"asset_type": "evacuation_centre", "exposure_state": "potentially_exposed",
         "road_keys": [ROAD]}]})
    return state


def _build():
    return feed.build_feed(None, pilot_config("bangkok"), NOW)


def test_every_district_is_listed_least_concern_first(stored) -> None:
    body = _build()
    codes = [d["district_code"] for d in body["districts"]]
    assert len(codes) == 56 and {"1030", "1029", "1204"} <= set(codes)
    assert codes[-2:] == ["1029", "1030"]  # the two districts with a high incident come last
    quiet = body["districts"][0]
    assert quiet["active_incidents"] == 0 and quiet["worst_confidence"] is None
    assert all(d["valid_until"] == "2026-10-05T02:25:00Z" for d in body["districts"])


def test_an_incident_across_a_border_lists_both_districts(stored) -> None:
    record = _build()["records"][0]
    assert record["district_codes"] == ["1029", "1030"]
    assert len(record["district_names_en"]) == 2 and record["road_names_en"] == ["Vibhavadi Road"]
    assert record["evidence_class"] == "crowd_and_official_mix"


def test_longdo_values_and_officer_reasons_never_reach_the_feed(stored) -> None:
    record = _build()["records"][0]
    assert record["max_depth_cm"] == 30  # the iTIC report said 90
    assert record["report_count"] == 1
    assert record["last_evidence_at"] == "2026-10-05T01:50:00Z"
    assert record["confidence_reasons"] == ["two_families"]
    assert "itic" not in record["source_families"]


def test_facility_counts_are_openstreetmap_only(stored) -> None:
    body = _build()
    assert body["records"][0]["facilities_nearby"] == {"school": 1, "hospital": 0, "clinic": 0}
    assert "evacuation_centre" not in json.dumps(body)


def test_an_officer_review_gives_byte_identical_feed(stored) -> None:
    plain, _ = feed.serialise(_build())
    stored["incidents"] = [_incident(verification="officer_confirmed",
                                     officer={"name": "someone", "note": "saw water"})]
    reviewed, _ = feed.serialise(_build())
    assert plain == reviewed


def test_no_free_text_names_links_or_cameras(stored) -> None:
    blob = feed.serialise(_build())[0].decode()
    for word in ("verification", "officer", "camera_id", "viewer_url", "picture", "r-traffy"):
        assert word not in blob


def test_no_incidents_still_gives_every_district(stored) -> None:
    stored["incidents"] = []
    body = _build()
    assert body["records"] == [] and len(body["districts"]) == 56
    assert body["as_of"] == "2026-10-05T01:55:00Z"


def test_serialisation_is_stable(stored) -> None:
    first = feed.serialise(_build())
    assert first == feed.serialise(_build())
    assert first[1].startswith('"') and len(first[1]) == 34
