"""River Watch pilot: read a GEOGLOWS river forecast as display-only evidence (ADR-0036).

Pure functions, no network. GEOGLOWS returns parallel arrays; this module checks them, turns them
into one record per time step and computes the summary that both the Pilot page and the feed
preview show, so the two can never disagree.

Three times are kept apart: the forecast run (when the model started, used for freshness), the
valid time of each value, and when GRP retrieved the bytes. ``metadata.gen_date`` is a retrieval
time, not the run, so it is never used.

A blank value is missing, never zero, and a missing median is never filled from ``high_res``.
Discharge is not water level, flood depth or a warning, and the reaches here are exploratory.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import cache
from pathlib import Path
from typing import Any

GEOGLOWS_API = "https://geoglows.ecmwf.int/api/v2"
SOURCE_PAGE = "https://geoglows.ecmwf.int/documentation"
WINDOW = timedelta(days=7)
# GEOGLOWS publishes each day's run by about 12:00 UTC; allow two hours before calling the newest
# run we hold "older".
PUBLISH_BY = timedelta(hours=14)
# Within 5% of the first value in the window counts as "about the same".
STEADY_RATIO = 0.05
UNITS = "m3/s"
RUN = re.compile(r"^\d{10}$")


@dataclass(frozen=True)
class Reach:
    reach_id: int
    label: str
    query_point: tuple[float, float]
    # A best guess for a non-specialist, with its reason key. Never a confirmed identity.
    likely_name_en: str | None = None
    likely_name_th: str | None = None
    likely_reason: str | None = None


# Exploratory candidates from the pilot plan. Neither is confirmed by a hydrologist. The owner asked
# on 2 October 2026 for plain names, so each carries a labelled best guess and the named waterways
# near its model line (ADR-0036 amendment). The browser can ask only for these.
REACHES: dict[int, Reach] = {
    430537201: Reach(
        430537201,
        "Big river near Nonthaburi: probably the Chao Phraya (not confirmed)",
        (13.840, 100.490),
        likely_name_en="Chao Phraya River",
        likely_name_th="แม่น้ำเจ้าพระยา",
        likely_reason="catchment_and_flow",
    ),
    430392813: Reach(
        430392813,
        "Small canal near Bang Bua Thong town (not confirmed)",
        (13.917, 100.425),
    ),
}
LARGE_RIVER_KM2 = 10_000
SMALL_WATERWAY_KM2 = 1_000
MAP_DATA = Path(__file__).resolve().parent / "data" / "river_watch_reaches.json"


@cache
def _map_data() -> dict[str, Any]:
    return json.loads(MAP_DATA.read_text(encoding="utf-8"))


def reach_map(reach_id: int) -> dict[str, Any] | None:
    """Where a reach is: the model's line, the named waterways it passes, and its size.

    The lines were captured once (see ``_source`` in the data file); nothing is fetched here.
    """

    data = _map_data()
    item = data["reaches"].get(str(reach_id))
    reach = REACHES.get(reach_id)
    if item is None or reach is None:
        return None
    area = item["upstream_area_km2"]
    size = (
        "large_river" if area >= LARGE_RIVER_KM2
        else "small_waterway" if area < SMALL_WATERWAY_KM2
        else "medium_river"
    )
    likely = None
    if reach.likely_name_en:
        likely = {
            "name_en": reach.likely_name_en,
            "name_th": reach.likely_name_th,
            "reason": reach.likely_reason,
            "confirmed": False,
        }
    return {
        "size": size,
        "stream_order": item["stream_order"],
        "upstream_area_km2": area,
        "length_km": item["length_km"],
        "line": item["line"],
        "waterways": item["waterways"],
        "likely": likely,
        "sources": data["_source"],
    }
SCOPE_NOTE = (
    "Exploratory GEOGLOWS reach found by a nearest-river lookup or chosen by rule for a district; "
    "not confirmed by a hydrologist as relevant to the chosen area. River flow only: not water "
    "level, flood depth, a flood map or a warning."
)

# ---------- Bangkok districts (captured once by grpcli.river_watch_capture) ----------

BANGKOK_DATA = Path(__file__).resolve().parent / "data" / "river_watch_bangkok.json"
# Inside Bangkok, a segment draining this much land is the Chao Phraya; nothing else comes close.
CHAO_PHRAYA_KM2 = 100_000


@cache
def _bangkok() -> dict[str, Any]:
    if not BANGKOK_DATA.exists():
        return {"districts": {}, "reaches": {}, "_source": {}}
    return json.loads(BANGKOK_DATA.read_text(encoding="utf-8"))


def size_class(upstream_area_km2: float) -> str:
    if upstream_area_km2 >= LARGE_RIVER_KM2:
        return "large_river"
    if upstream_area_km2 < SMALL_WATERWAY_KM2:
        return "small_waterway"
    return "medium_river"


def allowed_reach(reach_id: int) -> bool:
    """Only the pilot's own reaches and those inside a captured Bangkok district may be fetched."""

    return reach_id in REACHES or str(reach_id) in _bangkok()["reaches"]


