"""How long flood-pilot evidence is kept (ADR-0045). Run hourly by the worker, live pilots only.

- **Raw downloads** older than ``raw_days`` are deleted a whole UTC day at a time (storage only
  removes folders, never a loose file). The fetch row stays with its SHA-256 as proof of what was
  received; its ``storage_key`` is cleared, so a replay can no longer cover that day.
- **Report IDs** older than ``raw_days`` (Traffy ticket IDs and news links can lead to people) are
  replaced by an opaque ``pruned:`` key. The observed facts stay.
- **Per-snapshot facility states** older than ``exposure_days`` are deleted; "what changed"
  needs only the last 24 hours.

Observations, incidents and their events are kept: they are small and are the pilot's history.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from core.flood_evidence.config import PilotConfig
from core.flood_evidence.models import FloodAssetExposure, FloodObservation, FloodSourceFetch
from core.flood_evidence.observation import REPORT
from core.storage import LocalStorage

PRUNED = "pruned:"


def prune(session: Session, config: PilotConfig, now: datetime) -> dict[str, Any]:
    """Update the database for retention. Commit, then call ``delete_raw`` with the result."""

    if config.is_replay:
        raise ValueError("Retention runs on live pilots; replays expire on their own")
    raw_cutoff = now - timedelta(days=config.retention["raw_days"])
    # Whole UTC days strictly before the cutoff day, so a day folder is never half deleted.
    day_cutoff = datetime(raw_cutoff.year, raw_cutoff.month, raw_cutoff.day,
                          tzinfo=raw_cutoff.tzinfo)
    old = list(session.scalars(
        select(FloodSourceFetch).where(
            FloodSourceFetch.pilot_id == config.pilot_id,
            FloodSourceFetch.retrieved_at < day_cutoff,
            FloodSourceFetch.storage_key.is_not(None),
        )
    ))
    prefixes = sorted({f.storage_key.rsplit("/", 1)[0] for f in old})
    for fetch in old:
        fetch.storage_key = None

    renamed = 0
    reports = session.scalars(
        select(FloodObservation).where(
            FloodObservation.pilot_id == config.pilot_id,
            FloodObservation.kind == REPORT,
            FloodObservation.last_seen_at < raw_cutoff,
            ~FloodObservation.external_id.startswith(PRUNED),
        )
    )
    for row in reports:
        row.external_id = PRUNED + row.record_key[:16]
        renamed += 1

    exposure_cutoff = now - timedelta(days=config.retention["exposure_days"])
    stale_fetches = select(FloodSourceFetch.id).where(
        FloodSourceFetch.pilot_id == config.pilot_id,
        FloodSourceFetch.retrieved_at < exposure_cutoff,
    )
    removed = session.execute(
        delete(FloodAssetExposure).where(
            FloodAssetExposure.pilot_id == config.pilot_id,
            FloodAssetExposure.fetch_id.in_(stale_fetches),
        )
    ).rowcount
    session.flush()
    return {
        "raw_days_removed": len(prefixes),
        "raw_fetches_cleared": len(old),
        "report_ids_pruned": renamed,
        "exposure_rows_removed": removed or 0,
        "raw_kept_from": day_cutoff.isoformat(),
        # Deleted by ``delete_raw`` only after the caller commits, so no row ever points at a
        # file that is already gone.
        "raw_prefixes": prefixes,
    }


def delete_raw(storage: LocalStorage, result: dict[str, Any]) -> None:
    for prefix in result["raw_prefixes"]:
        storage.delete_prefix(prefix)
