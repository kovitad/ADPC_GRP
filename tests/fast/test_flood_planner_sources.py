"""The Planner's Live layer sources for the whole pilot area (ADR-0058)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

import core.flood_evidence.planner_sources as ps

NOW = datetime(2026, 10, 4, 13, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def stored(monkeypatch):
    road = {"type": "Feature", "geometry": {"type": "LineString",
                                            "coordinates": [[100.5, 13.8], [100.51, 13.8]]},
            "properties": {"id": "a" * 16, "name": "ถนน", "name_en": "Road", "depth_cm": 20,
                           "closed_all": False, "cleared": False, "freshness": "current",
                           "reported_at": NOW.isoformat(), "provider_verdict": {"truck": "ok"}}}
    monkeypatch.setattr(ps, "current_roads", lambda *_a, **_k: {
        "features": [road], "snapshot_retrieved_at": NOW.isoformat()})
    monkeypatch.setattr(ps, "list_incidents", lambda *_a: {"incidents": [
        {"incident_id": "inc-1", "status": "active", "confidence": "high", "reasons": [],
         "source_families": ["bma", "traffy"], "road_keys": ["a" * 16], "report_keys": ["r1"],
         "verification": "officer_saw_dry", "officer": {"name": "someone"}}]})
    monkeypatch.setattr(ps, "recent_reports", lambda *_a: {"features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [100.5, 13.8]},
         "properties": {"underlying_source": source, "depth_cm": 10, "cleared": False,
                        "closed_all": False, "observed_at": NOW.isoformat(),
                        "freshness": "current", "id": "should-not-pass"}}
        for source in ("traffy", "crowd", "bma_sensor", "itic", "news")]})
    monkeypatch.setattr(ps, "latest_exposure", lambda *_a: {"assets": [
        {"asset_id": "osm:node/1", "asset_type": "hospital", "name": "H", "lat": 13.8,
         "lon": 100.5, "district_code": "1030", "exposure_state": "potentially_exposed",
         "nearest_distance_m": 40, "access_state": "access_disrupted_confirmed",
         "road_keys": ["a" * 16], "reasons": ["officer_confirmed_access_disrupted"],
         "officer": {"name": "someone"}, "source": "OpenStreetMap"},
        {"asset_id": "ddpm:2", "asset_type": "evacuation_centre", "name": "E", "lat": 13.9,
         "lon": 100.4, "district_code": "1201", "exposure_state": "no_report_nearby",
         "nearest_distance_m": None, "access_state": "access_unknown", "road_keys": [],
         "reasons": [], "source": "DDPM"},
    ]})
    cameras = [
        SimpleNamespace(camera_id="bmatraffic:7", provider="BMA_TRAFFIC", provider_camera_id="7",
                        name={"en": "A"}, source_label="BMA", lat=13.8, lon=100.5,
                        status="unknown", viewer_url="http://x", placeholder=False),
        SimpleNamespace(camera_id="pakkret:CAMPK001", provider="PAKKRET_CCTV",
                        provider_camera_id="CAMPK001", name={"en": "B"}, source_label="Pak Kret",
                        lat=13.9, lon=100.5, status="unknown", viewer_url="https://y",
                        placeholder=False),
        SimpleNamespace(camera_id="bma:1", provider="BMA_DDS", provider_camera_id="1",
                        name={"en": "C"}, source_label="BMA DDS", lat=13.8, lon=100.6,
                        status="unknown", viewer_url="https://z", placeholder=False),
    ]
    monkeypatch.setattr(ps, "camera_registry", lambda _pilot: cameras)


def test_roads_link_to_incidents_without_officer_checks() -> None:
    body = ps.source(None, "adpc", "roads", relay=False, now=NOW)
    feature = body["roads"]["features"][0]
    assert feature["properties"]["incident_id"] == "inc-1"
    assert "provider_verdict" not in feature["properties"]
    assert "officer" not in str(body) and "verification" not in str(body)
    assert body["incidents"][0]["report_count"] == 1


def test_reports_are_grouped_by_kind_and_carry_no_ids() -> None:
    body = ps.source(None, "adpc", "reports", relay=False, now=NOW)
    groups = [f["properties"]["group"] for f in body["reports"]["features"]]
    assert groups == ["rep_traffy", "rep_crowd", "rep_bma", "rep_longdo", "rep_other"]
    assert "should-not-pass" not in str(body)


def test_facilities_never_show_an_officer_confirmed_state() -> None:
    body = ps.source(None, "adpc", "facilities", relay=False, now=NOW)
    hospital, centre = body["facilities"]
    assert hospital["access_state"] == "access_unknown" and hospital["incident_ids"] == ["inc-1"]
    assert centre["source"].startswith("DDPM")
    assert "officer" not in str(body)


def test_only_relayed_cameras_get_a_picture_and_only_when_the_relay_is_on() -> None:
    on = {c["camera_id"]: c for c in ps.source(None, "adpc", "cameras", relay=True)["cameras"]}
    assert on["bmatraffic:7"]["picture_url"] and on["pakkret:CAMPK001"]["picture_url"]
    assert on["bma:1"]["picture_url"] is None
    assert {c["group"] for c in on.values()} == {"cam_traffic", "cam_pakkret", "cam_bma"}
    off = ps.source(None, "adpc", "cameras", relay=False)["cameras"]
    assert all(c["picture_url"] is None for c in off)


def test_the_summary_counts_every_switch_and_other_hubs_get_nothing() -> None:
    counts = ps.summary(None, "adpc", relay=True, now=NOW)["counts"]
    assert counts["roads"] == 1 and counts["rep_traffy"] == 1 and counts["rep_other"] == 1
    assert counts["fac_osm"] == 1 and counts["fac_ddpm"] == 1
    assert counts["cam_pakkret"] == 1 and counts["outline"] == 56
    assert ps.summary(None, "other", relay=True)["available"] is False
