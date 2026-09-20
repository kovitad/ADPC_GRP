"""Seed the SYNTHETIC RP100 test case (risk R-02: start with synthetic cases).

Everything here is invented test data, labelled "synthetic" in every name and source.
It is NOT the Chiang Yuen golden case and must never be shown as a real result.
Run: python -m grp.seed synthetic-rp100
"""

from __future__ import annotations

import argparse
import hashlib
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.settings import get_settings
from core.access_models import AuditEvent, AuditResult
from core.assessment_models import Boundary, Dataset, DatasetVersion, Feature, Method
from core.db import session_scope
from core.gis import METHOD_KEY, METHOD_VERSION, REASON_CODES
from core.hazard_overlay import render_overlay
from core.storage import LocalStorage
from core.validation import canonical_sha256, centers_sha256

ADMIN_CODE = "SYN-TH-0001"
NODATA = -9999.0
# Raster grid: 0.001 degree cells from lon 100.000 and lat 15.110 (top), 120 x 120 cells.
RASTER_WEST, RASTER_NORTH, CELL, SIZE = 100.0, 15.11, 0.001, 120
BOUNDARY = {
    "type": "Polygon",
    "coordinates": [
        [[100.0, 15.0], [100.15, 15.0], [100.15, 15.1], [100.0, 15.1], [100.0, 15.0]]
    ],
}
# name, lon, lat. Points sit in cell centres so no result depends on edge rounding.
CENTERS = [
    ("Synthetic School A", 100.0105, 15.0205),
    ("Synthetic Temple B", 100.0305, 15.0805),
    ("Synthetic Hall C", 100.0455, 15.0505),
    ("Synthetic School D", 100.0605, 15.0305),
    ("Synthetic Clinic E", 100.0905, 15.0905),
    ("Synthetic Gym F", 100.0755, 15.0555),
    ("Synthetic Shelter G", 100.1305, 15.0405),
    ("Synthetic Hall H (outside district)", 100.2005, 15.0505),
]


@dataclass(frozen=True)
class SeedResult:
    changed: bool
    boundary_id: str
    hazard_version_id: str
    centers_version_id: str
    method_id: str


def flood_depth_grid() -> np.ndarray:
    """Depth in metres: 1.2 m west of lon 100.02, 0.6 m to lon 100.05, 0 m east of it,
    with a NoData patch at lon 100.070-100.080, lat 15.050-15.060."""

    grid = np.zeros((SIZE, SIZE), dtype="float32")
    lons = RASTER_WEST + (np.arange(SIZE) + 0.5) * CELL
    lats = RASTER_NORTH - (np.arange(SIZE) + 0.5) * CELL
    lon_grid, lat_grid = np.meshgrid(lons, lats)
    grid[lon_grid < 100.02] = 1.2
    grid[(lon_grid >= 100.02) & (lon_grid < 100.05)] = 0.6
    patch = (lon_grid >= 100.07) & (lon_grid < 100.08) & (lat_grid >= 15.05) & (lat_grid < 15.06)
    grid[patch] = NODATA
    return grid


def pixel_sha256(grid: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(grid, dtype="<f4").tobytes()).hexdigest()


def write_flood_raster(path: Path) -> None:
    import rasterio
    from rasterio.transform import from_origin

    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=SIZE,
        width=SIZE,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(RASTER_WEST, RASTER_NORTH, CELL, CELL),
        nodata=NODATA,
        tiled=True,
        blockxsize=64,
        blockysize=64,
        compress="deflate",
    ) as dataset:
        dataset.write(flood_depth_grid(), 1)


def ensure_overlay(session: Session, storage: LocalStorage, version: DatasetVersion) -> None:
    """Add the display-only flood overlay. It is a picture of the input, not an input, so
    adding it to metadata does not change the pinned fingerprint."""

    if (
        version.meta.get("palette") == "red_depth_v1"
        and version.meta.get("overlay_key")
        and storage.exists(str(version.meta["overlay_key"]))
    ):
        return
    overlay = render_overlay(
        storage,
        str(version.storage_key),
        f"overlays/{version.sha256[:16]}/flood-red-v1.png",
    )
    version.meta = {**version.meta, **overlay, "palette": "red_depth_v1"}
    session.flush()


