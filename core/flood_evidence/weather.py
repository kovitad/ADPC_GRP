"""Rain now and the next 30 minutes from Longdo Weather (ADR-0049). Context, never evidence.

The worker calls Longdo Weather for live pilots only (never in a replay), and only when the
radar has a new observation (about every 15 minutes). For each demo district and the top
incidents it stores rain now and the +15/+30 minute forecast within a radius. (The polygon
query answered HTTP 403 for the pilot key's plan, so districts use a circle around their centre.)

- Rain is weather context. It is never a source family, never changes confidence or conflict,
  and a forecast is never an observation.
- A failed or unavailable call is stored as ``unavailable``: the page says "rain unknown",
  never "no rain".
- The key is sent as ``key=`` but never stored or logged: errors are redacted before saving.
"""

from __future__ import annotations

import json
import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.flood_evidence.areas import all_areas
from core.flood_evidence.config import PilotConfig
from core.flood_evidence.incident_store import list_incidents
from core.flood_evidence.ingest import utc
from core.flood_evidence.models import FloodWeather

logger = logging.getLogger("grp.flood_weather")
# httpx logs every request URL at INFO; Longdo takes the key in the URL, so never let it log.
logging.getLogger("httpx").setLevel(logging.WARNING)
BASE = "https://weather.longdo.com"
TIMEOUT_SECONDS = 20.0
TOP_INCIDENTS = 10
DISTRICT_RADIUS_CAP_KM = 8.0
LEVELS = ("no_rain", "very_light", "light", "moderate", "heavy", "very_heavy")
SOURCE = "Longdo Weather (radar estimate, provided as is)"
USER_AGENT = "GRP-flood-pilot/0.1 (ADPC SERVIR pilot)"


class WeatherUnavailable(RuntimeError):
    pass


@dataclass
class LongdoWeather:
    """A tiny client. ``get``/``post`` can be replaced in tests; nothing here logs a URL."""

    key: str
    get: Callable[[str, dict[str, Any]], Any] | None = None
    post: Callable[[str, dict[str, Any]], Any] | None = None

    def redact(self, text: str) -> str:
        return text.replace(self.key, "<key>") if self.key else text

    def _request(self, method: str, path: str, params: dict[str, Any], body: Any = None) -> Any:
        try:
            with httpx.Client(timeout=TIMEOUT_SECONDS, headers={"User-Agent": USER_AGENT}) as c:
                response = c.request(method, BASE + path, params={**params, "key": self.key},
                                     json=body)
        except httpx.HTTPError as error:
            raise WeatherUnavailable(type(error).__name__) from None
        if response.status_code != 200:
            raise WeatherUnavailable(f"HTTP {response.status_code}")
        try:
            return response.json()
        except json.JSONDecodeError:
            raise WeatherUnavailable("Not JSON") from None

    def call_get(self, path: str, params: dict[str, Any]) -> Any:
        return (self.get or (lambda p, q: self._request("GET", p, q)))(path, params)

    def call_post(self, path: str, body: dict[str, Any]) -> Any:
        return (self.post or (lambda p, b: self._request("POST", p, {}, b)))(path, body)


def _stats(payload: Any) -> dict[str, Any] | None:
    """The fields the page shows, checked; anything unexpected becomes unknown."""

    stats = payload.get("stats") if isinstance(payload, dict) else None
    if not isinstance(stats, dict):
        return None
    level = (stats.get("dominant_level") or {}).get("level")
    max_intensity = stats.get("max_intensity")
    if level not in LEVELS or not isinstance(max_intensity, (int, float)):
        return None
    return {
        "dominant_level": level,
        "max_level": LEVELS[min(int(max_intensity), len(LEVELS) - 1)],
        "coverage_pct": round(float(stats.get("rain_coverage_pct") or 0.0), 1),
    }


def _forecast(payload: Any) -> list[dict[str, Any]] | None:
    items = payload.get("forecast") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return None
    out = []
    for item in items:
        stats = _stats(item) if item.get("available") else None
        out.append({"time": item.get("forecast_time"), "available": stats is not None,
                    **(stats or {})})
    return out


def _radius_km(bbox: list[float], cap: float = 3.0) -> float:
    west, south, east, north = bbox
    lat = (south + north) / 2
    dx = (east - west) * 111.32 * math.cos(math.radians(lat))
    dy = (north - south) * 110.54
    return round(min(cap, max(0.5, math.hypot(dx, dy) / 2)), 2)


