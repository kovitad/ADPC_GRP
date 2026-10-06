"""Metadata-only review of stored ThaiWater shadow windows.

This module reads immutable raw captures and normalized lineage. It reports cadence, missingness,
station churn, correction counts, clock status, quality coverage and observation lag, but never
returns a measurement value. It performs no network request and changes no operational state.
"""

from __future__ import annotations

import gzip
from collections import Counter
from datetime import UTC, datetime
from statistics import median
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.flood_evidence.ingest import utc
from core.flood_evidence.models import (
    FETCH_OK,
    FloodSourceFetch,
    HydroObservation,
    HydroStationVersion,
)
from core.flood_evidence.observation import SourceFormatError
from core.flood_evidence.thaiwater import PRODUCTS, PROVIDER, Product, parse_product
from core.storage import LocalStorage


def _iso(moment: datetime | None) -> str | None:
    return utc(moment).isoformat() if moment else None


def _minutes(seconds: float) -> float:
    return round(seconds / 60, 1)


def _lag_summary(rows: list[HydroObservation]) -> dict[str, float] | None:
    if not rows:
        return None
    seconds = sorted((utc(row.retrieved_at) - utc(row.observed_at)).total_seconds() for row in rows)
    return {
        "minimum_minutes": _minutes(seconds[0]),
        "median_minutes": _minutes(median(seconds)),
        "maximum_minutes": _minutes(seconds[-1]),
    }


def _raw_counts(
    storage: LocalStorage, fetch: FloodSourceFetch, product: Product
) -> dict[str, Any]:
    if fetch.outcome != FETCH_OK:
        return {"state": "not_successful"}
    if not fetch.storage_key or not storage.exists(fetch.storage_key):
        return {"state": "raw_unavailable"}
    try:
        body = gzip.decompress(storage.read_bytes(fetch.storage_key))
        parsed = parse_product(body, product)
    except (OSError, SourceFormatError):
        return {"state": "invalid"}
    return {
        "state": "parsed",
        "measurements": len(parsed.values),
        "missing_measurements": parsed.feature_count - len(parsed.values),
    }


def _fetch_rows(
    session: Session,
    pilot_id: str,
    source_id: str,
    start: datetime | None,
    end: datetime,
) -> list[FloodSourceFetch]:
    query = select(FloodSourceFetch).where(
        FloodSourceFetch.pilot_id == pilot_id,
        FloodSourceFetch.source_id == source_id,
        FloodSourceFetch.retrieved_at <= end,
    )
    if start is not None:
        query = query.where(FloodSourceFetch.retrieved_at >= start)
    return list(session.scalars(query.order_by(FloodSourceFetch.retrieved_at)))


def _observations(
    session: Session, pilot_id: str, product: str, start: datetime | None, end: datetime
) -> list[HydroObservation]:
    query = select(HydroObservation).where(
        HydroObservation.pilot_id == pilot_id,
        HydroObservation.provider == PROVIDER,
        HydroObservation.product == product,
        HydroObservation.retrieved_at <= end,
    )
    if start is not None:
        query = query.where(HydroObservation.retrieved_at >= start)
    return list(session.scalars(query.order_by(HydroObservation.retrieved_at)))


def _station_summary(
    session: Session, pilot_id: str, product: str, start: datetime | None, end: datetime
) -> dict[str, Any]:
    query = select(HydroStationVersion).where(
        HydroStationVersion.pilot_id == pilot_id,
        HydroStationVersion.provider == PROVIDER,
        HydroStationVersion.product == product,
        HydroStationVersion.first_seen_at <= end,
    )
    versions = list(session.scalars(query))
    identities: dict[str, list[HydroStationVersion]] = {}
    for row in versions:
        identities.setdefault(row.provider_station_id, []).append(row)

    active: list[HydroStationVersion] = []
    for rows in identities.values():
        newest = max(rows, key=lambda row: utc(row.last_seen_at))
        if start is None or utc(newest.last_seen_at) >= start:
            active.append(newest)

    districts = {code for row in active for code in row.district_codes}
    subdistricts = {code for row in active for code in row.subdistrict_codes}
    agencies = Counter(row.originating_agency_code or "unknown" for row in active)
    identity_bases = Counter(row.identity_basis for row in active)
    versions_created = [
        row for row in versions if start is None or utc(row.first_seen_at) >= start
    ]
    return {
        "active_station_identities": len(active),
        "active_districts": len(districts),
        "active_subdistricts": len(subdistricts),
        "identity_bases": dict(sorted(identity_bases.items())),
        "originating_agencies": dict(sorted(agencies.items())),
        "station_versions_created": len(versions_created),
        "identities_with_multiple_versions": sum(len(rows) > 1 for rows in identities.values()),
    }


