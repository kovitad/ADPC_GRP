"""River Watch pilot rules (ADR-0036): honest parsing, one summary, older is never new."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

import api.river_watch as river_watch
from api.main import app
from api.permissions import admin_user
from core.river_watch import (
    ForecastError,
    expected_newest_run,
    feed_preview,
    forecast_url,
    freshness,
    parse_forecast,
    parse_runs,
    run_issued_at,
    series_records,
    summarise,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "geoglows"
REACH = 430537201
RUN = "2026100100"
DECISION = datetime(2026, 10, 2, 4, 0, tzinfo=UTC)


@pytest.fixture
def payload() -> dict:
    return json.loads((FIXTURES / "forecaststats_430537201_20261001.json").read_text("utf-8"))


def _small(**overrides) -> dict:
    """A tiny forecast: three-hourly medians with blank hourly steps between them."""

    base = {
        "datetime": [
            "2026-10-02T00:00:00+00:00",
            "2026-10-02T01:00:00+00:00",
            "2026-10-02T03:00:00+00:00",
            "2026-10-02T06:00:00+00:00",
            "2026-10-02T09:00:00+00:00",
        ],
        "flow_med": [100.0, "", 120.0, 130.0, 110.0],
        "flow_25p": [90.0, "", 110.0, 120.0, 100.0],
        "flow_75p": [110.0, "", 130.0, 140.0, 120.0],
        "high_res": [101.0, 999.0, 121.0, 131.0, 111.0],
        "metadata": {"river_id": REACH, "units": {"short": "cms"}},
    }
    base.update(overrides)
    return base


# ---------- parsing ----------


@pytest.mark.fast
def test_the_run_list_is_csv_newest_first() -> None:
    runs = parse_runs((FIXTURES / "dates_head.csv").read_text("utf-8"))
    assert runs[0] == "2026100100"
    assert runs == sorted(runs, reverse=True)
    assert run_issued_at("2026100100") == datetime(2026, 10, 1, tzinfo=UTC)


@pytest.mark.fast
@pytest.mark.parametrize("text", ["", "dates\n", "date\n2026100100", "dates\n20261001"])
def test_an_unusable_run_list_is_refused(text: str) -> None:
    with pytest.raises(ForecastError):
        parse_runs(text)


@pytest.mark.fast
def test_the_request_pins_the_run_by_date() -> None:
    assert forecast_url(REACH, RUN).endswith("/forecaststats/430537201?format=json&date=20261001")


@pytest.mark.fast
def test_blank_values_stay_missing_and_are_not_filled_from_high_res() -> None:
    forecast = parse_forecast(_small(), REACH, RUN)
    assert forecast.steps[1].median is None
    assert [r["median_m3s"] for r in series_records(forecast, forecast.steps[0].valid_at)] == [
        100.0, 120.0, 130.0, 110.0,
    ]


@pytest.mark.fast
def test_the_real_snapshot_parses_with_mixed_time_steps(payload: dict) -> None:
    forecast = parse_forecast(payload, REACH, RUN)
    gaps = {
        (b.valid_at - a.valid_at) for a, b in zip(forecast.steps, forecast.steps[1:], strict=False)
    }
    assert gaps == {timedelta(hours=1), timedelta(hours=3)}
    assert forecast.issued_at == datetime(2026, 10, 1, tzinfo=UTC)


@pytest.mark.fast
@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"metadata": {"river_id": 1, "units": {"short": "cms"}}}, "wrong_reach"),
        ({"metadata": {"river_id": REACH, "units": {}}}, "bad_units"),
        ({"flow_med": [100.0, "", 120.0, 130.0]}, "misaligned"),
        ({"high_res": [1.0]}, "misaligned"),
        ({"flow_med": [100.0, "", -1.0, 130.0, 110.0]}, "bad_value"),
        ({"flow_med": [100.0, "", "NaN", 130.0, 110.0]}, "bad_value"),
        ({"flow_med": [100.0, "", "high", 130.0, 110.0]}, "bad_value"),
        ({"flow_med": [100.0, "", 200.0, 130.0, 110.0]}, "bad_order"),
        (
            {"datetime": ["2026-10-02T00:00:00+00:00"] * 5},
            "bad_time",
        ),
        (
            {
                "datetime": [
                    "2026-10-02T00:00:00",
                    "2026-10-02T01:00:00",
                    "2026-10-02T03:00:00",
                    "2026-10-02T06:00:00",
                    "2026-10-02T09:00:00",
                ]
            },
            "bad_time",
        ),
    ],
)
def test_a_changed_or_broken_forecast_is_refused(change: dict, code: str) -> None:
    with pytest.raises(ForecastError) as caught:
        parse_forecast(_small(**change), REACH, RUN)
    assert caught.value.code == code


@pytest.mark.fast
@pytest.mark.parametrize(
    ("body", "code"),
    [({}, "empty"), ({"error": "An unexpected error occurred"}, "upstream_error"), ([], "empty")],
)
def test_an_empty_or_error_answer_is_unavailable(body, code: str) -> None:
    with pytest.raises(ForecastError) as caught:
        parse_forecast(body, REACH, RUN)
    assert caught.value.code == code


# ---------- the summary ----------


@pytest.mark.fast
def test_the_summary_matches_an_independent_recalculation(payload: dict) -> None:
    forecast = parse_forecast(payload, REACH, RUN)
    summary = summarise(
        forecast, decision_time=DECISION, retrieved_at=DECISION, source_url="u"
    )

    end = DECISION + timedelta(days=7)
    best = None
    for when, med, p25, p75 in zip(
        payload["datetime"], payload["flow_med"], payload["flow_25p"], payload["flow_75p"],
        strict=True,
    ):
        moment = datetime.fromisoformat(when)
        if med == "" or not (DECISION <= moment < end):
            continue
        if best is None or float(med) > best[1]:
            best = (moment, float(med), float(p25), float(p75))

    assert best is not None
    assert summary["median_peak_m3s"] == best[1]
    assert summary["median_peak_valid_at_utc"] == best[0].isoformat().replace("+00:00", "Z")
    assert (summary["p25_at_peak_m3s"], summary["p75_at_peak_m3s"]) == (best[2], best[3])
    assert summary["window_end_utc"] == "2026-10-09T04:00:00Z"
    assert summary["issued_at_utc"] == "2026-10-01T00:00:00Z"


@pytest.mark.fast
def test_a_tied_peak_takes_the_earliest_time() -> None:
    forecast = parse_forecast(
        _small(
            flow_med=[100.0, "", 130.0, 130.0, 110.0],
            flow_25p=[90.0, "", 120.0, 125.0, 100.0],
            flow_75p=[110.0, "", 140.0, 135.0, 120.0],
        ),
        REACH,
        RUN,
    )
    summary = summarise(
        forecast,
        decision_time=datetime(2026, 10, 2, tzinfo=UTC),
        retrieved_at=DECISION,
        source_url="u",
    )
    assert summary["median_peak_valid_at_utc"] == "2026-10-02T03:00:00Z"
    assert summary["p75_at_peak_m3s"] == 140.0


@pytest.mark.fast
def test_the_window_includes_its_start_and_excludes_its_end() -> None:
    forecast = parse_forecast(_small(), REACH, RUN)
    start = datetime(2026, 10, 2, 3, tzinfo=UTC)
    records = series_records(forecast, start)
    assert records[0]["valid_at_utc"] == "2026-10-02T03:00:00Z"
    assert all(r["valid_at_utc"] != "2026-10-02T00:00:00Z" for r in records)


@pytest.mark.fast
@pytest.mark.parametrize(
    ("medians", "trend"),
    [
        ([100.0, "", 120.0, 130.0, 110.0], "rise"),
        ([100.0, "", 102.0, 101.0, 99.0], "steady"),
        ([100.0, "", 95.0, 90.0, 80.0], "fall"),
    ],
)
def test_the_trend_reads_as_a_plain_word(medians: list, trend: str) -> None:
    forecast = parse_forecast(
        _small(flow_med=medians, flow_25p=[""] * 5, flow_75p=[""] * 5), REACH, RUN
    )
    summary = summarise(
        forecast,
        decision_time=datetime(2026, 10, 2, tzinfo=UTC),
        retrieved_at=DECISION,
        source_url="u",
    )
    assert summary["trend"] == trend


@pytest.mark.fast
def test_no_values_in_the_window_is_unavailable_not_zero() -> None:
    forecast = parse_forecast(_small(), REACH, RUN)
    with pytest.raises(ForecastError) as caught:
        summarise(
            forecast,
            decision_time=datetime(2026, 11, 1, tzinfo=UTC),
            retrieved_at=DECISION,
            source_url="u",
        )
    assert caught.value.code == "no_window"


@pytest.mark.fast
def test_bangkok_time_is_seven_hours_ahead_of_the_utc_peak(payload: dict) -> None:
    forecast = parse_forecast(payload, REACH, RUN)
    summary = summarise(forecast, decision_time=DECISION, retrieved_at=DECISION, source_url="u")
    utc = datetime.fromisoformat(summary["median_peak_valid_at_utc"].replace("Z", "+00:00"))
    assert utc.astimezone(ZoneInfo("Asia/Bangkok")).utcoffset() == timedelta(hours=7)


# ---------- freshness ----------


@pytest.mark.fast
def test_a_morning_query_does_not_call_yesterdays_run_older() -> None:
    morning = datetime(2026, 10, 2, 4, tzinfo=UTC)
    assert expected_newest_run(morning) == datetime(2026, 10, 1, tzinfo=UTC)
    assert freshness(datetime(2026, 10, 1, tzinfo=UTC), morning) == "latest"


@pytest.mark.fast
def test_an_old_run_never_looks_new_even_with_future_valid_times(payload: dict) -> None:
    forecast = parse_forecast(payload, REACH, RUN)
    two_days_later = datetime(2026, 10, 3, 16, tzinfo=UTC)
    summary = summarise(
        forecast, decision_time=two_days_later, retrieved_at=two_days_later, source_url="u"
    )
    assert summary["quality_state"] == "older"
    assert summary["issued_at_utc"] == "2026-10-01T00:00:00Z"


@pytest.mark.fast
def test_the_feed_preview_carries_the_card_summary_and_is_not_sent(payload: dict) -> None:
    forecast = parse_forecast(payload, REACH, RUN)
    summary = summarise(forecast, decision_time=DECISION, retrieved_at=DECISION, source_url="u")
    series = series_records(forecast, DECISION)
    preview = feed_preview(summary, series)
    assert preview["records"] == [summary]
    assert preview["as_of_field"] == "issued_at_utc"
    assert preview["sent_to_global_risk"] is False


# ---------- the API ----------


@pytest.fixture
def api(monkeypatch, payload: dict):
    river_watch.reset_cache()
    calls: list[str] = []
    state = {"fail": False, "body": payload}

    async def fake_fetch(url: str) -> bytes:
        calls.append(url)
        if state["fail"]:
            raise ForecastError("unreachable", "GEOGLOWS could not be reached.")
        if url.endswith("/dates"):
            return (FIXTURES / "dates_head.csv").read_bytes()
        return json.dumps(state["body"]).encode()

    clock = {"now": DECISION}
    monkeypatch.setattr(river_watch, "fetch", fake_fetch)
    monkeypatch.setattr(river_watch, "now", lambda: clock["now"])
    app.dependency_overrides[admin_user] = lambda: object()
    try:
        yield TestClient(app), calls, state, clock
    finally:
        app.dependency_overrides.pop(admin_user, None)
        river_watch.reset_cache()


@pytest.mark.fast
def test_the_card_and_feed_share_one_summary_and_fetch_once(api) -> None:
    client, calls, _, _ = api
    card = client.get(f"/api/v1/pilot/river-watch/{REACH}").json()
    feed = client.get(f"/api/v1/pilot/river-watch/{REACH}/feed-preview").json()

    assert card["available"] is True
    assert card["reach"]["confirmed"] is False
    assert card["summary"]["quality_state"] == "latest"
    assert feed["records"] == [card["summary"]]
    assert feed["sent_to_global_risk"] is False
    assert [url.rsplit("/", 1)[-1] for url in calls] == [
        "dates", "430537201?format=json&date=20261001",
    ]


@pytest.mark.fast
def test_an_unknown_reach_is_not_found_without_fetching(api) -> None:
    client, calls, _, _ = api
    assert client.get("/api/v1/pilot/river-watch/12345").status_code == 404
    assert calls == []


@pytest.mark.fast
def test_when_geoglows_fails_the_last_forecast_is_shown_as_older(api) -> None:
    client, _, state, clock = api
    assert client.get(f"/api/v1/pilot/river-watch/{REACH}").json()["available"] is True

    state["fail"] = True
    clock["now"] = DECISION + timedelta(hours=1)
    river_watch._runs = None  # force a run-list re-check
    card = client.get(f"/api/v1/pilot/river-watch/{REACH}").json()

    assert card["available"] is True
    assert card["summary"]["quality_state"] == "older"
    assert "could not be reached" in card["problem"]


@pytest.mark.fast
def test_when_geoglows_fails_with_nothing_held_the_card_is_unavailable(api) -> None:
    client, _, state, _ = api
    state["fail"] = True
    card = client.get(f"/api/v1/pilot/river-watch/{REACH}").json()
    assert card["available"] is False
    assert card["summary"] is None
    assert card["series"] == []


@pytest.mark.fast
def test_a_broken_upstream_answer_is_unavailable_not_zero(api, payload: dict) -> None:
    client, _, state, _ = api
    broken = copy.deepcopy(payload)
    broken["metadata"]["river_id"] = 1
    state["body"] = broken
    card = client.get(f"/api/v1/pilot/river-watch/{REACH}").json()
    assert card["available"] is False
    assert "different river reach" in card["problem"]


@pytest.mark.fast
def test_the_page_preview_matches_its_card_even_when_time_moves_on(api) -> None:
    client, _, _, clock = api
    card = client.get(f"/api/v1/pilot/river-watch/{REACH}").json()
    clock["now"] = DECISION + timedelta(hours=6)
    later = client.get(f"/api/v1/pilot/river-watch/{REACH}/feed-preview").json()

    assert card["feed_preview"]["records"] == [card["summary"]]
    assert card["feed_preview"]["series_records"] == card["series"]
    # A later request is a later window; the page shows the card's own preview instead.
    assert later["records"][0]["window_start_utc"] != card["summary"]["window_start_utc"]


@pytest.mark.fast
def test_the_exact_upstream_bytes_can_be_downloaded_and_match_the_hash(api) -> None:
    import hashlib

    client, _, _, _ = api
    card = client.get(f"/api/v1/pilot/river-watch/{REACH}").json()
    raw = client.get(f"/api/v1/pilot/river-watch/{REACH}/raw/{RUN}")

    assert raw.status_code == 200
    assert hashlib.sha256(raw.content).hexdigest() == card["evidence"]["raw_sha256"]
    assert client.get(f"/api/v1/pilot/river-watch/{REACH}/raw/2026090100").status_code == 404


@pytest.mark.fast
def test_after_a_restart_a_missing_newest_run_falls_back_to_the_previous_one(
    api, monkeypatch, payload: dict
) -> None:
    client, calls, _, _ = api
    real = river_watch.fetch

    async def newest_missing(url: str) -> bytes:
        if url.endswith("date=20261001"):
            calls.append(url)
            raise ForecastError("upstream_status", "GEOGLOWS answered 404.")
        return await real(url)

    monkeypatch.setattr(river_watch, "fetch", newest_missing)
    card = client.get(f"/api/v1/pilot/river-watch/{REACH}").json()

    assert card["available"] is True
    assert card["summary"]["run"] == "2026093000"
    assert card["summary"]["quality_state"] == "older"


@pytest.mark.fast
def test_every_reach_has_a_map_with_its_line_names_and_an_unconfirmed_guess() -> None:
    from core.river_watch import REACHES, reach_map

    for reach_id in REACHES:
        info = reach_map(reach_id)
        assert info is not None
        assert len(info["line"]) >= 2
        # Bang Bua Thong / Nonthaburi, roughly.
        assert all(100.3 < lon < 100.6 and 13.7 < lat < 14.1 for lon, lat in info["line"])
        assert info["waterways"] and all(w["name_th"] and w["name_en"] for w in info["waterways"])
        assert "OpenStreetMap" in info["sources"]["waterways"]
        if info["likely"]:
            assert info["likely"]["confirmed"] is False
    assert reach_map(430537201)["size"] == "large_river"
    assert reach_map(430392813)["size"] == "small_waterway"
    assert reach_map(1) is None


@pytest.mark.fast
def test_the_reaches_route_carries_each_map(api) -> None:
    client, calls, _, _ = api
    reaches = client.get("/api/v1/pilot/river-watch/reaches").json()["reaches"]
    assert {r["reach_id"] for r in reaches} == {430537201, 430392813}
    assert all(r["map"]["line"] for r in reaches)
    assert calls == []  # the map is stored data; nothing is fetched


@pytest.mark.fast
def test_every_bangkok_district_is_listed_and_riverside_ones_get_the_chao_phraya() -> None:
    from core.river_watch import CHAO_PHRAYA_KM2, bangkok_district, bangkok_districts

    districts = bangkok_districts()
    assert len(districts) == 50
    riverside = [d for d in districts if not d["inland"]]
    assert riverside, "some Bangkok districts lie on the Chao Phraya"
    for summary in districts:
        detail = bangkok_district(summary["admin_code"])
        assert detail["outline"]["type"] in {"Polygon", "MultiPolygon"}
        if not detail["reaches"]:
            assert summary["main_reach"] is None and summary["inland"]
            continue
        # The main river drains the most land of the district's segments.
        areas = [r["upstream_area_km2"] for r in detail["reaches"]]
        assert detail["reaches"][0]["reach_id"] == summary["main_reach"]
        assert areas[0] == max(areas)
        for reach in detail["reaches"]:
            assert len(reach["line"]) >= 2
            if reach["likely"]:
                assert reach["upstream_area_km2"] >= CHAO_PHRAYA_KM2
                assert reach["likely"]["confirmed"] is False
    assert bangkok_district("no-such") is None


@pytest.mark.fast
def test_a_bangkok_river_can_be_forecast_and_an_unknown_one_cannot(api, payload: dict) -> None:
    from core.river_watch import bangkok_districts

    client, calls, state, _ = api
    main = next(d["main_reach"] for d in bangkok_districts() if not d["inland"])
    body = dict(payload)
    body["metadata"] = {**payload["metadata"], "river_id": main}
    state["body"] = body
    card = client.get(f"/api/v1/pilot/river-watch/{main}").json()
    assert card["available"] is True
    assert card["reach"]["reach_id"] == main
    assert card["reach"]["confirmed"] is False
    assert client.get("/api/v1/pilot/river-watch/999999999").status_code == 404

    listed = client.get("/api/v1/pilot/river-watch/districts").json()["districts"]
    assert len(listed) == 50
    code = listed[0]["admin_code"]
    assert client.get(f"/api/v1/pilot/river-watch/districts/{code}").status_code == 200