def reach_point(reach_id: int) -> tuple[float, float] | None:
    """A (lat, lon) on the reach: the pilot's search point, or the middle of a Bangkok line."""

    if reach_id in REACHES:
        return REACHES[reach_id].query_point
    item = _bangkok()["reaches"].get(str(reach_id))
    if not item:
        return None
    lon, lat = item["line"][len(item["line"]) // 2]
    return (lat, lon)


def _bangkok_reach(reach_id: int) -> dict[str, Any]:
    item = _bangkok()["reaches"][str(reach_id)]
    area = item["upstream_area_km2"]
    likely = None
    if area >= CHAO_PHRAYA_KM2:
        likely = {
            "name_en": "Chao Phraya River",
            "name_th": "แม่น้ำเจ้าพระยา",
            "reason": "catchment_bangkok",
            "confirmed": False,
        }
    nearby = item.get("nearby")
    return {
        "reach_id": reach_id,
        "size": size_class(area),
        "stream_order": item["stream_order"],
        "upstream_area_km2": area,
        "length_km": item["length_km"],
        "line": item["line"],
        "waterways": [nearby] if nearby else [],
        "likely": likely,
    }


def bangkok_districts() -> list[dict[str, Any]]:
    data = _bangkok()
    out = []
    for code, district in data["districts"].items():
        main = district["main_reach"]
        area = data["reaches"][str(main)]["upstream_area_km2"] if main else 0
        out.append(
            {
                "admin_code": code,
                "name": district["name"],
                "name_th": district["name_th"],
                "main_reach": main,
                "reach_count": len(district["reaches"]),
                "inland": area < SMALL_WATERWAY_KM2,
            }
        )
    return out


def bangkok_district(admin_code: str) -> dict[str, Any] | None:
    data = _bangkok()
    district = data["districts"].get(admin_code)
    if district is None:
        return None
    reaches = [_bangkok_reach(rid) for rid in district["reaches"]]
    main = district["main_reach"]
    return {
        "admin_code": admin_code,
        "name": district["name"],
        "name_th": district["name_th"],
        "outline": district["outline"],
        "main_reach": main,
        "inland": not reaches or reaches[0]["upstream_area_km2"] < SMALL_WATERWAY_KM2,
        "reaches": reaches,
        "sources": data["_source"],
    }


class ForecastError(ValueError):
    """The upstream answer cannot be used. ``code`` is a short machine reason."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Step:
    valid_at: datetime
    median: float | None
    p25: float | None
    p75: float | None


@dataclass(frozen=True)
class Forecast:
    reach_id: int
    run: str
    issued_at: datetime
    steps: tuple[Step, ...]


def parse_runs(text: str) -> list[str]:
    """The run identifiers in the ``/dates`` answer, newest first.

    The documentation says JSON, but the route answers CSV with a ``dates`` header.
    """

    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    if not lines or lines[0].lower() != "dates":
        raise ForecastError("bad_dates", "The GEOGLOWS run list is not in the expected form.")
    runs = lines[1:]
    if not runs or any(not RUN.match(run) for run in runs):
        raise ForecastError("bad_dates", "The GEOGLOWS run list has no usable run.")
    for run in runs:
        run_issued_at(run)
    return sorted(set(runs), reverse=True)


def run_issued_at(run: str) -> datetime:
    """``2026100100`` -> 1 October 2026, 00:00 UTC."""

    if not RUN.match(run):
        raise ForecastError("bad_run", f"Unrecognised forecast run {run!r}.")
    try:
        return datetime.strptime(run, "%Y%m%d%H").replace(tzinfo=UTC)
    except ValueError as exc:
        raise ForecastError("bad_run", f"Unrecognised forecast run {run!r}.") from exc


def run_query_date(run: str) -> str:
    """The ``date=`` value GEOGLOWS accepted on 2 October 2026 (``20261001``)."""

    return run_issued_at(run).strftime("%Y%m%d")


def forecast_url(reach_id: int, run: str) -> str:
    return f"{GEOGLOWS_API}/forecaststats/{reach_id}?format=json&date={run_query_date(run)}"


def dates_url() -> str:
    return f"{GEOGLOWS_API}/dates"


def _number(value: Any, field: str, index: int) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ForecastError("bad_value", f"{field}[{index}] is not a number.")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ForecastError("bad_value", f"{field}[{index}] is not a number.") from exc
    if not math.isfinite(number) or number < 0:
        raise ForecastError("bad_value", f"{field}[{index}] is not a usable river flow.")
    return number


def _utc(value: Any, index: int) -> datetime:
    if not isinstance(value, str):
        raise ForecastError("bad_time", f"datetime[{index}] is not a timestamp.")
    try:
        moment = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ForecastError("bad_time", f"datetime[{index}] is not a timestamp.") from exc
    if moment.tzinfo is None or moment.utcoffset() != timedelta(0):
        raise ForecastError("bad_time", f"datetime[{index}] is not in UTC.")
    return moment.astimezone(UTC)


def parse_forecast(payload: Any, reach_id: int, run: str) -> Forecast:
    """Check a ``forecaststats`` answer and turn its arrays into one step per valid time."""

    if not isinstance(payload, dict) or not payload:
        raise ForecastError("empty", "GEOGLOWS returned no forecast.")
    if "error" in payload:
        raise ForecastError("upstream_error", "GEOGLOWS answered with an error instead of data.")
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        raise ForecastError("bad_shape", "The forecast has no metadata.")
    if metadata.get("river_id") != reach_id:
        raise ForecastError("wrong_reach", "The forecast is for a different river reach.")
    units = metadata.get("units")
    if not isinstance(units, dict) or units.get("short") != "cms":
        raise ForecastError(
            "bad_units", "The forecast does not say it is in cubic metres per second."
        )

    fields = ("datetime", "flow_med", "flow_25p", "flow_75p")
    arrays = [payload.get(name) for name in fields]
    if any(not isinstance(array, list) for array in arrays):
        raise ForecastError("bad_shape", "The forecast is missing a series.")
    length = len(arrays[0])
    if length == 0:
        raise ForecastError("empty", "GEOGLOWS returned no forecast values.")
    others = [payload.get(name) for name in ("flow_avg", "flow_min", "flow_max", "high_res")]
    if any(len(array) != length for array in arrays) or any(
        isinstance(array, list) and len(array) != length for array in others
    ):
        raise ForecastError("misaligned", "The forecast series have different lengths.")

    steps: list[Step] = []
    previous: datetime | None = None
    for index in range(length):
        valid_at = _utc(arrays[0][index], index)
        if previous is not None and valid_at <= previous:
            raise ForecastError("bad_time", "The forecast times do not keep increasing.")
        previous = valid_at
        median = _number(arrays[1][index], "flow_med", index)
        p25 = _number(arrays[2][index], "flow_25p", index)
        p75 = _number(arrays[3][index], "flow_75p", index)
        if None not in (median, p25, p75) and not (p25 <= median <= p75):  # type: ignore[operator]
            raise ForecastError("bad_order", f"The forecast range is out of order at step {index}.")
        steps.append(Step(valid_at, median, p25, p75))

    return Forecast(reach_id=reach_id, run=run, issued_at=run_issued_at(run), steps=tuple(steps))


def expected_newest_run(now: datetime) -> datetime:
    """The newest run that should be published by ``now``."""

    today = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return today if now - today >= PUBLISH_BY else today - timedelta(days=1)


def freshness(issued_at: datetime, now: datetime) -> str:
    return "latest" if issued_at >= expected_newest_run(now) else "older"


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _trend(first: float, last: float, peak: float) -> str:
    if peak > first * (1 + STEADY_RATIO):
        return "rise"
    if last < first * (1 - STEADY_RATIO):
        return "fall"
    return "steady"


def summarise(
    forecast: Forecast,
    *,
    decision_time: datetime,
    retrieved_at: datetime,
    source_url: str,
) -> dict[str, Any]:
    """The card and feed summary for ``[decision_time, decision_time + 7 days)``.

    The peak is the highest value of the median series in the window; on a tie, the earliest.
    P25 and P75 are read at that same time. This is not a probability of flooding.
    """

    start = decision_time.astimezone(UTC)
    end = start + WINDOW
    in_window = [step for step in forecast.steps if start <= step.valid_at < end]
    series = [step for step in in_window if step.median is not None]
    if not series:
        raise ForecastError("no_window", "The forecast has no values for the next seven days.")

    peak = series[0]
    for step in series[1:]:
        if step.median > peak.median:  # type: ignore[operator]
            peak = step
    first = series[0].median
    last = series[-1].median
    assert first is not None and last is not None and peak.median is not None

    summary = {
        "reach_id": forecast.reach_id,
        "run": forecast.run,
        "issued_at_utc": _iso(forecast.issued_at),
        "retrieved_at_utc": _iso(retrieved_at),
        "decision_time_utc": _iso(start),
        "window_start_utc": _iso(start),
        "window_end_utc": _iso(end),
        "units": UNITS,
        "trend": _trend(first, last, peak.median),
        "first_median_m3s": first,
        "last_median_m3s": last,
        "median_peak_m3s": peak.median,
        "median_peak_valid_at_utc": _iso(peak.valid_at),
        "p25_at_peak_m3s": peak.p25,
        "p75_at_peak_m3s": peak.p75,
        "steps_in_window": len(in_window),
        "median_steps_in_window": len(series),
        "quality_state": freshness(forecast.issued_at, start),
        "scope_note": SCOPE_NOTE,
        "source_url": source_url,
    }
    return summary


def series_records(forecast: Forecast, decision_time: datetime) -> list[dict[str, Any]]:
    """One record per valid time in the window that has a median value."""

    start = decision_time.astimezone(UTC)
    end = start + WINDOW
    return [
        {
            "valid_at_utc": _iso(step.valid_at),
            "median_m3s": step.median,
            "p25_m3s": step.p25,
            "p75_m3s": step.p75,
        }
        for step in forecast.steps
        if start <= step.valid_at < end and step.median is not None
    ]


def feed_preview(summary: dict[str, Any], series: list[dict[str, Any]]) -> dict[str, Any]:
    """The records a Global Risk ``generic_json`` feed would read. A local preview only."""

    return {
        "records": [summary],
        "as_of_field": "issued_at_utc",
        "series_records": series,
        "sent_to_global_risk": False,
    }
