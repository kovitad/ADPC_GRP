"""Public, database-only ThaiWater observation feed for the temporary Bangkok pilot.

The feed publishes only the latest valid stored value for each current station and product. It
never contacts ThaiWater, returns raw provider responses, or changes flood warnings/confidence.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.flood_evidence.config import PilotConfig
from core.flood_evidence.ingest import utc
from core.flood_evidence.models import HydroObservation, HydroStationVersion
from core.flood_evidence.thaiwater import PROVIDER

SCHEMA_VERSION = "grp.thaiwater.pilot-observations.v1"
ATTRIBUTION = (
    "ThaiWater; delivered by Hydro-Informatics Institute (HII). "
    "The originating government agency is stated on each record."
)


def _iso(moment: datetime) -> str:
    return utc(moment).isoformat()


def _latest_station_versions(
    session: Session, pilot_id: str, as_of: datetime
) -> list[HydroStationVersion]:
    rows = session.scalars(
        select(HydroStationVersion).where(
            HydroStationVersion.pilot_id == pilot_id,
            HydroStationVersion.provider == PROVIDER,
            HydroStationVersion.first_seen_at <= as_of,
        )
    )
    newest: dict[tuple[str, str], HydroStationVersion] = {}
    for row in rows:
        key = (row.product, row.provider_station_id)
        previous = newest.get(key)
        if previous is None or utc(row.last_seen_at) > utc(previous.last_seen_at):
            newest[key] = row
    return list(newest.values())


def public_government_observation_feed(
    session: Session, config: PilotConfig, as_of: datetime
) -> dict[str, Any]:
    """Return latest valid pilot-area measurements without raw payloads or secret metadata."""

    station_rows = _latest_station_versions(session, config.pilot_id, as_of)
    stations = {row.id: row for row in station_rows}
    observations: list[HydroObservation] = []
    if stations:
        ranked = (
            select(
                HydroObservation.id.label("observation_id"),
                func.row_number()
                .over(
                    partition_by=HydroObservation.station_version_id,
                    order_by=(
                        HydroObservation.observed_at.desc(),
                        HydroObservation.retrieved_at.desc(),
                        HydroObservation.id.desc(),
                    ),
                )
                .label("position"),
            )
            .where(
                HydroObservation.station_version_id.in_(stations),
                HydroObservation.provider == PROVIDER,
                HydroObservation.clock_status == "valid",
                HydroObservation.observed_at <= as_of,
                HydroObservation.retrieved_at <= as_of,
            )
            .subquery()
        )
        latest_ids = select(ranked.c.observation_id).where(ranked.c.position == 1)
        observations = list(
            session.scalars(select(HydroObservation).where(HydroObservation.id.in_(latest_ids)))
        )

    stale_after = timedelta(minutes=config.freshness_minutes["stale"])
    records = []
    for observation in observations:
        station = stations[observation.station_version_id]
        valid_until = utc(observation.observed_at) + stale_after
        records.append(
            {
                "product": observation.product,
                "station_id": station.provider_station_id,
                "station_code": station.station_code,
                "station_name": station.station_name,
                "station_type": station.station_type,
                "longitude": station.longitude,
                "latitude": station.latitude,
                "district_codes": station.district_codes,
                "subdistrict_codes": station.subdistrict_codes,
                "variable": observation.variable,
                "value": observation.value,
                "unit": observation.unit,
                "datum": observation.datum,
                "observed_at": _iso(observation.observed_at),
                "retrieved_at": _iso(observation.retrieved_at),
                "valid_until": _iso(valid_until),
                "is_stale": as_of > valid_until,
                "quality_flag": observation.quality_flag,
                "originating_agency_code": observation.originating_agency_code,
                "originating_agency_name": observation.originating_agency_name,
                "delivery_provider": observation.delivery_provider,
            }
        )
    records.sort(key=lambda row: (row["product"], row["station_code"] or row["station_id"]))
    return {
        "schema_version": SCHEMA_VERSION,
        "pilot_id": config.pilot_id,
        "generated_at": _iso(as_of),
        "provider": "ThaiWater",
        "attribution": ATTRIBUTION,
        "disclaimer": (
            "Government observations only; not a GRP warning and not used to change incident "
            "confidence or Global Risk calculations."
        ),
        "records": records,
    }


__all__ = ["ATTRIBUTION", "SCHEMA_VERSION", "public_government_observation_feed"]
