"""Pilot River Watch: a live GEOGLOWS river forecast for Admins (ADR-0036).

Display-only evidence. GRP fetches the public GEOGLOWS forecast for one allow-listed, exploratory
reach, checks it with ``core.river_watch`` and shows the summary. Nothing is sent to Global Risk:
the feed preview shows the records a feed would serve, and registering one is a separate decision.

GEOGLOWS is read at most once per reach and run, plus a run-list check every 30 minutes. When it
cannot be reached, the last good forecast is shown as older, never as new, and never as zero flow.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from fastapi import APIRouter
from fastapi.responses import Response

from api.errors import not_found
from api.permissions import AdminUser
from core.river_watch import (
    REACHES,
    SOURCE_PAGE,
    Forecast,
    ForecastError,
    allowed_reach,
    bangkok_district,
    bangkok_districts,
    dates_url,
    feed_preview,
    forecast_url,
    parse_forecast,
    parse_runs,
    reach_map,
    reach_point,
    series_records,
    summarise,
)

logger = logging.getLogger("grp.river_watch")
router = APIRouter(prefix="/pilot/river-watch", tags=["pilot"])

FETCH_TIMEOUT_SECONDS = 30.0
RUNS_RECHECK = timedelta(minutes=30)
MAX_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True)
class Fetched:
    forecast: Forecast
    url: str
    raw: bytes
    sha256: str
    retrieved_at: datetime
    seconds: float


_runs: tuple[datetime, list[str]] | None = None
_forecasts: dict[tuple[int, str], Fetched] = {}
_lock = asyncio.Lock()


def now() -> datetime:
    return datetime.now(UTC)


async def fetch(url: str) -> bytes:
    """GET one GEOGLOWS URL, with one retry on a network failure or a 5xx answer."""

    last: Exception | None = None
    async with httpx.AsyncClient(timeout=FETCH_TIMEOUT_SECONDS, follow_redirects=False) as client:
        for _ in range(2):
            try:
                response = await client.get(url)
            except httpx.HTTPError as exc:
                last = exc
                continue
            if response.status_code >= 500:
                last = ForecastError(
                    "upstream_status", f"GEOGLOWS answered {response.status_code}."
                )
                continue
            if response.status_code != 200:
                raise ForecastError("upstream_status", f"GEOGLOWS answered {response.status_code}.")
            if len(response.content) > MAX_BYTES:
                raise ForecastError("too_large", "The GEOGLOWS answer is larger than expected.")
            return response.content
    raise ForecastError("unreachable", "GEOGLOWS could not be reached.") from last


def reset_cache() -> None:
    global _runs
    _runs = None
    _forecasts.clear()


async def _newest_runs(moment: datetime) -> list[str]:
    global _runs
    if _runs and moment - _runs[0] < RUNS_RECHECK:
        return _runs[1]
    runs = parse_runs((await fetch(dates_url())).decode("utf-8", errors="replace"))
    _runs = (moment, runs)
    return runs


async def _forecast(reach_id: int, run: str) -> Fetched:
    cached = _forecasts.get((reach_id, run))
    if cached:
        return cached
    url = forecast_url(reach_id, run)
    started = time.perf_counter()
    raw = await fetch(url)
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise ForecastError("not_json", "The GEOGLOWS answer is not JSON.") from exc
    fetched = Fetched(
        forecast=parse_forecast(payload, reach_id, run),
        url=url,
        raw=raw,
        sha256=hashlib.sha256(raw).hexdigest(),
        retrieved_at=now(),
        seconds=round(time.perf_counter() - started, 2),
    )
    _forecasts[(reach_id, run)] = fetched
    logger.info(
        "river_watch fetched reach=%s run=%s sha256=%s seconds=%s",
        reach_id, run, fetched.sha256[:12], fetched.seconds,
    )
    return fetched


def _newest_cached(reach_id: int) -> Fetched | None:
    held = [item for (reach, _), item in _forecasts.items() if reach == reach_id]
    return max(held, key=lambda item: item.forecast.run, default=None)


async def _current(reach_id: int) -> tuple[Fetched | None, str | None]:
    """The newest usable forecast for a reach, and why a newer one could not be read."""

    async with _lock:
        try:
            runs = await _newest_runs(now())
        except ForecastError as exc:
            logger.warning("river_watch unavailable reach=%s code=%s", reach_id, exc.code)
            return _newest_cached(reach_id), str(exc)
        try:
            return await _forecast(reach_id, runs[0]), None
        except ForecastError as exc:
            logger.warning("river_watch newest run failed reach=%s code=%s", reach_id, exc.code)
            problem = str(exc)
        held = _newest_cached(reach_id)
        if held is None and len(runs) > 1:
            # Right after a restart nothing is held: the previous listed run is better than none.
            try:
                held = await _forecast(reach_id, runs[1])
            except ForecastError:
                held = None
        return held, problem


def _reach(reach_id: int) -> None:
    if not allowed_reach(reach_id):
        raise not_found()


def _view(reach_id: int, fetched: Fetched | None, problem: str | None) -> dict[str, Any]:
    _reach(reach_id)
    known = REACHES.get(reach_id)
    base: dict[str, Any] = {
        "reach": {
            "reach_id": reach_id,
            "label": known.label if known else f"GEOGLOWS river segment {reach_id}",
            "confirmed": False,
            "query_point": list(reach_point(reach_id) or ()),
        },
        "source": {"name": "GEOGLOWS River Forecast System (ECMWF)", "documentation": SOURCE_PAGE},
        "problem": problem,
    }
    if fetched is None:
        return {**base, "available": False, "summary": None, "series": []}
    decision_time = now()
    try:
        summary = summarise(
            fetched.forecast,
            decision_time=decision_time,
            retrieved_at=fetched.retrieved_at,
            source_url=fetched.url,
        )
    except ForecastError as exc:
        return {**base, "available": False, "problem": str(exc), "summary": None, "series": []}
    if problem:
        summary["quality_state"] = "older"
    series = series_records(fetched.forecast, decision_time)
    return {
        **base,
        "available": True,
        "summary": summary,
        "series": series,
        # Built from this same summary, so the page's preview can never drift from the card.
        "feed_preview": feed_preview(summary, series),
        "evidence": {
            "request_url": fetched.url,
            "raw_sha256": fetched.sha256,
            "fetch_seconds": fetched.seconds,
        },
    }


@router.get(
    "/reaches",
    summary="The exploratory river reaches the pilot can show",
    openapi_extra={"x-grp-access": "protected"},
)
def list_reaches(principal: AdminUser) -> dict[str, Any]:
    return {
        "reaches": [
            {
                "reach_id": reach.reach_id,
                "label": reach.label,
                "confirmed": False,
                "query_point": list(reach.query_point),
                "map": reach_map(reach.reach_id),
            }
            for reach in REACHES.values()
        ]
    }


@router.get(
    "/districts",
    summary="Bangkok districts with the GEOGLOWS river segments captured inside them",
    openapi_extra={"x-grp-access": "protected"},
)
def list_districts(principal: AdminUser) -> dict[str, Any]:
    return {"districts": bangkok_districts()}


@router.get(
    "/districts/{admin_code}",
    summary="One Bangkok district: its outline, its river segments and its main river",
    openapi_extra={"x-grp-access": "protected"},
)
def read_district(admin_code: str, principal: AdminUser) -> dict[str, Any]:
    district = bangkok_district(admin_code)
    if district is None:
        raise not_found()
    return district


@router.get(
    "/{reach_id}",
    summary="The latest GEOGLOWS seven-day river forecast for one reach",
    openapi_extra={"x-grp-access": "protected"},
)
async def river_forecast(reach_id: int, principal: AdminUser) -> dict[str, Any]:
    _reach(reach_id)
    fetched, problem = await _current(reach_id)
    return _view(reach_id, fetched, problem)


@router.get(
    "/{reach_id}/feed-preview",
    summary="The records a Global Risk feed would serve for this reach (not sent anywhere)",
    openapi_extra={"x-grp-access": "protected"},
)
async def river_feed_preview(reach_id: int, principal: AdminUser) -> dict[str, Any]:
    _reach(reach_id)
    fetched, problem = await _current(reach_id)
    view = _view(reach_id, fetched, problem)
    if not view["available"]:
        return {"records": [], "sent_to_global_risk": False, "problem": view["problem"]}
    return view["feed_preview"]


@router.get(
    "/{reach_id}/raw/{run}",
    summary="The exact GEOGLOWS bytes behind a forecast GRP holds, for checking",
    openapi_extra={"x-grp-access": "protected"},
)
def river_raw_response(reach_id: int, run: str, principal: AdminUser) -> Response:
    _reach(reach_id)
    fetched = _forecasts.get((reach_id, run))
    if fetched is None:
        raise not_found()
    return Response(
        fetched.raw,
        media_type="application/json",
        headers={
            "Content-Disposition": (
                f'attachment; filename="geoglows_{reach_id}_{run}.json"'
            ),
            "X-Raw-SHA256": fetched.sha256,
        },
    )
