"""DDPM evacuation centres in the flood pilot's facility check (ADR-0056, step 4).

The pilot's facility list was OpenStreetMap only. Planners need "which evacuation centres have
flooding reported nearby", so the current DDPM shelter version from the GRP data library is added
for the demo districts. It is read from the database, never copied into the repository, because
baseline source data stays out of Git (ADR-0022).

The same exposure rules apply (ADR-0040): "flooding reported nearby", never "flooded", and access
is never assumed.

Two kinds of record are left out:

- synthetic test data (provider "GRP synthetic test data"), which is never real;
- records the importer flagged as ``district_name_mismatch``: DDPM named one place, but the
  coordinates fall in another, so their location cannot be trusted.

On 4 October 2026 this left **no DDPM centre inside Bangkok**. DDPM's delivery names 75
provinces and not Bangkok (probably because BMA runs disaster work in the capital; to confirm
with DDPM). The 8 points that fell inside
Bangkok were all flagged records from other provinces (Phetchaburi, Samut Sakhon, Chachoengsao,
Samut Prakan and Ubon Ratchathani) whose coordinates land in Bangkok.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.assessment_models import Boundary, Dataset, DatasetVersion, Feature
from core.flood_evidence.assets import EVACUATION_CENTRE, Asset, asset_registry
from core.flood_evidence.config import PilotConfig

SHELTER_DATASET_TYPE = "evacuation_centers"
SYNTHETIC_PROVIDER = "grp synthetic test data"
SOURCE_LABEL = "DDPM evacuation centre (GRP data library)"


def ddpm_shelters(session: Session, config: PilotConfig) -> tuple[Asset, ...]:
    """Current platform-baseline shelters inside the pilot's demo districts."""

    codes = set(config.demo_corridor.get("areas") or [])
    if config.base_id != "bangkok" or not codes:
        return ()
    rows = session.execute(
        select(Feature, Boundary.admin_code, DatasetVersion.id, Dataset.provider)
        .join(DatasetVersion, DatasetVersion.id == Feature.dataset_version_id)
        .join(Dataset, Dataset.id == DatasetVersion.dataset_id)
        .join(Boundary, Boundary.id == Feature.boundary_id)
        .where(
            Dataset.type == SHELTER_DATASET_TYPE,
            Dataset.hub_id.is_(None),
            DatasetVersion.is_current.is_(True),
            Feature.lon.is_not(None),
            Feature.lat.is_not(None),
        )
        .order_by(Feature.id)
    ).all()
    out = []
    for feature, admin_code, version_id, provider in rows:
        district = str(admin_code or "")[:4]
        if district not in codes:
            continue
        if str(provider or "").casefold() == SYNTHETIC_PROVIDER:
            continue
        if (feature.attributes or {}).get("district_name_mismatch"):
            continue  # the coordinates contradict the place DDPM named
        out.append(Asset(
            asset_id=f"ddpm:{feature.id}",
            asset_type=EVACUATION_CENTRE,
            name=feature.name or "",
            name_en="",
            lat=float(feature.lat),
            lon=float(feature.lon),
            district_code=district,
            source=f"{SOURCE_LABEL}, version {str(version_id)[:8]}",
        ))
    return tuple(out)


def pilot_assets(session: Session, config: PilotConfig) -> tuple[tuple[Asset, ...], dict[str, Any]]:
    """OSM facilities plus DDPM evacuation centres, and a description of both sources."""

    osm, source = asset_registry(config.base_id)
    shelters = ddpm_shelters(session, config)
    return osm + shelters, {
        **source,
        "ddpm_evacuation_centres": len(shelters),
        "ddpm_source": SOURCE_LABEL if shelters else None,
    }
