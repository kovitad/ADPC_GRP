"""Data-library import jobs are idempotent and fenced against stale workers (ADR-0008)."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from core.access_models import AppUser, Base, Hub
from core.assessment_models import Dataset, DatasetVersion
from core.data_import_jobs import (
    DatasetDefinition,
    claim_next_import,
    fail_import,
    finish_import,
    promote_import_version,
    renew_import_lease,
    request_import,
    version_id_for_import,
)
from core.data_library_models import DataImportJob, DatasetFile
from core.dataset_readiness import DatasetReadiness
from core.import_staging import PromotedFile, PromotedImport
from core.models import AssessmentState


@pytest.fixture
def world():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        hub = Hub(code="adpc", name="ADPC")
        user = AppUser(email="admin@example.test", is_platform_admin=True)
        session.add_all([hub, user])
        session.commit()
        yield session, hub.id, user.id


def _request(session: Session, hub_id, user_id, key="import-1"):
    return request_import(
        session,
        hub_id=hub_id,
        requested_by=user_id,
        idempotency_key=key,
        category="boundary",
        source_ref="administrative_boundary/district_boundary",
        support_ref="GRP-IMPORT",
    )


@pytest.mark.fast
def test_request_retry_reuses_one_import(world) -> None:
    session, hub_id, user_id = world

    first = _request(session, hub_id, user_id)
    retry = _request(session, hub_id, user_id)

    assert first.reused is False
    assert retry.reused is True
    assert retry.import_id == first.import_id


@pytest.mark.fast
def test_running_import_renews_its_lease_and_progress(world) -> None:
    session, hub_id, user_id = world
    asked = _request(session, hub_id, user_id)
    now = datetime(2026, 9, 19, tzinfo=UTC)
    claim = claim_next_import(session, lease_minutes=15, now=now)

    renewed = renew_import_lease(
        session, claim, lease_minutes=15, progress=40, now=now + timedelta(minutes=5)
    )

    job = session.get(DataImportJob, asked.import_id)
    assert renewed is True
    assert job.progress == 40
    assert job.lease_until.replace(tzinfo=UTC) == now + timedelta(minutes=20)


@pytest.mark.fast
def test_reclaimed_job_fences_the_stale_worker(world) -> None:
    session, hub_id, user_id = world
    _request(session, hub_id, user_id)
    now = datetime(2026, 9, 19, tzinfo=UTC)
    stale = claim_next_import(session, lease_minutes=1, now=now)
    current = claim_next_import(session, lease_minutes=15, now=now + timedelta(minutes=2))

    assert current.import_id == stale.import_id
    assert current.attempt == stale.attempt + 1
    assert (
        renew_import_lease(
            session,
            stale,
            lease_minutes=15,
            progress=90,
            now=now + timedelta(minutes=2),
        )
        is False
    )


@pytest.mark.fast
def test_only_current_attempt_can_finalize_once(world) -> None:
    session, hub_id, user_id = world
    asked = _request(session, hub_id, user_id)
    now = datetime(2026, 9, 19, tzinfo=UTC)
    claim = claim_next_import(session, lease_minutes=15, now=now)
    dataset = Dataset(
        hub_id=hub_id,
        type="evacuation_centers",
        owner_kind="hub_local",
        title="Test shelters",
        provider="Test",
    )
    session.add(dataset)
    session.flush()
    version = DatasetVersion(
        dataset_id=dataset.id,
        sha256="a" * 64,
        meta={},
        readiness="technically_valid",
        is_current=False,
    )
    session.add(version)
    session.commit()

    assert finish_import(
        session,
        claim,
        dataset_version_id=version.id,
        report={"message": "validated"},
        now=now + timedelta(minutes=1),
    )
    assert not finish_import(
        session,
        claim,
        dataset_version_id=version.id,
        report={"message": "duplicate"},
        now=now + timedelta(minutes=1),
    )
    job = session.get(DataImportJob, asked.import_id)
    assert job.state == AssessmentState.SUCCEEDED
    assert job.progress == 100
    assert job.dataset_version_id == version.id


def _promoted(import_id, dataset_id) -> PromotedImport:
    version_id = version_id_for_import(import_id)
    key = f"datasets/{dataset_id}/{version_id}/original/boundary.shp"
    file = PromotedFile(
        role="source_shp",
        original_name="district.shp",
        storage_key=key,
        size_bytes=12,
        sha256="b" * 64,
        metadata={"geometry": "polygon"},
    )
    manifest = {
        "schema_version": 1,
        "files": [{"role": file.role, "sha256": file.sha256}],
    }
    return PromotedImport(
        files=(file,),
        total_bytes=12,
        manifest_key=key.rsplit("/original/", 1)[0] + "/manifest.json",
        manifest_sha256="c" * 64,
        manifest=manifest,
    )


@pytest.mark.fast
def test_promotion_atomically_creates_version_files_and_job_result(world) -> None:
    session, hub_id, user_id = world
    asked = _request(session, hub_id, user_id)
    now = datetime(2026, 9, 19, tzinfo=UTC)
    claim = claim_next_import(session, lease_minutes=15, now=now)
    dataset_id = uuid4()

    version_id = promote_import_version(
        session,
        claim,
        dataset=DatasetDefinition(
            id=dataset_id,
            hub_id=None,
            type="boundary",
            owner_kind="platform",
            title="Thailand district boundaries",
            provider="Data Science delivery",
        ),
        promoted=_promoted(asked.import_id, dataset_id),
        readiness=DatasetReadiness.TECHNICALLY_VALID,
        importer_version="grp-boundary/1",
        version_metadata={"feature_count": 928},
        report={"message": "validated"},
        now=now + timedelta(minutes=1),
    )

    job = session.get(DataImportJob, asked.import_id)
    version = session.get(DatasetVersion, version_id)
    files = session.query(DatasetFile).filter_by(dataset_version_id=version_id).all()
    assert version_id == version_id_for_import(asked.import_id)
    assert job.state == AssessmentState.SUCCEEDED
    assert job.dataset_version_id == version_id
    assert version.readiness == DatasetReadiness.TECHNICALLY_VALID
    assert version.is_current is False
    assert version.meta["feature_count"] == 928
    assert len(files) == 1
    assert files[0].sha256 == "b" * 64


@pytest.mark.fast
def test_stale_attempt_cannot_publish_promoted_files_or_fail_reclaimed_job(world) -> None:
    session, hub_id, user_id = world
    asked = _request(session, hub_id, user_id)
    now = datetime(2026, 9, 19, tzinfo=UTC)
    stale = claim_next_import(session, lease_minutes=1, now=now)
    current = claim_next_import(session, lease_minutes=15, now=now + timedelta(minutes=2))
    dataset_id = uuid4()
    definition = DatasetDefinition(
        id=dataset_id,
        hub_id=None,
        type="boundary",
        owner_kind="platform",
        title="Thailand district boundaries",
        provider="Data Science delivery",
    )

    assert (
        promote_import_version(
            session,
            stale,
            dataset=definition,
            promoted=_promoted(asked.import_id, dataset_id),
            readiness=DatasetReadiness.TECHNICALLY_VALID,
            importer_version="grp-boundary/1",
            version_metadata={},
            report={},
            now=now + timedelta(minutes=2),
        )
        is None
    )
    assert not fail_import(
        session,
        stale,
        error_code="IMPORT_FAILED",
        report={},
        now=now + timedelta(minutes=2),
    )
    assert session.get(DatasetVersion, version_id_for_import(asked.import_id)) is None
    assert session.get(DataImportJob, asked.import_id).attempt == current.attempt


@pytest.mark.fast
def test_materializer_failure_rolls_back_complete_version(world) -> None:
    session, hub_id, user_id = world
    asked = _request(session, hub_id, user_id)
    claim = claim_next_import(session, lease_minutes=15)
    dataset_id = uuid4()

    def reject_materialization(_session, _version_id) -> None:
        raise ValueError("invalid staged features")

    with pytest.raises(ValueError, match="invalid staged features"):
        promote_import_version(
            session,
            claim,
            dataset=DatasetDefinition(
                id=dataset_id,
                hub_id=None,
                type="boundary",
                owner_kind="platform",
                title="Thailand district boundaries",
                provider="Data Science delivery",
            ),
            promoted=_promoted(asked.import_id, dataset_id),
            readiness=DatasetReadiness.TECHNICALLY_VALID,
            importer_version="grp-boundary/1",
            version_metadata={},
            report={},
            materialize=reject_materialization,
        )

    assert session.get(DatasetVersion, version_id_for_import(asked.import_id)) is None
    assert session.get(Dataset, dataset_id) is None
    assert session.get(DataImportJob, asked.import_id).state == AssessmentState.RUNNING
