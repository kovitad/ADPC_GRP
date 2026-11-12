"""Observed bank context and honest 1–3 day river-flow slots for Live.

ThaiWater can describe one station's observed level and provider-reported distance to its bank.
GEOGLOWS can describe forecast discharge for a model reach. Without a reviewed station/reach
mapping and rating curve these facts stay separate: every future bank-overtopping state is
``undetermined`` rather than a guessed yes/no answer (ADR-0070).
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.flood_evidence.areas import pilot_areas, pilot_subdistricts
from core.flood_evidence.config import PilotConfig
from core.flood_evidence.ingest import utc
from core.flood_evidence.models import HydroObservation, HydroStationVersion
from core.flood_evidence.thaiwater import PROVIDER

MAX_NEARBY_KM = 15.0
STEADY_RATIO = 0.05


def _coordinates(value: Any) -> list[tuple[float, float]]:
    """Flatten GeoJSON polygon coordinates into lon/lat pairs."""

    points: list[tuple[float, float]] = []
    if isinstance(value, list):
        if len(value) >= 2 and all(isinstance(item, int | float) for item in value[:2]):
            points.append((float(value[0]), float(value[1])))
        else:
            for item in value:
                points.extend(_coordinates(item))
    return points


def _area_centre(config: PilotConfig, area_code: str) -> tuple[float, float] | None:
    areas = pilot_areas(config) + pilot_subdistricts(config)
    area = next((item for item in areas if item["admin_code"] == area_code), None)
    if area is None and len(area_code) > 4:
        area = next((item for item in areas if item["admin_code"] == area_code[:4]), None)
    points = _coordinates((area or {}).get("outline", {}).get("coordinates"))
    if not points:
        return None
    west = min(point[0] for point in points)
    east = max(point[0] for point in points)
    south = min(point[1] for point in points)
    north = max(point[1] for point in points)
    return ((west + east) / 2, (south + north) / 2)


def _distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lon1, lat1 = map(math.radians, a)
    lon2, lat2 = map(math.radians, b)
    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1
    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return 2 * 6371.0 * math.asin(math.sqrt(value))


def _latest_water_stations(
    session: Session, pilot_id: str, as_of: datetime
) -> list[HydroStationVersion]:
    rows = session.scalars(
        select(HydroStationVersion).where(
            HydroStationVersion.pilot_id == pilot_id,
            HydroStationVersion.provider == PROVIDER,
            HydroStationVersion.product == "waterlevel",
            HydroStationVersion.first_seen_at <= as_of,
        )
    )
    newest: dict[str, HydroStationVersion] = {}
    for row in rows:
        previous = newest.get(row.provider_station_id)
        if previous is None or utc(row.last_seen_at) > utc(previous.last_seen_at):
            newest[row.provider_station_id] = row
    return list(newest.values())


def _latest_observation(
    session: Session, station: HydroStationVersion, as_of: datetime
) -> HydroObservation | None:
    return session.scalar(
        select(HydroObservation)
        .where(
            HydroObservation.station_version_id == station.id,
            HydroObservation.clock_status == "valid",
            HydroObservation.observed_at <= as_of,
            HydroObservation.retrieved_at <= as_of,
        )
        .order_by(
            HydroObservation.observed_at.desc(),
            HydroObservation.retrieved_at.desc(),
            HydroObservation.id.desc(),
        )
        .limit(1)
    )


def observed_bank_context(
    session: Session,
    config: PilotConfig,
    area_code: str,
    as_of: datetime,
) -> dict[str, Any]:
    """Return one exact-area or nearby water-level station, never an area average."""

    district_code = area_code[:4]
    centre = _area_centre(config, area_code)
    candidates: list[tuple[HydroStationVersion, HydroObservation]] = []
    for station in _latest_water_stations(session, config.pilot_id, as_of):
        observation = _latest_observation(session, station, as_of)
        if observation is not None:
            candidates.append((station, observation))
    if not candidates or centre is None:
        return {"status": "unavailable", "reason": "no_station"}

    exact = [item for item in candidates if district_code in item[0].district_codes]
    pool = exact or candidates
    selected = min(
        pool,
        key=lambda item: _distance_km(
            centre, (item[0].longitude, item[0].latitude)
        ),
    )
    station, observation = selected
    distance = _distance_km(centre, (station.longitude, station.latitude))
    if not exact and distance > MAX_NEARBY_KM:
        return {"status": "unavailable", "reason": "no_station_nearby"}

    stale_after = timedelta(minutes=config.freshness_minutes["stale"])
    valid_until = utc(observation.observed_at) + stale_after
    bank_difference = observation.quality.get("provider_bank_difference")
    if not isinstance(bank_difference, int | float) or not math.isfinite(bank_difference):
        bank_difference = None
    provider_status = observation.quality.get("provider_status")
    return {
        "status": "available",
        "relationship": "in_area" if exact else "nearby",
        "distance_km": round(distance, 2),
        "station": {
            "station_code": station.station_code,
            "station_name": station.station_name,
            "longitude": station.longitude,
            "latitude": station.latitude,
        },
        "observation": {
            "value": observation.value,
            "unit": observation.unit,
            "datum": observation.datum,
            "observed_at": utc(observation.observed_at).isoformat(),
            "retrieved_at": utc(observation.retrieved_at).isoformat(),
            "valid_until": valid_until.isoformat(),
            "is_stale": as_of > valid_until,
            "quality_flag": observation.quality_flag,
            "provider_bank_difference_m": bank_difference,
            "provider_bank_status": provider_status if isinstance(provider_status, str) else None,
        },
        "limitations": [
            "A station observation applies at the station, not to the whole area.",
            "Provider bank difference is observed context, not a future forecast.",
        ],
    }


def _trend(first: float, last: float) -> str:
    if last > first * (1 + STEADY_RATIO):
        return "rise"
    if last < first * (1 - STEADY_RATIO):
        return "fall"
    return "steady"


def three_day_flow_slots(view: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Split an existing 72-hour GEOGLOWS view into three deterministic 24-hour cards."""

    if not view or not view.get("available") or not view.get("summary"):
        return [
            {
                "day": day,
                "status": "forecast_unavailable",
                "overtopping": "undetermined",
                "reason_codes": ["forecast_unavailable"],
            }
            for day in range(1, 4)
        ]
    summary = view["summary"]
    start = datetime.fromisoformat(summary["window_start_utc"].replace("Z", "+00:00"))
    rows = view.get("series") or []
    slots = []
    for index in range(3):
        slot_start = start + timedelta(hours=24 * index)
        slot_end = slot_start + timedelta(hours=24)
        selected = [
            row
            for row in rows
            if slot_start
            <= datetime.fromisoformat(row["valid_at_utc"].replace("Z", "+00:00"))
            < slot_end
        ]
        if selected:
            peak = max(selected, key=lambda row: row["median_m3s"])
            flow = {
                "status": "available",
                "first_median_m3s": selected[0]["median_m3s"],
                "last_median_m3s": selected[-1]["median_m3s"],
                "median_peak_m3s": peak["median_m3s"],
                "median_peak_valid_at_utc": peak["valid_at_utc"],
                "trend": _trend(selected[0]["median_m3s"], selected[-1]["median_m3s"]),
                "steps": len(selected),
            }
        else:
            flow = {"status": "unavailable"}
        slots.append(
            {
                "day": index + 1,
                "status": "available" if selected else "forecast_unavailable",
                "start_utc": slot_start.isoformat(),
                "end_utc": slot_end.isoformat(),
                "flow": flow,
                "overtopping": "undetermined",
                "reason_codes": [
                    "no_rating_curve",
                    "station_reach_not_reviewed",
                    "local_controls_not_modelled",
                ],
            }
        )
    return slots


__all__ = ["MAX_NEARBY_KM", "observed_bank_context", "three_day_flow_slots"]
