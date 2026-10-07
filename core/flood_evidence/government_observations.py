"""Protected health and coverage read model for ThaiWater shadow observations.

The read model reports whether capture is operating and what has been stored. It deliberately
returns no measurement values, creates no area aggregate and makes no warning or confidence
judgement. Web requests read the local database only; they never contact ThaiWater.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from core.flood_evidence.config import PilotConfig, SourceConfig
from core.flood_evidence.ingest import utc
from core.flood_evidence.models import (
    FETCH_OK,
    FloodSourceFetch,
    HydroObservation,
    HydroStationVersion,
)
from core.flood_evidence.thaiwater import PROVIDER, sources


def _iso(moment: datetime | None) -> str | None:
    return utc(moment).isoformat() if moment else None


def _latest_fetch(
    session: Session, pilot_id: str, source_id: str, as_of: datetime, *, successful: bool
) -> FloodSourceFetch | None:
    query = select(FloodSourceFetch).where(
        FloodSourceFetch.pilot_id == pilot_id,
        FloodSourceFetch.source_id == source_id,
        FloodSourceFetch.retrieved_at <= as_of,
    )
    if successful:
        query = query.where(FloodSourceFetch.outcome == FETCH_OK)
    return session.scalars(query.order_by(FloodSourceFetch.retrieved_at.desc()).limit(1)).first()


def _fetch_state(
    attempt: FloodSourceFetch | None,
    success: FloodSourceFetch | None,
    source: SourceConfig,
    as_of: datetime,
    offline_after: timedelta,
) -> str:
    if attempt is None:
        return "never_fetched"
    if success is None or as_of - utc(success.retrieved_at) > offline_after:
        return "offline"
    on_time = timedelta(minutes=source.interval_minutes * 3)
    if attempt.outcome == FETCH_OK and as_of - utc(attempt.retrieved_at) <= on_time:
        return "ok"
    return "degraded"


def _latest_station_versions(
    session: Session, pilot_id: str, product: str, as_of: datetime
) -> list[HydroStationVersion]:
    rows = session.scalars(
        select(HydroStationVersion).where(
            HydroStationVersion.pilot_id == pilot_id,
            HydroStationVersion.provider == PROVIDER,
            HydroStationVersion.product == product,
            HydroStationVersion.first_seen_at <= as_of,
        )
    )
    newest: dict[str, HydroStationVersion] = {}
    for row in rows:
        previous = newest.get(row.provider_station_id)
        if previous is None or utc(row.last_seen_at) > utc(previous.last_seen_at):
            newest[row.provider_station_id] = row
    return list(newest.values())


def _counter_items(values: Counter[str]) -> list[dict[str, Any]]:
    return [{"value": value, "count": values[value]} for value in sorted(values)]


def _coverage(stations: list[HydroStationVersion]) -> dict[str, Any]:
    districts: Counter[str] = Counter()
    subdistricts: Counter[str] = Counter()
    agencies: Counter[str] = Counter()
    agency_names: dict[str, str | None] = {}
    identity_bases: Counter[str] = Counter()
    for station in stations:
        districts.update(station.district_codes)
        subdistricts.update(station.subdistrict_codes)
        identity_bases[station.identity_basis] += 1
        agency_code = station.originating_agency_code or "unknown"
        agencies[agency_code] += 1
        agency_names.setdefault(agency_code, station.originating_agency_name)
    return {
        "stations": len(stations),
        "districts": _counter_items(districts),
        "subdistricts": _counter_items(subdistricts),
        "originating_agencies": [
            {"code": code, "name": agency_names[code], "stations": agencies[code]}
            for code in sorted(agencies)
        ],
        "identity_bases": _counter_items(identity_bases),
    }


def _observation_summary(
    session: Session, pilot_id: str, product: str, as_of: datetime
) -> dict[str, Any]:
    filters = (
        HydroObservation.pilot_id == pilot_id,
        HydroObservation.provider == PROVIDER,
        HydroObservation.product == product,
        HydroObservation.retrieved_at <= as_of,
    )
    state_count, station_versions, latest_observed, latest_retrieved = session.execute(
        select(
            func.count(HydroObservation.id),
            func.count(distinct(HydroObservation.station_version_id)),
            func.max(HydroObservation.observed_at),
            func.max(HydroObservation.retrieved_at),
        ).where(*filters)
    ).one()
    clock_counts = {
        str(status): int(count)
        for status, count in session.execute(
            select(HydroObservation.clock_status, func.count(HydroObservation.id))
            .where(*filters)
            .group_by(HydroObservation.clock_status)
        )
    }
    quality_counts = {
        str(flag) if flag is not None else "unreported": int(count)
        for flag, count in session.execute(
            select(HydroObservation.quality_flag, func.count(HydroObservation.id))
            .where(*filters)
            .group_by(HydroObservation.quality_flag)
        )
    }
    valid_latest = session.scalar(
        select(func.max(HydroObservation.observed_at)).where(
            *filters, HydroObservation.clock_status == "valid"
        )
    )
    return {
        "stored_observation_states": int(state_count),
        "station_versions_with_observations": int(station_versions),
        "latest_observed_at": _iso(latest_observed),
        "latest_valid_observed_at": _iso(valid_latest),
        "latest_retrieved_at": _iso(latest_retrieved),
        "clock_status_counts": clock_counts,
        "quality_flag_counts": quality_counts,
    }


def government_observation_status(
    session: Session,
    config: PilotConfig,
    as_of: datetime,
    *,
    capture_enabled: bool,
    key_configured: bool,
    base_url: str,
    interval_minutes: int,
    publication_approved: bool = False,
) -> dict[str, Any]:
    """Summarize stored shadow evidence without returning values or contacting the provider."""

    if config.is_replay:
        return {
            "provider": PROVIDER,
            "mode": "shadow",
            "state": "not_available_in_replay",
            "as_of": as_of.isoformat(),
            "publication_approved": publication_approved,
            "products": [],
        }

    configured_sources = sources(base_url, interval_minutes)
    offline_after = timedelta(minutes=config.freshness_minutes["stale"])
    products = []
    for source in configured_sources:
        attempt = _latest_fetch(
            session, config.pilot_id, source.source_id, as_of, successful=False
        )
        success = _latest_fetch(
            session, config.pilot_id, source.source_id, as_of, successful=True
        )
        station_rows = _latest_station_versions(
            session, config.pilot_id, source.adapter, as_of
        )
        products.append(
            {
                "source_id": source.source_id,
                "product": source.adapter,
                "state": _fetch_state(attempt, success, source, as_of, offline_after),
                "last_attempt_at": _iso(attempt.retrieved_at) if attempt else None,
                "last_attempt_outcome": attempt.outcome if attempt else None,
                "last_success_at": _iso(success.retrieved_at) if success else None,
                "last_success_features": success.record_count if success else None,
                "last_success_sha256": success.sha256 if success else None,
                "coverage": _coverage(station_rows),
                "observations": _observation_summary(
                    session, config.pilot_id, source.adapter, as_of
                ),
            }
        )

    product_states = {product["state"] for product in products}
    if not capture_enabled:
        state = "capture_disabled"
    elif not key_configured:
        state = "credential_missing"
    elif product_states == {"ok"}:
        state = "ok"
    elif "offline" in product_states:
        state = "offline"
    elif product_states == {"never_fetched"}:
        state = "awaiting_first_fetch"
    else:
        state = "degraded"
    return {
        "provider": PROVIDER,
        "mode": "shadow",
        "state": state,
        "as_of": as_of.isoformat(),
        "capture_enabled": capture_enabled,
        "credential_configured": key_configured,
        "publication_approved": publication_approved,
        "products": products,
    }


__all__ = ["government_observation_status"]
