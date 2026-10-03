"""Compute and read facility exposure per roads snapshot (ADR-0040).

The worker calls ``store_exposure`` right after a good roads snapshot is stored, so the spatial
work never runs in a web request. Reads return the records of the latest good snapshot.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.flood_evidence.assets import assess, asset_registry, flooded_now
from core.flood_evidence.config import PilotConfig
from core.flood_evidence.models import FloodAssetExposure, FloodSourceFetch
from core.flood_evidence.situation import current_roads, latest_roads_snapshot


def store_exposure(session: Session, config: PilotConfig, fetch: FloodSourceFetch) -> int:
    """Assess every facility against the snapshot ``fetch`` and store one row each."""

    assets, _ = asset_registry(config.base_id)
    if not assets:
        return 0
    roads = current_roads(session, config, fetch.retrieved_at)["features"]
    records = assess(
        assets,
        flooded_now(roads),
        near_m=config.exposure["near_m"],
        frontage_m=config.exposure["frontage_m"],
    )
    for record in records:
        session.add(
            FloodAssetExposure(
                pilot_id=config.pilot_id,
                fetch_id=fetch.id,
                computed_at=fetch.retrieved_at,
                **record,
            )
        )
    session.flush()
    return len(records)


def latest_exposure(session: Session, config: PilotConfig, as_of: datetime) -> dict[str, Any]:
    """Facilities with their state from the latest good roads snapshot at ``as_of``."""

    assets, source = asset_registry(config.base_id)
    snapshot = latest_roads_snapshot(session, config, as_of)
    rows = {}
    if snapshot is not None:
        rows = {
            row.asset_id: row
            for row in session.scalars(
                select(FloodAssetExposure).where(FloodAssetExposure.fetch_id == snapshot.id)
            )
        }
    # Imported here: reviews read the asset registry through this package too.
    from core.flood_evidence.reviews import facility_overrides

    confirmed = facility_overrides(session, config, as_of)
    out = []
    for asset in assets:
        row = rows.get(asset.asset_id)
        item = asset.public()
        if row is None:
            # Not assessed against this snapshot: say so rather than guess.
            item.update(exposure_state="not_assessed", access_state="access_unknown",
                        nearest_road_key=None, nearest_distance_m=None, road_keys=[],
                        reasons=["not_assessed"], rule_version=None)
        else:
            item.update(
                exposure_state=row.exposure_state,
                access_state=row.access_state,
                nearest_road_key=row.nearest_road_key,
                nearest_distance_m=row.nearest_distance_m,
                road_keys=row.road_keys,
                reasons=row.reasons,
                rule_version=row.rule_version,
            )
        if asset.asset_id in confirmed:
            # An officer saw that the facility is cut off. Only a person can set this state.
            item["access_state"] = "access_disrupted_confirmed"
            item["officer"] = confirmed[asset.asset_id]
            item["reasons"] = [*item["reasons"], "officer_confirmed_access_disrupted"]
        out.append(item)
    return {
        "assets": out,
        "snapshot_retrieved_at": snapshot.retrieved_at.isoformat() if snapshot else None,
        "near_m": config.exposure["near_m"],
        "frontage_m": config.exposure["frontage_m"],
        "source": source,
    }
