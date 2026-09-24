"""Shelter import assigns membership by geometry and reports, but does not move, conflicts."""

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from core.access_models import AppUser, Base
from core.assessment_models import Boundary, Dataset, DatasetVersion, Feature
from core.data_import_jobs import claim_next_import, request_import
from core.data_library_models import DataImportJob, DatasetFile  # noqa: F401
from core.shelter_import import (
    REQUIRED_SUFFIXES,
    SHELTER_SOURCE_REF,
    SHELTER_STEM,
    process_shelter_import,
    validate_shelter_collection,
)
from core.storage import LocalStorage


def _delivery(root: Path) -> None:
    folder = root / SHELTER_SOURCE_REF
    folder.mkdir(parents=True)
    for suffix in (*REQUIRED_SUFFIXES, ".cpg"):
        (folder / f"{SHELTER_STEM}{suffix}").write_bytes(suffix.encode())


def _fake_read(*_args, **_kwargs):
    from shapely import to_wkb
    from shapely.geometry import Point

    return (
        {"crs": "EPSG:4326", "fields": ["สถา", "สถ_1", "district_name", "จัง"]},
        None,
        [to_wkb(Point(100.25, 14.25)), to_wkb(Point(101.25, 14.25))],
        [
            ["Shelter one", "Shelter two"],
            ["Unit one", "Unit two"],
            ["เขตหนึ่ง", "เขตหนึ่ง"],
            ["จังหวัด", "จังหวัด"],
        ],
    )


def _boundary_version(session: Session) -> DatasetVersion:
    dataset = Dataset(
        id=uuid4(),
        type="boundary",
        owner_kind="platform",
        title="Boundaries",
        provider="Test",
    )
    version = DatasetVersion(
        id=uuid4(),
        dataset_id=dataset.id,
        sha256="a" * 64,
        meta={},
        readiness="technically_valid",
        is_current=False,
    )
    session.add_all([dataset, version])
    for code, name, west in (("A", "เขตหนึ่ง", 100), ("B", "เขตสอง", 101)):
        session.add(
            Boundary(
                admin_code=code,
                admin_level="district",
                name=name,
                name_th=name,
                province_name="Province",
                province_name_th="จังหวัด",
                geom={
                    "type": "Polygon",
                    "coordinates": [
                        [[west, 14], [west + 1, 14], [west + 1, 15], [west, 15], [west, 14]]
                    ],
                },
                source="Test",
                edition="2026",
                geometry_sha256="b" * 64,
                collection_version_id=version.id,
                is_supported=False,
            )
        )
    session.commit()
    return version


@pytest.mark.fast
def test_validate_shelters_reads_the_confirmed_name_and_selects_district_field(
    tmp_path: Path, monkeypatch
) -> None:
    _delivery(tmp_path)
    monkeypatch.setattr("pyogrio.raw.read", _fake_read)

    collection = validate_shelter_collection(tmp_path)

    assert len(collection.records) == 2
    assert collection.records[0].name == "Shelter one"
    assert collection.records[0].claimed_district == "เขตหนึ่ง"
    assert collection.district_field == "district_name"
    assert {item.storage_name for item in collection.source_files} == {
        "shelters.shp", "shelters.shx", "shelters.dbf", "shelters.prj", "shelters.cpg"
    }


@pytest.mark.fast
def test_process_shelters_assigns_geometry_and_reports_name_mismatch(
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
        user = AppUser(id=uuid4(), email="admin@example.test", is_platform_admin=True)
        session.add(user)
        session.commit()
        boundary_version = _boundary_version(session)
        request = request_import(
            session,
            hub_id=None,
            requested_by=user.id,
            idempotency_key="shelter-baseline",
            category="evacuation_centers",
            source_ref=SHELTER_SOURCE_REF,
            support_ref="GRP-SHELTER",
        )
        claim = claim_next_import(session, lease_minutes=15)

        version_id = process_shelter_import(
            session, storage, tmp_path / "source", claim, lease_minutes=15
        )

        job = session.get(DataImportJob, request.import_id)
        version = session.get(DatasetVersion, version_id)
        features = session.scalars(
            select(Feature).where(Feature.dataset_version_id == version_id).order_by(Feature.lon)
        ).all()
        assert job.state == "succeeded"
        assert job.report["district_name_mismatch_count"] == 1
        assert version.meta["boundary_version_id"] == str(boundary_version.id)
        assert version.meta["feature_count"] == 2
        assert version.meta["district_field"] == "district_name"
        assert version.meta["shelter_names_confirmed"] is True
        assert job.report["confirmed_fields"] == {
            "name": "สถา",
            "capacity": "รอง",
            "supporting_unit": "สถ_1",
        }
        assert job.report["labels"]["from_source_name"] == 2
        assert [feature.name for feature in features] == ["Shelter one", "Shelter two"]
        assert features[0].attributes["source_name"] == "Shelter one"
        assert features[0].attributes["district_name_mismatch"] is False
        assert features[1].attributes["district_name_mismatch"] is True
        assert features[0].boundary_id != features[1].boundary_id


@pytest.mark.fast
def test_process_shelters_accepts_its_generated_browser_quarantine(
    tmp_path: Path, monkeypatch
) -> None:
    import_id = uuid4()
    source_ref = (
        f"quarantine/browser-uploads/{import_id}/source/{SHELTER_SOURCE_REF}"
    )
    _delivery(tmp_path / "managed" / Path(source_ref).parents[1])
    monkeypatch.setattr("pyogrio.raw.read", _fake_read)
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    storage = LocalStorage(tmp_path / "managed")
    with Session(engine) as session:
        user = AppUser(id=uuid4(), email="admin@example.test", is_platform_admin=True)
        session.add(user)
        session.commit()
        _boundary_version(session)
        request_import(
            session,
            hub_id=None,
            requested_by=user.id,
            idempotency_key="shelter-browser-upload",
            category="evacuation_centers",
            source_ref=source_ref,
            support_ref="GRP-UPLOAD",
            source_mode="browser_upload",
            manifest={"original_filename": "ddpm-shelters-september.zip"},
            import_id=import_id,
        )
        claim = claim_next_import(session, lease_minutes=15)

        version_id = process_shelter_import(
            session, storage, storage.root, claim, lease_minutes=15
        )

        version = session.get(DatasetVersion, version_id)
        assert version.meta["source_mode"] == "browser_upload"
        assert version.meta["original_filename"] == "ddpm-shelters-september.zip"
        assert version.meta["feature_count"] == 2
