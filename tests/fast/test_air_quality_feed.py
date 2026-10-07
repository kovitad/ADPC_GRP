"""Southeast Asia PM2.5 republished from SERVIR-SEA's public AQ Tracker feed (ADR-0061)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import api.air_quality as aq_api
from core.air_quality import AirQualityUnavailable, build_feed, category, fetch_latest
from core.contribution_rules import check_manifest
from core.feed_check import read_like_global_risk
from core.live_feeds import platform_feeds

SAMPLE = json.loads((Path(__file__).parents[1] / "fixtures" / "air_quality"
                     / "pm25_latest_sample.json").read_text(encoding="utf-8"))
NOW = datetime(2026, 10, 5, 5, 0, tzinfo=UTC)


def test_us_epa_2024_breakpoints() -> None:
    assert [category(v) for v in (9.0, 9.1, 35.4, 35.5, 55.5, 125.5, 225.5)] == [
        "good", "moderate", "moderate", "unhealthy_for_sensitive_groups", "unhealthy",
        "very_unhealthy", "hazardous"]
    assert category(None) is None


def test_every_record_carries_its_time_and_the_worst_come_last() -> None:
    feed = build_feed(SAMPLE, NOW)
    records = feed["records"]
    assert feed["count"] == len(SAMPLE["data"])
    assert all(r["forecast_time"] == "2026-10-05T04:30:00Z" for r in records)
    assert all(r["valid_until"] == "2026-10-05T07:30:00Z" for r in records)
    averages = [r["pm25_avg"] for r in records if r["pm25_avg"] is not None]
    assert averages == sorted(averages)
    assert records[-1]["province"] == "Nonthaburi" and records[-1]["category"] == "unhealthy"


def test_zero_means_no_data_and_comes_first() -> None:
    first = build_feed(SAMPLE, NOW)["records"][0]
    assert first["province"] == "Test no-data province"
    assert first["pm25_avg"] is None and first["category"] is None


@pytest.mark.parametrize("broken", [
    {**SAMPLE, "data": []},
    {**SAMPLE, "adm_lvl": "country"},
    {**SAMPLE, "forecast_time": None},
    {**SAMPLE, "data": [{"area_name": "x"}]},
])
def test_a_changed_shape_fails_closed(broken) -> None:
    with pytest.raises(AirQualityUnavailable):
        build_feed(broken, NOW)


def test_global_risk_returns_the_worst_provinces_by_default() -> None:
    feed = build_feed(SAMPLE, NOW)
    manifest = json.loads((Path(__file__).parents[2] / "core" / "data" / "live_feeds"
                           / "sea_pm25_province_forecast.json").read_text(encoding="utf-8"))
    fetch = manifest["fetch"]
    seen = read_like_global_risk(feed, fetch["records_path"], fetch["fields"],
                                 fetch["as_of_field"], limit=3)
    assert seen["sorted_by_time"]
    assert [r["province"] for r in seen["last"]][-1] == "Nonthaburi"


def test_a_source_error_is_reported(monkeypatch) -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda _r: httpx.Response(503)))
    with pytest.raises(AirQualityUnavailable, match="503"):
        fetch_latest(client)


def test_the_feed_is_listed_for_sharing_once_switched_on() -> None:
    feeds = {f["dataset"]: f for f in platform_feeds(
        "https://grp.example.org", {"flood_feed_public": False, "air_quality_feed_public": True})}
    air = feeds["sea_pm25_province_forecast"]
    assert air["available"]
    assert air["manifest"]["fetch"]["url"] == "https://grp.example.org/api/v1/public/aq/sea/feed.json"
    assert check_manifest("feed", air["manifest"]).problems == {}
    assert not feeds["bangkok_flood_districts_live"]["available"]


def test_the_public_route_is_closed_unless_switched_on(monkeypatch) -> None:
    from api.main import app

    calls = []
    monkeypatch.setattr(aq_api, "fetch_latest", lambda: calls.append(1) or SAMPLE)
    aq_api._cache.update(at=0.0, feed=None)
    client = TestClient(app)
    assert client.get("/api/v1/public/aq/sea/feed.json").status_code == 404
    assert calls == []

    settings = aq_api.get_settings().model_copy(update={"air_quality_feed_public": True})
    monkeypatch.setattr(aq_api, "get_settings", lambda: settings)
    first = client.get("/api/v1/public/aq/sea/feed.json")
    assert first.status_code == 200 and first.json()["records"][-1]["province"] == "Nonthaburi"
    again = client.get("/api/v1/public/aq/sea/feed.json",
                       headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304 and calls == [1]  # served from GRP's 10-minute copy