def observation_time(client: LongdoWeather) -> datetime:
    listing = client.call_get("/rain/api/v1/layer/list", {})
    stamp = (listing.get("radar") or {}).get("observation_base_time") if isinstance(
        listing, dict) else None
    if not isinstance(stamp, (int, float)):
        raise WeatherUnavailable("No radar observation time")
    return datetime.fromtimestamp(stamp, UTC)


def _scopes(session: Session, config: PilotConfig, now: datetime) -> list[dict[str, Any]]:
    codes = set(config.rain_areas)
    scopes = []
    for area in all_areas(config.base_id):
        if area["admin_code"] not in codes:
            continue
        polygon = area["outline"]
        rings = polygon["coordinates"] if polygon["type"] == "Polygon" else polygon[
            "coordinates"][0]
        points = rings[0]
        lons, lats = [p[0] for p in points], [p[1] for p in points]
        bbox = [min(lons), min(lats), max(lons), max(lats)]
        # A circle around the district: the polygon query answered 403 for this key's plan.
        scopes.append({"kind": "district", "id": area["admin_code"],
                       "center": [(bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2],
                       "radius_km": _radius_km(bbox, cap=DISTRICT_RADIUS_CAP_KM)})
    active = [i for i in list_incidents(session, config, now)["incidents"]
              if i["status"] == "active"][:TOP_INCIDENTS]
    for incident in active:
        scopes.append({"kind": "incident", "id": incident["incident_id"],
                       "center": incident["center"], "radius_km": _radius_km(incident["bbox"])})
    return scopes


def last_observation(session: Session, pilot_id: str) -> datetime | None:
    value = session.scalar(select(func.max(FloodWeather.observed_base_time))
                           .where(FloodWeather.pilot_id == pilot_id))
    return utc(value) if value else None


def run_weather(
    session: Session, config: PilotConfig, client: LongdoWeather, now: datetime
) -> int | None:
    """Record rain for every scope once per radar observation. None when there was nothing new."""

    if config.is_replay:
        raise ValueError("Weather is live only; a replay never calls Longdo")
    try:
        base_time = observation_time(client)
    except WeatherUnavailable as error:
        logger.warning("Longdo Weather unavailable: %s", client.redact(str(error)))
        return None
    if last_observation(session, config.pilot_id) == base_time:
        return None
    stored = 0
    for scope in _scopes(session, config, now):
        lon, lat = scope["center"]
        now_stats = forecast = None
        errors = []
        try:
            now_stats = _stats(client.call_get("/rain/api/v1/area", {
                "lat": lat, "lon": lon, "radius_km": scope["radius_km"]}))
        except WeatherUnavailable as error:
            errors.append("now: " + client.redact(str(error)))
        try:
            forecast = _forecast(client.call_get("/rain/api/v1/forecast/area", {
                "lat": lat, "lon": lon, "radius_km": scope["radius_km"]}))
        except WeatherUnavailable as error:
            errors.append("forecast: " + client.redact(str(error)))
        session.add(FloodWeather(
            pilot_id=config.pilot_id, observed_base_time=base_time, retrieved_at=now,
            scope_kind=scope["kind"], scope_id=scope["id"], radius_km=scope["radius_km"],
            rain_now=now_stats, forecast=forecast,
            outcome="ok" if now_stats is not None or forecast else "unavailable",
            error="; ".join(errors) or None,
        ))
        stored += 1
    session.flush()
    return stored


def latest_weather(session: Session, config: PilotConfig) -> dict[str, Any]:
    if config.is_replay:
        return {"available": False, "reason": "replay", "scopes": []}
    base = last_observation(session, config.pilot_id)
    if base is None:
        return {"available": False, "reason": "not_collected", "scopes": []}
    rows = session.scalars(select(FloodWeather).where(
        FloodWeather.pilot_id == config.pilot_id, FloodWeather.observed_base_time == base))
    return {
        "available": True,
        "observed_at": base.isoformat(),
        "source": SOURCE,
        "scopes": [
            {"kind": r.scope_kind, "id": r.scope_id, "radius_km": r.radius_km,
             "rain_now": r.rain_now, "forecast": r.forecast, "outcome": r.outcome}
            for r in rows
        ],
    }