def seed_synthetic_rp100(session: Session, storage: LocalStorage) -> SeedResult:
    existing = session.scalar(select(Boundary).where(Boundary.admin_code == ADMIN_CODE))
    if existing is not None:
        hazard = session.scalar(
            select(DatasetVersion)
            .join(Dataset, Dataset.id == DatasetVersion.dataset_id)
            .where(Dataset.title == "Synthetic flood depth", DatasetVersion.is_current)
        )
        centers = session.scalar(
            select(DatasetVersion)
            .join(Dataset, Dataset.id == DatasetVersion.dataset_id)
            .where(Dataset.title == "Synthetic evacuation centers", DatasetVersion.is_current)
        )
        method = session.scalar(
            select(Method).where(Method.key == METHOD_KEY, Method.version == METHOD_VERSION)
        )
        ensure_overlay(session, storage, hazard)
        return SeedResult(False, str(existing.id), str(hazard.id), str(centers.id), str(method.id))

    boundary = Boundary(
        admin_code=ADMIN_CODE,
        admin_level="district",
        name="Synthetic Test District",
        geom=BOUNDARY,
        source="synthetic test data (not a real boundary)",
        edition="unsigned-v0",
        geometry_sha256=canonical_sha256(BOUNDARY),
        is_supported=True,
    )
    hazard_dataset = Dataset(
        type="hazard", owner_kind="platform", title="Synthetic flood depth",
        provider="GRP synthetic test data",
    )
    centers_dataset = Dataset(
        type="evacuation_centers", owner_kind="platform", title="Synthetic evacuation centers",
        provider="GRP synthetic test data",
    )
    session.add_all([boundary, hazard_dataset, centers_dataset])
    session.flush()

    grid = flood_depth_grid()
    key = f"rasters/synthetic-flood/rp100/{pixel_sha256(grid)[:16]}.tif"
    with tempfile.TemporaryDirectory() as folder:
        raster_path = Path(folder) / "flood.tif"
        write_flood_raster(raster_path)
        file_sha = storage.put(key, raster_path)
    hazard_version = DatasetVersion(
        dataset_id=hazard_dataset.id,
        storage_key=key,
        sha256=file_sha,
        return_period_years=100,
        meta={
            "edition": "synthetic-v0",
            "units": "metres",
            "crs": "EPSG:4326",
            "licence": "synthetic test data",
            "pixel_sha256": pixel_sha256(grid),
        },
    )
    feature_rows = [{"name": name, "lon": lon, "lat": lat} for name, lon, lat in CENTERS]
    centers_version = DatasetVersion(
        dataset_id=centers_dataset.id,
        storage_key=None,
        sha256=centers_sha256(feature_rows),
        meta={"edition": "synthetic-v0", "crs": "EPSG:4326", "licence": "synthetic test data"},
    )
    method = Method(
        key=METHOD_KEY,
        version=METHOD_VERSION,
        reason_codes={code: {**rule, "status": str(rule["status"])}
                      for code, rule in REASON_CODES.items()},
        status="draft",
    )
    session.add_all([hazard_version, centers_version, method])
    session.flush()
    ensure_overlay(session, storage, hazard_version)
    session.add_all(
        Feature(dataset_version_id=centers_version.id, name=name, lon=lon, lat=lat,
                attributes={"type": "evacuation_center", "synthetic": True})
        for name, lon, lat in CENTERS
    )
    session.add(
        AuditEvent(
            actor_kind="system",
            action="dataset_accepted",
            target_type="dataset_version",
            target_id=str(hazard_version.id),
            new_value={"seed": "synthetic-rp100", "sha256": file_sha},
            result=AuditResult.SUCCESS,
            support_ref="grp.seed synthetic-rp100",
        )
    )
    return SeedResult(True, str(boundary.id), str(hazard_version.id), str(centers_version.id),
                      str(method.id))


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed GRP test data")
    parser.add_argument("case", choices=["synthetic-rp100"])
    parser.parse_args()
    storage = LocalStorage(get_settings().storage_root)
    with session_scope() as session:
        result = seed_synthetic_rp100(session, storage)
    print("Synthetic RP100 case " + ("seeded" if result.changed else "already seeded"))


if __name__ == "__main__":
    main()
