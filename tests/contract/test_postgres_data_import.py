"""PostgreSQL-only concurrency and PostGIS checks for the data-library foundation."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from core.access_models import AppUser, Hub
from core.data_import_jobs import (
    DatasetDefinition,
    claim_next_import,
    promote_import_version,
    request_import,
    version_id_for_import,
)
from core.dataset_readiness import DatasetReadiness
from core.import_staging import PromotedFile, PromotedImport

pytestmark = [pytest.mark.contract]


def _engine():
    path = os.environ.get("GRP_POSTGRES_TEST_URL_FILE")
    if not path or not Path(path).is_file():
        pytest.skip("GRP_POSTGRES_TEST_URL_FILE is not configured")
    return create_engine(Path(path).read_text(encoding="utf-8").strip(), pool_pre_ping=True)


def _promoted(import_id, dataset_id) -> PromotedImport:
    version_id = version_id_for_import(import_id)
    prefix = f"datasets/{dataset_id}/{version_id}"
    item = PromotedFile(
        role="source_shp",
        original_name="district.shp",
        storage_key=f"{prefix}/original/boundary.shp",
        size_bytes=10,
        sha256="a" * 64,
        metadata={},
    )
    return PromotedImport(
        files=(item,),
        total_bytes=10,
        manifest_key=f"{prefix}/manifest.json",
        manifest_sha256="b" * 64,
        manifest={"schema_version": 1},
    )


def test_postgis_boundary_columns_and_indexes_exist() -> None:
    engine = _engine()
    with engine.connect() as connection:
        columns = set(
            connection.execute(
                text(
                    "SELECT f_geometry_column FROM geometry_columns WHERE f_table_name = 'boundary'"
                )
            ).scalars()
        )
        indexes = set(
            connection.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE tablename = 'boundary' AND indexdef ILIKE '%USING gist%'"
                )
            ).scalars()
        )
    assert columns == {"geom_postgis", "geom_simplified_postgis"}
    assert indexes >= {"ix_boundary_geom_postgis", "ix_boundary_geom_simplified_postgis"}


def test_two_postgres_workers_cannot_publish_one_import_twice() -> None:
    engine = _engine()
    token = uuid4().hex
    with Session(engine) as session:
        hub = Hub(code=f"test-{token[:12]}", name="Import concurrency test")
        user = AppUser(email=f"import-{token}@example.test", is_platform_admin=True)
        session.add_all([hub, user])
        session.commit()
        request = request_import(
            session,
            hub_id=None,
            requested_by=user.id,
            idempotency_key=token,
            category="boundary",
            source_ref="administrative_boundary/district_boundary",
            support_ref="GRP-CONCURRENCY",
        )
        claim = claim_next_import(session, lease_minutes=15)
        user_id = user.id
        hub_id = hub.id

    dataset_id = uuid4()
    definition = DatasetDefinition(
        id=dataset_id,
        hub_id=None,
        type="boundary",
        owner_kind="platform",
        title=f"Concurrency {token}",
        provider="Test",
    )
    promoted = _promoted(request.import_id, dataset_id)
    barrier = Barrier(2)

    def publish():
        with Session(engine) as session:
            barrier.wait(timeout=10)
            return promote_import_version(
                session,
                claim,
                dataset=definition,
                promoted=promoted,
                readiness=DatasetReadiness.TECHNICALLY_VALID,
                importer_version="test/1",
                version_metadata={},
                report={},
            )

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = [
                future.result(timeout=20) for future in [executor.submit(publish) for _ in range(2)]
            ]
        assert sum(result is not None for result in results) == 1
        with engine.connect() as connection:
            count = connection.scalar(
                text("SELECT count(*) FROM dataset_version WHERE id = :id"),
                {"id": version_id_for_import(request.import_id)},
            )
        assert count == 1
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM data_import_job WHERE id = :id"), {"id": request.import_id}
            )
            connection.execute(
                text("DELETE FROM dataset_file WHERE dataset_version_id = :id"),
                {"id": version_id_for_import(request.import_id)},
            )
            connection.execute(
                text("DELETE FROM dataset_version WHERE dataset_id = :id"), {"id": dataset_id}
            )
            connection.execute(text("DELETE FROM dataset WHERE id = :id"), {"id": dataset_id})
            connection.execute(text("DELETE FROM app_user WHERE id = :id"), {"id": user_id})
            connection.execute(text("DELETE FROM hub WHERE id = :id"), {"id": hub_id})
