"""Worker import for the six-tile RP100 flood-depth baseline and map preview."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.data_import_jobs import (
    DatasetDefinition,
    ImportClaim,
    promote_import_version,
    renew_import_lease,
    version_id_for_import,
)
from core.data_library_models import DataImportJob, DatasetFile
from core.dataset_readiness import DatasetReadiness
from core.hazard_overlay import colourise
from core.import_staging import (
    SourceFile,
    cleanup_import_staging,
    promote_staged_import,
    stage_import_files,
)
from core.storage import Storage

HAZARD_SOURCE_REF = "floods/flood_depth_rp100"
EXPECTED_TILE_COUNT = 6
RETURN_PERIOD_YEARS = 100
IMPORTER_VERSION = "grp-hazard-rp100/1"
PLATFORM_HAZARD_DATASET_ID = uuid5(
    NAMESPACE_URL, "grp:platform-dataset:thailand-flood-depth-rp100"
)
PREVIEW_WIDTH = 1200


class HazardImportError(ValueError):
    """The RP100 delivery failed a safe technical validation."""


@dataclass(frozen=True)
class HazardTile:
    path: Path
    role: str
    bounds: tuple[float, float, float, float]
    resolution: tuple[float, float]
    nodata: float | None
    width: int
    height: int
    dtype: str


@dataclass(frozen=True)
class ValidatedHazardCollection:
    tiles: tuple[HazardTile, ...]
    source_files: tuple[SourceFile, ...]
    bounds: tuple[float, float, float, float]


def hazard_source_available(root: Path) -> bool:
    folder = root / HAZARD_SOURCE_REF
    return folder.is_dir() and len(list(folder.glob("*.tif"))) == EXPECTED_TILE_COUNT


def validate_hazard_collection(root: Path) -> ValidatedHazardCollection:
    """Validate one deterministic six-file manifest without reading whole rasters."""

    import rasterio

    folder = root / HAZARD_SOURCE_REF
    paths = sorted(folder.glob("*.tif"), key=lambda path: path.name)
    if len(paths) != EXPECTED_TILE_COUNT:
        raise HazardImportError("RP100 delivery must contain exactly six GeoTIFF tiles")
    tiles: list[HazardTile] = []
    files: list[SourceFile] = []
    resolutions: set[tuple[float, float]] = set()
    for index, path in enumerate(paths):
        try:
            with rasterio.open(path) as raster:
                if raster.crs is None or raster.crs.to_epsg() != 4326:
                    raise HazardImportError("Every RP100 tile must declare EPSG:4326")
                if raster.count != 1:
                    raise HazardImportError("Every RP100 tile must contain one depth band")
                resolution = (round(abs(raster.res[0]), 12), round(abs(raster.res[1]), 12))
                resolutions.add(resolution)
                bounds = tuple(float(value) for value in raster.bounds)
                tile = HazardTile(
                    path=path,
                    role=f"source_tile_{index + 1:02d}",
                    bounds=bounds,
                    resolution=resolution,
                    nodata=float(raster.nodata) if raster.nodata is not None else None,
                    width=raster.width,
                    height=raster.height,
                    dtype=str(raster.dtypes[0]),
                )
        except HazardImportError:
            raise
        except Exception as exc:  # noqa: BLE001 - safe worker finding
            raise HazardImportError("An RP100 GeoTIFF could not be read") from exc
        tiles.append(tile)
        files.append(
            SourceFile(
                role=tile.role,
                path=path,
                storage_name=f"tile-{index + 1:02d}.tif",
                metadata={
                    "source_filename": path.name,
                    "bounds": list(tile.bounds),
                    "resolution": list(tile.resolution),
                    "nodata": tile.nodata,
                    "width": tile.width,
                    "height": tile.height,
                    "dtype": tile.dtype,
                    "manifest_order": index,
                },
            )
        )
    if len(resolutions) != 1:
        raise HazardImportError("RP100 tiles do not share one pixel resolution")
    west = min(tile.bounds[0] for tile in tiles)
    south = min(tile.bounds[1] for tile in tiles)
    east = max(tile.bounds[2] for tile in tiles)
    north = max(tile.bounds[3] for tile in tiles)
    # The delivery is a 2 x 3 regular grid. Check union area as well as the envelope so an overlap
    # and a same-sized gap cannot cancel each other out.
    from shapely.geometry import box
    from shapely.ops import unary_union

    tile_area = sum(
        (tile.bounds[2] - tile.bounds[0]) * (tile.bounds[3] - tile.bounds[1])
        for tile in tiles
    )
    envelope_area = (east - west) * (north - south)
    union_area = unary_union([box(*tile.bounds) for tile in tiles]).area
    tolerance = envelope_area * 1e-6
    if abs(tile_area - union_area) > tolerance or abs(union_area - envelope_area) > tolerance:
        raise HazardImportError("RP100 tiles contain an unintended overlap or gap")
    return ValidatedHazardCollection(tuple(tiles), tuple(files), (west, south, east, north))


def _build_map_preview(collection: ValidatedHazardCollection, destination: Path) -> None:
    """Reproject tiles into a bounded national RGBA PNG; never allocate a full source raster."""

    import numpy as np
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.transform import from_bounds
    from rasterio.warp import reproject

    west, south, east, north = collection.bounds
    height = max(1, round(PREVIEW_WIDTH * (north - south) / (east - west)))
    depth = np.zeros((height, PREVIEW_WIDTH), dtype="float32")
    valid = np.zeros((height, PREVIEW_WIDTH), dtype=bool)
    transform = from_bounds(west, south, east, north, PREVIEW_WIDTH, height)
    for tile in collection.tiles:
        with rasterio.open(tile.path) as source:
            target = np.full((height, PREVIEW_WIDTH), np.nan, dtype="float32")
            reproject(
                source=rasterio.band(source, 1),
                destination=target,
                src_transform=source.transform,
                src_crs=source.crs,
                src_nodata=source.nodata,
                dst_transform=transform,
                dst_crs="EPSG:4326",
                dst_nodata=np.nan,
                resampling=Resampling.nearest,
            )
            tile_valid = np.isfinite(target)
            depth[tile_valid] = target[tile_valid]
            valid[tile_valid] = True
    rgba = colourise(depth, ~valid)
    with rasterio.open(
        destination,
        "w",
        driver="PNG",
        width=PREVIEW_WIDTH,
        height=height,
        count=4,
        dtype="uint8",
    ) as image:
        image.write(rgba)


def _build_cog(source: Path, destination: Path) -> None:
    """Create one bounded-memory Cloud Optimized GeoTIFF with internal overviews."""

    import rasterio
    from rasterio.shutil import copy as raster_copy

    with rasterio.Env(GDAL_CACHEMAX=256):
        raster_copy(
            source,
            destination,
            driver="COG",
            compress="DEFLATE",
            blocksize=512,
            overview_resampling="nearest",
            BIGTIFF="IF_SAFER",
        )


def process_hazard_import(
    session: Session,
    storage: Storage,
    source_root: Path,
    claim: ImportClaim,
    *,
    lease_minutes: int,
) -> UUID | None:
    """Publish six originals, six COGs and one bounded map preview as one RP100 version."""

    job = session.scalar(select(DataImportJob).where(DataImportJob.id == claim.import_id))
    if job is None or job.category != "hazard" or job.source_ref != HAZARD_SOURCE_REF:
        raise HazardImportError("Import job does not reference the accepted RP100 source")
    collection = validate_hazard_collection(source_root)
    if not renew_import_lease(session, claim, lease_minutes=lease_minutes, progress=15):
        return None
    staged = stage_import_files(
        storage, claim, source_root=source_root, files=list(collection.source_files)
    )
    version_id = version_id_for_import(claim.import_id)
    prefix = f"datasets/{PLATFORM_HAZARD_DATASET_ID}/{version_id}"
    working_files: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory() as folder_name:
        folder = Path(folder_name)
        staged_by_name = {item.original_name: item for item in staged.files}
        pinned_tiles: list[HazardTile] = []
        for index, tile in enumerate(collection.tiles):
            pinned_source = folder / f"source-{index + 1:02d}.tif"
            storage.get(staged_by_name[tile.path.name].staging_key, pinned_source)
            pinned_tile = replace(tile, path=pinned_source)
            pinned_tiles.append(pinned_tile)
            cog = folder / f"tile-{index + 1:02d}.tif"
            _build_cog(pinned_source, cog)
            key = f"{prefix}/working/tile-{index + 1:02d}.tif"
            digest = storage.put(key, cog)
            working_files.append(
                {
                    "role": f"working_cog_{index + 1:02d}",
                    "original_name": tile.path.name,
                    "storage_key": key,
                    "sha256": digest,
                    "size_bytes": cog.stat().st_size,
                    "metadata": {"source_filename": tile.path.name},
                }
            )
            progress = 20 + (index + 1) * 8
            if not renew_import_lease(
                session, claim, lease_minutes=lease_minutes, progress=progress
            ):
                return None
        preview = folder / "flood-depth-rp100.png"
        pinned_collection = replace(collection, tiles=tuple(pinned_tiles))
        _build_map_preview(pinned_collection, preview)
        preview_key = f"{prefix}/previews/flood-depth-rp100.png"
        preview_digest = storage.put(preview_key, preview)
        working_files.append(
            {
                "role": "map_preview_png",
                "original_name": preview.name,
                "storage_key": preview_key,
                "sha256": preview_digest,
                "size_bytes": preview.stat().st_size,
                "metadata": {"bounds": list(collection.bounds)},
            }
        )
    if not renew_import_lease(session, claim, lease_minutes=lease_minutes, progress=80):
        return None
    promoted = promote_staged_import(
        storage,
        staged,
        dataset_id=PLATFORM_HAZARD_DATASET_ID,
        version_id=version_id,
    )

    def materialize(session: Session, published_version_id: UUID) -> None:
        if published_version_id != version_id:
            raise ValueError("Hazard materialization version changed")
        session.add_all(
            [
                DatasetFile(
                    dataset_version_id=version_id,
                    role=str(item["role"]),
                    original_name=str(item["original_name"]),
                    storage_key=str(item["storage_key"]),
                    sha256=str(item["sha256"]),
                    size_bytes=int(item["size_bytes"]),
                    file_metadata=dict(item["metadata"]),
                )
                for item in working_files
            ]
        )

    published = promote_import_version(
        session,
        claim,
        dataset=DatasetDefinition(
            id=PLATFORM_HAZARD_DATASET_ID,
            hub_id=None,
            type="hazard",
            owner_kind="platform",
            title="Thailand flood depth · 100-year",
            provider="ADPC Data Science delivery",
        ),
        promoted=promoted,
        readiness=DatasetReadiness.WAITING_FOR_METHOD,
        importer_version=IMPORTER_VERSION,
        return_period_years=RETURN_PERIOD_YEARS,
        version_metadata={
            "crs": "EPSG:4326",
            "tile_count": len(collection.tiles),
            "source_ref": HAZARD_SOURCE_REF,
            "overlay_key": f"{prefix}/previews/flood-depth-rp100.png",
            "overlay_sha256": working_files[-1]["sha256"],
            "overlay_bounds": [
                [collection.bounds[1], collection.bounds[0]],
                [collection.bounds[3], collection.bounds[2]],
            ],
            "map_preview": True,
            "no_data_decision": "pending_DEP_05",
        },
        report={
            "message": (
                "Six RP100 tiles were registered as one version with COGs and a map preview."
            ),
            "tile_count": len(collection.tiles),
            "working_cog_count": len(collection.tiles),
            "readiness": DatasetReadiness.WAITING_FOR_METHOD.value,
            "blocking_dependency": "DEP-05",
        },
        materialize=materialize,
    )
    if published is not None:
        cleanup_import_staging(storage, claim)
    return published