def _correction_count(
    session: Session,
    pilot_id: str,
    product: str,
    start: datetime | None,
    end: datetime,
) -> int:
    rows = session.execute(
        select(
            HydroObservation.station_version_id,
            HydroObservation.observed_at,
            HydroObservation.retrieved_at,
        ).where(
            HydroObservation.pilot_id == pilot_id,
            HydroObservation.provider == PROVIDER,
            HydroObservation.product == product,
            HydroObservation.retrieved_at <= end,
        )
    )
    groups: dict[tuple[Any, datetime], list[datetime]] = {}
    for station_id, observed_at, retrieved_at in rows:
        groups.setdefault((station_id, utc(observed_at)), []).append(utc(retrieved_at))
    return sum(
        len(retrievals) > 1
        and (start is None or any(retrieved_at >= start for retrieved_at in retrievals))
        for retrievals in groups.values()
    )


def thaiwater_shadow_analysis(
    session: Session,
    storage: LocalStorage,
    pilot_id: str,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict[str, Any]:
    """Build a reproducible metadata-only report from stored shadow evidence."""

    end = utc(end or datetime.now(UTC))
    start = utc(start) if start else None
    if start is not None and start > end:
        raise ValueError("Analysis start must not be after end")

    products: list[dict[str, Any]] = []
    for product in PRODUCTS:
        fetches = _fetch_rows(session, pilot_id, product.source_id, start, end)
        observations = _observations(session, pilot_id, product.product, start, end)
        previous_sha: str | None = None
        fetch_reports: list[dict[str, Any]] = []
        intervals: list[float] = []
        for index, fetch in enumerate(fetches):
            if index:
                intervals.append(
                    (utc(fetch.retrieved_at) - utc(fetches[index - 1].retrieved_at)).total_seconds()
                )
            raw = _raw_counts(storage, fetch, product)
            fetch_reports.append(
                {
                    "retrieved_at": _iso(fetch.retrieved_at),
                    "outcome": fetch.outcome,
                    "http_status": fetch.http_status,
                    "features": fetch.record_count,
                    "new_pilot_states": fetch.new_states,
                    "raw_sha256": fetch.sha256,
                    "raw_changed_from_previous": (
                        None if previous_sha is None else fetch.sha256 != previous_sha
                    ),
                    "raw_analysis": raw,
                }
            )
            previous_sha = fetch.sha256

        outcomes = Counter(fetch.outcome for fetch in fetches)
        clocks = Counter(row.clock_status for row in observations)
        quality = Counter(row.quality_flag or "unreported" for row in observations)
        raw_states = Counter(report["raw_analysis"]["state"] for report in fetch_reports)
        successful_fetches = outcomes[FETCH_OK]
        all_successes_parsed = raw_states["parsed"] == successful_fetches
        missing = (
            sum(
                report["raw_analysis"].get("missing_measurements", 0)
                for report in fetch_reports
            )
            if all_successes_parsed
            else None
        )
        raw_hashes = {fetch.sha256 for fetch in fetches if fetch.sha256 is not None}
        products.append(
            {
                "product": product.product,
                "source_id": product.source_id,
                "default_interval_minutes": product.interval_minutes,
                "fetch_attempts": len(fetches),
                "fetch_outcomes": dict(sorted(outcomes.items())),
                "first_fetch_at": _iso(fetches[0].retrieved_at) if fetches else None,
                "last_fetch_at": _iso(fetches[-1].retrieved_at) if fetches else None,
                "observed_interval_minutes": (
                    {
                        "minimum": _minutes(min(intervals)),
                        "median": _minutes(median(intervals)),
                        "maximum": _minutes(max(intervals)),
                    }
                    if intervals
                    else None
                ),
                "distinct_raw_responses": len(raw_hashes),
                "raw_change_events": sum(
                    report["raw_changed_from_previous"] is True for report in fetch_reports
                ),
                "raw_analysis_states": dict(sorted(raw_states.items())),
                "missing_measurements": missing,
                "station_summary": _station_summary(session, pilot_id, product.product, start, end),
                "stored_states_created": len(observations),
                "corrected_station_times": _correction_count(
                    session, pilot_id, product.product, start, end
                ),
                "clock_status_counts": dict(sorted(clocks.items())),
                "quality_flag_counts": dict(sorted(quality.items())),
                "observation_lag": _lag_summary(observations),
                "fetches": fetch_reports,
            }
        )

    return {
        "provider": PROVIDER,
        "mode": "shadow_window_analysis",
        "pilot_id": pilot_id,
        "window": {"start": _iso(start), "end": _iso(end)},
        "generated_at": datetime.now(UTC).isoformat(),
        "publication_approved": False,
        "contains_measurement_values": False,
        "network_requests_made": False,
        "products": products,
    }


__all__ = ["thaiwater_shadow_analysis"]
