"""Contributing a live feed from Share data (ADR-0052)."""

from __future__ import annotations

import json

import httpx
import pytest

import core.feed_check as fc
from core.contribution_rules import check_manifest
from core.live_feeds import platform_feeds

FLAT = {
    "dataset": "sea_pm25_province", "title": "PM2.5 by province", "description": "Forecast.",
    "source": "SERVIR-SEA", "validation": "unvalidated", "cadence": "every 3 hours",
    "url": "https://feeds.example.org/pm25.json", "records_path": "provinces",
    "fields": '{"province": "name", "pm25": "values.0", "as_of": "time"}',
    "as_of_field": "as_of", "hazards": "air_quality, pm25", "usage_notes": "Indicative only.",
}


def test_a_feed_is_checked_flat_and_sent_nested() -> None:
    checked = check_manifest("feed", dict(FLAT))
    assert checked.problems == {}
    manifest = checked.manifest
    assert manifest["adapter"] == "generic_json" and manifest["pack"] == "risk"
    assert manifest["fetch"] == {"url": FLAT["url"], "records_path": "provinces",
                                 "as_of_field": "as_of",
                                 "fields": {"province": "name", "pm25": "values.0",
                                            "as_of": "time"}}
    assert manifest["hazards"] == ["air_quality", "pm25"]
    assert "url" not in manifest and "records_path" not in manifest
    # The checked manifest comes back on send, nested; it must pass unchanged.
    again = check_manifest("feed", manifest)
    assert again.problems == {} and again.manifest == manifest


@pytest.mark.parametrize(("url", "words"), [
    ("https://areas-barry-beyond-res.trycloudflare.com/feed.json", "temporary"),
    ("http://127.0.0.1:8000/feed.json", "private"),
    ("http://localhost/feed.json", "this computer"),
    ("https://user:secret@feeds.example.org/x.json", "password"),
    ("ftp://feeds.example.org/x.json", "http or https"),
])
def test_a_feed_url_global_risk_cannot_keep_is_refused(url, words) -> None:
    problems = check_manifest("feed", {**FLAT, "url": url}).problems
    assert words in problems["url"]


def test_the_date_field_must_be_a_mapped_output_field() -> None:
    problems = check_manifest("feed", {**FLAT, "as_of_field": "time"}).problems
    assert "output field" in problems["as_of_field"]


def test_global_risk_reading_sorts_on_the_mapped_date() -> None:
    document = {"provinces": [
        {"name": "B", "values": [40.0], "time": "2026-10-05T04:30Z"},
        {"name": "A", "values": [12.5], "time": "2026-10-05T01:30Z"},
    ]}
    result = fc.read_like_global_risk(document, "provinces",
                                      {"province": "name", "pm25": "values.0", "as_of": "time"},
                                      "as_of")
    assert result["sorted_by_time"] and result["last"][-1] == {
        "province": "B", "pm25": 40.0, "as_of": "2026-10-05T04:30Z"}
    unsorted = fc.read_like_global_risk(document, "provinces", {"province": "name"}, "as_of")
    assert not unsorted["sorted_by_time"] and "not guaranteed" in unsorted["order"]


def test_an_empty_list_fails_like_on_global_risk() -> None:
    with pytest.raises(fc.FeedCheckError, match="empty or missing"):
        fc.read_like_global_risk({"provinces": []}, "provinces", {"p": "name"})


def test_the_check_fetches_through_the_pinned_public_address(monkeypatch) -> None:
    seen = {}

    def answer(request: httpx.Request) -> httpx.Response:
        seen["host_header"] = request.headers["host"]
        seen["url"] = str(request.url)
        return httpx.Response(200, content=json.dumps(
            {"provinces": [{"name": "A", "time": "t1"}]}).encode())

    monkeypatch.setattr(fc, "_public_address", lambda host: "93.184.216.34")
    client = httpx.Client(transport=httpx.MockTransport(answer))
    result = fc.check_feed("http://feeds.example.org/pm25.json", "provinces",
                           {"province": "name", "as_of": "time"}, "as_of", client=client)
    assert result["ok"] and result["count"] == 1
    assert seen["url"].startswith("http://93.184.216.34/")
    assert seen["host_header"] == "feeds.example.org"


def test_a_name_that_resolves_privately_is_refused(monkeypatch) -> None:
    monkeypatch.setattr(fc.socket, "getaddrinfo",
                        lambda *_a, **_k: [(None, None, None, None, ("10.0.0.5", 0))])
    result = fc.check_feed("https://feeds.example.org/x.json", "a", {"b": "c"})
    assert not result["ok"] and "private" in result["problem"]


def test_platform_feeds_wait_for_a_permanent_public_address() -> None:
    none = platform_feeds(None, {"flood_feed_public": True})
    assert not any(f["available"] for f in none)
    assert "permanent public address" in none[0]["reason"]
    assert none[0]["manifest"]["fetch"]["url"] is None

    off = platform_feeds("https://grp.example.org", {"flood_feed_public": False})
    assert "switched off" in off[0]["reason"]

    ready = platform_feeds("https://grp.example.org/", {"flood_feed_public": True})
    assert ready[0]["available"]
    assert ready[0]["manifest"]["fetch"]["url"] == (
        "https://grp.example.org/api/v1/public/flood/bangkok/feed.json")
    assert check_manifest("feed", ready[0]["manifest"]).problems == {}

    tunnel = platform_feeds("https://x.trycloudflare.com", {"flood_feed_public": True})
    assert not tunnel[0]["available"] and "temporary" in tunnel[0]["reason"]
