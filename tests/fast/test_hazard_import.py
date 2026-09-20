"""RP100 import keeps six tiles as one version and creates bounded display products."""

from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from core.access_models import AppUser, Base
from core.assessment_models import DatasetVersion
from core.data_import_jobs import claim_next_import, request_import
from core.data_library_models import DataImportJob, DatasetFile
from core.hazard_import import (
    HAZARD_SOURCE_REF,
    process_hazard_import,
    validate_hazard_collection,
)
from core.storage import LocalStorage


def _delivery(root: Path) -> None:
    import numpy as np
    import rasterio
    from rasterio.transform import from_bounds

    folder = root / HAZARD_SOURCE_REF
    folder.mkdir(parents=True)
    index = 0
    for row in range(3):
        for column in range(2):
            index += 1
            west, east = float(column), float(column + 1)
            south, north = float(2 - row), float(3 - row)
            data = np.full((10, 10), index / 2, dtype="float32")
            data[0, 0] = -9999
            with rasterio.open(
                folder / f"tile-{index}.tif",
                "w",
                driver="GTiff",
                width=10,
                height=10,
                count=1,
                dtype="float32",
                crs="EPSG:4326",
                transform=from_bounds(west, south, east, north, 10, 10),
                nodata=-9999,
            ) as raster:
                raster.write(data, 1)


@pytest.mark.fast
def test_validate_hazard_builds_stable_six_tile_manifest(tmp_path: Path) -> None:
    _delivery(tmp_path)

    collection = validate_hazard_collection(tmp_path)

    assert len(collection.tiles) == 6
    assert collection.bounds == (0.0, 0.0, 2.0, 3.0)
    assert [item.role for item in collection.source_files] == [
        f"source_tile_{index:02d}" for index in range(1, 7)
    ]


@pytest.mark.fast
def test_process_hazard_publishes_originals_cogs_and_preview(tmp_path: Path) -> None:
    _delivery(tmp_path / "source")
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    storage = LocalStorage(tmp_path / "managed")
    with Session(engine) as session:
        user = AppUser(email="admin@example.test", is_platform_admin=True)
        session.add(user)
        session.commit()
        request = request_import(
            session,
            hub_id=None,
            requested_by=user.id,
            idempotency_key="hazard-baseline",
            category="hazard",
            source_ref=HAZARD_SOURCE_REF,
            support_ref="GRP-HAZARD",
        )
        claim = claim_next_import(session, lease_minutes=15)

        version_id = process_hazard_import(
            session, storage, tmp_path / "source", claim, lease_minutes=15
        )

        job = session.get(DataImportJob, request.import_id)
        version = session.get(DatasetVersion, version_id)
        files = session.scalars(
            select(DatasetFile).where(DatasetFile.dataset_version_id == version_id)
        ).all()
        assert job.state == "succeeded"
        assert version.readiness == "waiting_for_method"
        assert version.return_period_years == 100
        assert version.meta["tile_count"] == 6
        assert storage.exists(version.meta["overlay_key"])
        assert len(files) == 13
