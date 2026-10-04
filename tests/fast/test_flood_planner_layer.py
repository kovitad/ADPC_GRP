"""Live reported flooding for a Planner area (ADR-0056, step 2)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

import core.flood_evidence.planner_layer as layer

NOW = datetime(2026, 10, 4, 7, 0, tzinfo=UTC)


def _incident(incident_id: str, codes: list[str] | None, keys: list[str], **extra) -> dict:
    return {"incident_id": incident_id, "status": "active", "confidence": "medium",
            "reasons": ["two_families"], "source_families": ["crowd", "traffy"],
            "max_depth_cm": 20, "newest_evidence_at": NOW.isoformat(), "freshness": "current",
            "center": [100.55, 13.82], "district_codes": codes, "road_keys": keys, **extra}


def _road(key: str) -> dict:
    return {"type": "Feature", "geometry": {"type": "LineString",
                                            "coordinates": [[100.55, 13.82], [100.551, 13.82]]},
            "properties": {"id": key, "name": "ถนน", "name_en": "Road", "depth_cm": 20,
                           "closed_all": False, "freshness": "current",
                           "reported_at": NOW.isoformat()}}


@pytest.fixture(autouse=True)
def stored(monkeypatch):
    incidents = [
        _incident("in-chatuchak", ["1030"], ["a" * 16],
                  verification="officer_saw_dry", officer={"name": "someone"}),
        _incident("on-border", ["1029", "1030"], ["b" * 16]),
        _incident("in-lat-krabang", ["1011"], ["c" * 16]),
        _incident("not-placed-yet", None, ["d" * 16]),
    ]
    monkeypatch.setattr(layer, "list_incidents", lambda _s, _c, _now: {
        "incidents": incidents, "last_processed_at": NOW.isoformat(),
        "rule_version": "IncidentGrouping v0.1"})
    monkeypatch.setattr(layer, "current_roads", lambda _s, _c, _now, include_all=False: {
        "features": [_road(k * 16) for k in "abcde"],
        "snapshot_retrieved_at": NOW.isoformat()})
    monkeypatch.setattr(layer, "latest_exposure", lambda _s, _c, _now: {"assets": [
        _asset("ddpm:1", "evacuation_centre", "1030", ["a" * 16], 90),
        _asset("osm:node/2", "hospital", "1030", ["b" * 16], 40,
               access="access_disrupted_confirmed",
               reasons=["officer_confirmed_access_disrupted", "no_road_network"]),
        _asset("osm:node/3", "school", "1030", [], None, exposure="no_report_nearby"),
        _asset("osm:node/4", "school", "1011", ["c" * 16], 30),
    ]})
    monkeypatch.setattr(layer, "camera_registry", lambda _pilot: ())
    monkeypatch.setattr(layer, "nearby_cameras", lambda _reg, _geom, _now, _radius: [
        _camera("bmatraffic:1362", "BMA_TRAFFIC", "1362", 120),
        _camera("itic:9", "ITIC", "9", 50),
    ])


def _asset(asset_id, asset_type, district, keys, distance, *, access="access_unknown",
           exposure="potentially_exposed", reasons=None) -> dict:
    return {"asset_id": asset_id, "asset_type": asset_type, "name": asset_id, "name_en": "",
            "lat": 13.82, "lon": 100.55, "district_code": district, "exposure_state": exposure,
            "access_state": access, "nearest_distance_m": distance, "road_keys": keys,
            "reasons": reasons or ["no_road_network"], "source": "OpenStreetMap",
            "officer": {"name": "someone"} if access == "access_disrupted_confirmed" else None}


def _camera(camera_id, provider, number, distance) -> dict:
    return {"camera_id": camera_id, "provider": provider, "provider_camera_id": number,
            "name": {"en": f"Camera {number}", "th": f"กล้อง {number}"}, "lat": 13.82,
            "lon": 100.55, "status": "online", "viewer_url": "https://example.test/view",
            "placeholder": False, "source_label": provider, "distance_m": distance}


def test_a_district_gets_its_incidents_including_those_across_its_border() -> None:
    result = layer.live_layer(None, "adpc", "1030", "district", NOW)
    assert result["available"] and result["district_name"] == "Chatuchak"
    assert [i["incident_id"] for i in result["incidents"]] == ["in-chatuchak", "on-border"]
    assert {f["properties"]["id"] for f in result["roads"]["features"]} == {"a" * 16, "b" * 16}
    assert result["rolled_up_from"] is None
    assert "not a flood map" in result["title"]["en"]


def test_a_sub_district_shows_its_parent_district_and_says_so() -> None:
    result = layer.live_layer(None, "adpc", "103005", "subdistrict", NOW)
    assert result["district_code"] == "1030" and result["rolled_up_from"] == "103005"


def test_officer_checks_never_reach_the_planner_layer() -> None:
    result = layer.live_layer(None, "adpc", "1030", "district", NOW)
    text = str(result)
    assert "officer" not in text and "verification" not in text and "someone" not in text


def test_incidents_without_a_district_yet_are_named_as_a_gap() -> None:
    result = layer.live_layer(None, "adpc", "1030", "district", NOW)
    assert result["gaps"] and "cannot be placed" in result["gaps"][0]


def test_outside_bangkok_and_other_hubs_are_told_plainly() -> None:
    outside = layer.live_layer(None, "adpc", "3415", "district", NOW)
    assert not outside["available"] and outside["reason"] == "outside_coverage"
    other_hub = layer.live_layer(None, "other", "1030", "district", NOW)
    assert not other_hub["available"] and other_hub["reason"] == "hub_not_enabled"


def test_planner_facts_drop_officer_judgements_but_keep_computed_values() -> None:
    from core.flood_evidence.planner_answer import _without_officer_judgements

    facts = [
        {"id": "S", "kind": "situation", "active_incidents": 3,
         "facilities_access_confirmed_cut": 1},
        {"id": "C", "kind": "changes", "officer_checks": 2, "new_incidents": 1},
        {"id": "I1", "kind": "incident", "officer_check": "officer_saw_dry", "confidence": "low"},
        {"id": "F1", "kind": "facility", "access": "access_disrupted_confirmed", "name": "A"},
        {"id": "F2", "kind": "facility", "access": "access_under_review", "name": "B"},
    ]
    cleaned = _without_officer_judgements(facts)
    text = str(cleaned)
    assert "officer" not in text and "confirmed" not in text
    assert cleaned[0]["active_incidents"] == 3 and cleaned[2]["confidence"] == "low"
    assert cleaned[4]["access"] == "access_under_review"
    assert facts[2]["officer_check"] == "officer_saw_dry"  # the input is not changed


def test_planner_live_facts_refuse_areas_outside_bangkok_and_other_hubs() -> None:
    from core.flood_evidence.planner_answer import live_facts

    assert live_facts(None, "adpc", "3303", "district")["reason"] == "outside_coverage"
    assert live_facts(None, "other", "1011", "district")["reason"] == "hub_not_enabled"


def test_facilities_near_flooding_in_the_district_are_listed_without_officer_states() -> None:
    result = layer.live_layer(None, "adpc", "1030", "district", NOW)
    ids = [f["asset_id"] for f in result["facilities"]]
    assert ids == ["ddpm:1", "osm:node/2"]  # DDPM centres first; no unexposed or other district
    centre, hospital = result["facilities"]
    assert centre["incident_ids"] == ["in-chatuchak"] and centre["source"].startswith("DDPM")
    assert hospital["access_state"] == "access_unknown"
    assert "officer" not in str(result["facilities"])


def test_cameras_are_shared_across_incidents_and_only_relay_cameras_get_a_picture() -> None:
    with_relay = layer.live_layer(None, "adpc", "1030", "district", NOW, relay=True)
    first, second = with_relay["cameras"]
    assert first["camera_id"] == "bmatraffic:1362"
    assert first["picture_url"].endswith("/cameras/bmatraffic%3A1362/frame.jpg")
    assert sorted(first["incident_ids"]) == ["in-chatuchak", "on-border"]
    assert second["picture_url"] is None
    without = layer.live_layer(None, "adpc", "1030", "district", NOW, relay=False)
    assert all(c["picture_url"] is None for c in without["cameras"])
