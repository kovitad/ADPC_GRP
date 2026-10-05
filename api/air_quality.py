"""Southeast Asia PM2.5, republished from SERVIR-SEA's public AQ Tracker feed (ADR-0061).

The source is public and fast (under 0.2 s), and caches for 15 minutes itself; GRP keeps its own
copy for 10 minutes, so pages and Global Risk never add load beyond one read per 10 minutes. The
anonymous route answers 404 unless ``AIR_QUALITY_FEED_PUBLIC`` is on, like the flood feed.
"""

from __future__ import annotations

import asyncio
import threading
import time
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request, Response

from api.errors import GrpError, not_found
from api.permissions import SignedInMember
from api.rate_limits import limiter
from api.settings import get_settings
from core.air_quality import AirQualityUnavailable, build_feed, fetch_latest
from core.flood_evidence.feed import serialise

router = APIRouter(prefix="/air-quality", tags=["air quality"])
public_router = APIRouter(prefix="/public/aq", tags=["air quality"])
CACHE_SECONDS = 600
_cache: dict[str, Any] = {"at": 0.0, "feed": None}
_lock = threading.Lock()


def _latest() -> dict[str, Any]:
    with _lock:
        if _cache["feed"] is not None and time.monotonic() - _cache["at"] < CACHE_SECONDS:
            return _cache["feed"]
        feed = build_feed(fetch_latest(), datetime.now(UTC))
        _cache.update(at=time.monotonic(), feed=feed)
        return feed


async def _feed_or_error() -> dict[str, Any]:
    try:
        return await asyncio.to_thread(_latest)
    except AirQualityUnavailable as error:
        raise GrpError(502, "AIR_QUALITY_UNAVAILABLE",
                       f"Air-quality data is not available right now: {error}.") from error


def _response(feed: dict[str, Any], request: Request, cache: str) -> Response:
    body, etag = serialise(feed)
    headers = {"ETag": etag, "Cache-Control": cache}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=body, media_type="application/json", headers=headers)


@router.get(
    "/sea/latest",
    summary="Latest PM2.5 forecast step for every Southeast Asian province (ADR-0061)",
    openapi_extra={"x-grp-access": "protected"},
)
async def read_air_quality(principal: SignedInMember, request: Request) -> Response:
    return _response(await _feed_or_error(), request, "private, max-age=60")


@public_router.get(
    "/sea/feed.json",
    summary="The PM2.5 feed, anonymous, for Global Risk to fetch (ADR-0061)",
    openapi_extra={"x-grp-access": "public"},
)
async def read_public_air_quality(request: Request) -> Response:
    if not get_settings().air_quality_feed_public:
        raise not_found()
    caller = request.client.host if request.client else "unknown"
    limiter.check("public_air_quality_per_caller_per_minute", caller, 30, 60)
    return _response(await _feed_or_error(), request, "public, max-age=300")
