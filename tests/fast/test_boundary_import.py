"""The boundary loader validates the complete collection before atomic publication."""

from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from core.access_models import AppUser, Base, Hub
from core.assessment_models import Boundary, DatasetVersion
from core.boundary_import import (
    BOUNDARY_SOURCE_REF,
    BOUNDARY_STEM,
    BoundaryImportError,
    process_boundary_import,
    validate_boundary_collection,
)
from core.data_import_jobs import claim_next_import, request_import
from core.data_library_models import DataImportJob, DatasetFile  # noqa: F401
from core.storage import LocalStorage


def _delivery(root: Path) -> None:
    folder = root / BOUNDARY_SOURCE_REF
    folder.mkdir(parents=True)
    for suffix in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
        (folder / f"{BOUNDARY_STEM}{suffix}").write_bytes(suffix.encode())


def _fake_read(*_args, **_kwargs):
    from shapely import to_wkb
    from shapely.geometry import Polygon

    meta = {
        "crs": "EPSG:4326",
        "geometry_type": "Polygon",
        "fields": [
            "ADMIN_ID2",
            "NAME1",
            "NAME_ENG1",
            "NAME2",
            "NAME_ENG2",
            "VERSION",
        ],
    }
    geometries = [
        to_wkb(Polygon([(100, 14), (101, 14), (101, 15), (100, 14)])),
        to_wkb(Polygon([(101, 14), (102, 14), (102, 15), (101, 14)])),
    ]
    fields = [
        ["TH1001", "TH1002"],
        ["จังหวัดหนึ่ง", "จังหวัดสอง"],
        ["Province One", "Province Two"],
        ["อำเภอหนึ่ง", "อำเภอสอง"],
        ["District One", "District Two"],
        ["2026", "2026"],
    ]
    return meta, None, geometries, fields


@pytest.mark.fast
def test_validate_boundary_collection_checks_attributes_and_geometry(
    tmp_path: Path, monkeypatch
) -> None:
    _delivery(tmp_path)
    monkeypatch.setattr("pyogrio.raw.read", _fake_read)

    collection = validate_boundary_collection(tmp_path)

    assert len(collection.records) == 2
    assert collection.edition == "2026"
    assert collection.records[0].admin_code == "TH1001"
    assert collection.records[0].geometry_sha256
    assert {item.storage_name for item in collection.source_files} == {
        "boundary.shp",
        "boundary.shx",
        "boundary.dbf",
        "boundary.prj",
        "boundary.cpg",
    }


@pytest.mark.fast
def test_validate_boundary_collection_rejects_duplicate_admin_codes(
    tmp_path: Path, monkeypatch
) -> None:
    _delivery(tmp_path)

    def duplicate_read(*args, **kwargs):
        meta, extra, geometries, fields = _fake_read(*args, **kwargs)
        fields[0][1] = fields[0][0]
        return meta, extra, geometries, fields

    monkeypatch.setattr("pyogrio.raw.read", duplicate_read)

    with pytest.raises(BoundaryImportError, match="not unique"):
        validate_boundary_collection(tmp_path)


@pytest.mark.fast
def test_process_boundary_import_publishes_files_version_and_features_together(
    tmp_path: Path, monkeypatch
) -> None:
    _delivery(tmp_path / "source")
    monkeypatch.setattr("pyogrio.raw.read", _fake_read)
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    storage = LocalStorage(tmp_path / "managed")
    with Session(engine) as session:
        hub = Hub(code="adpc", name="ADPC")
        user = AppUser(email="admin@example.test", is_platform_admin=True)
        session.add_all([hub, user])
        session.commit()
        request = request_import(
            session,
            hub_id=None,
            requested_by=user.id,
            idempotency_key="boundary-baseline",
            category="boundary",
            source_ref=BOUNDARY_SOURCE_REF,
            support_ref="GRP-BOUNDARY",
        )
        claim = claim_next_import(session, lease_minutes=15)

        version_id = process_boundary_import(
            session,
            storage,
            tmp_path / "source",
            claim,
            lease_minutes=15,
        )

        job = session.get(DataImportJob, request.import_id)
        version = session.get(DatasetVersion, version_id)
        boundaries = session.scalars(
            select(Boundary).where(Boundary.collection_version_id == version_id)
        ).all()
        files = session.scalars(
            select(DatasetFile).where(DatasetFile.dataset_version_id == version_id)
        ).all()
        assert job.state == "succeeded"
        assert version.readiness == "technically_valid"
        assert version.meta["feature_count"] == 2
        assert len(boundaries) == 2
        assert not any(item.is_supported for item in boundaries)
        assert len(files) == 5
        assert storage.exists(version.storage_key)
