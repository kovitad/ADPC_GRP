"""Queue and lease controls for data-library imports (ADR-0008).

A worker attempt number acts as its fencing token: after a lease expires and another worker claims
the job, the stale worker can neither renew nor finalize that job.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.assessment_models import Dataset, DatasetVersion
from core.data_library_models import DataImportJob, DatasetFile
from core.dataset_readiness import DatasetReadiness
from core.models import AssessmentState

if TYPE_CHECKING:
    from core.import_staging import PromotedImport


@dataclass(frozen=True)
class ImportRequest:
    import_id: UUID
    state: str
    reused: bool


@dataclass(frozen=True)
class ImportClaim:
    import_id: UUID
    attempt: int


@dataclass(frozen=True)
class DatasetDefinition:
    id: UUID
    hub_id: UUID | None
    type: str
    owner_kind: str
    title: str
    provider: str


def version_id_for_import(import_id: UUID) -> UUID:
    """Return a deterministic version ID so storage promotion is retry-safe."""

    return uuid5(NAMESPACE_URL, f"grp:data-import:{import_id}:dataset-version")


def request_import(
    session: Session,
    *,
    hub_id: UUID | None,
    requested_by: UUID,
    idempotency_key: str,
    category: str,
    source_ref: str,
    support_ref: str,
    source_mode: str = "source_folder",
    manifest: dict[str, object] | None = None,
    import_id: UUID | None = None,
) -> ImportRequest:
    """Queue once for one person/idempotency key; retries return the existing job."""

    existing = session.scalar(
        select(DataImportJob).where(
            DataImportJob.requested_by == requested_by,
            DataImportJob.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        return ImportRequest(existing.id, existing.state, True)
    job = DataImportJob(
        **({"id": import_id} if import_id is not None else {}),
        hub_id=hub_id,
        requested_by=requested_by,
        idempotency_key=idempotency_key,
        category=category,
        source_mode=source_mode,
        source_ref=source_ref,
        state=AssessmentState.QUEUED,
        support_ref=support_ref,
        manifest=dict(manifest or {}),
    )
    session.add(job)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(
            select(DataImportJob).where(
                DataImportJob.requested_by == requested_by,
                DataImportJob.idempotency_key == idempotency_key,
            )
        )
        if existing is None:
            raise
        return ImportRequest(existing.id, existing.state, True)
    return ImportRequest(job.id, job.state, False)


def claim_next_import(
    session: Session, *, lease_minutes: int, now: datetime | None = None
) -> ImportClaim | None:
    """Claim a queued or expired job and return its fencing attempt."""

    now = now or datetime.now(UTC)
    job = session.scalar(
        select(DataImportJob)
        .where(
            or_(
                DataImportJob.state == AssessmentState.QUEUED,
                (DataImportJob.state == AssessmentState.RUNNING)
                & (DataImportJob.lease_until < now),
            )
        )
        .order_by(DataImportJob.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if job is None:
        return None
    job.state = AssessmentState.RUNNING
    job.attempt += 1
    job.lease_until = now + timedelta(minutes=lease_minutes)
    job.started_at = job.started_at or now
    session.commit()
    return ImportClaim(job.id, job.attempt)


def renew_import_lease(
    session: Session,
    claim: ImportClaim,
    *,
    lease_minutes: int,
    progress: int,
    now: datetime | None = None,
) -> bool:
    """Renew only the current attempt. A stale worker's fencing token fails."""

    now = now or datetime.now(UTC)
    result = session.execute(
        update(DataImportJob)
        .where(
            DataImportJob.id == claim.import_id,
            DataImportJob.state == AssessmentState.RUNNING,
            DataImportJob.attempt == claim.attempt,
            DataImportJob.lease_until >= now,
        )
        .values(
            lease_until=now + timedelta(minutes=lease_minutes),
            progress=max(0, min(99, progress)),
        )
        .execution_options(synchronize_session=False)
    )
    session.commit()
    return bool(result.rowcount)


def promote_import_version(
    session: Session,
    claim: ImportClaim,
    *,
    dataset: DatasetDefinition,
    promoted: PromotedImport,
    readiness: DatasetReadiness,
    importer_version: str,
    version_metadata: dict[str, object],
    report: dict[str, object],
    return_period_years: int | None = None,
    materialize: Callable[[Session, UUID], None] | None = None,
    now: datetime | None = None,
) -> UUID | None:
    """Atomically expose one immutable version and finalize its currently leased job.

    Storage promotion happens first and is idempotent under the deterministic version ID. This
    transaction then creates every database record and marks the job succeeded together. Therefore
    no partial version is selectable after a rollback, and a stale attempt cannot publish it.
    """

    now = now or datetime.now(UTC)
    version_id = version_id_for_import(claim.import_id)
    expected_prefix = f"datasets/{dataset.id}/{version_id}/"
    if promoted.manifest_key != f"{expected_prefix}manifest.json" or any(
        not item.storage_key.startswith(f"{expected_prefix}original/") for item in promoted.files
    ):
        raise ValueError("Promoted storage keys do not match the dataset and import version")
    if (dataset.owner_kind == "platform" and dataset.hub_id is not None) or (
        dataset.owner_kind == "hub_local" and dataset.hub_id is None
    ):
        raise ValueError("Dataset owner and Hub scope are inconsistent")
    job = session.scalar(
        select(DataImportJob)
        .where(
            DataImportJob.id == claim.import_id,
            DataImportJob.state == AssessmentState.RUNNING,
            DataImportJob.attempt == claim.attempt,
            DataImportJob.lease_until >= now,
            DataImportJob.dataset_version_id.is_(None),
        )
        .with_for_update()
    )
    if job is None:
        session.rollback()
        return None

    existing_dataset = session.get(Dataset, dataset.id)
    if existing_dataset is None:
        session.add(
            Dataset(
                id=dataset.id,
                hub_id=dataset.hub_id,
                type=dataset.type,
                owner_kind=dataset.owner_kind,
                title=dataset.title,
                provider=dataset.provider,
            )
        )
    elif (
        existing_dataset.hub_id,
        existing_dataset.type,
        existing_dataset.owner_kind,
        existing_dataset.title,
        existing_dataset.provider,
    ) != (
        dataset.hub_id,
        dataset.type,
        dataset.owner_kind,
        dataset.title,
        dataset.provider,
    ):
        session.rollback()
        raise ValueError("Dataset identity conflicts with the existing data-library record")

    session.add(
        DatasetVersion(
            id=version_id,
            dataset_id=dataset.id,
            storage_key=promoted.manifest_key,
            sha256=promoted.manifest_sha256,
            return_period_years=return_period_years,
            meta=dict(version_metadata),
            is_current=False,
            readiness=readiness.value,
            importer_version=importer_version,
        )
    )
    session.add_all(
        [
            DatasetFile(
                dataset_version_id=version_id,
                role=item.role,
                original_name=item.original_name,
                storage_key=item.storage_key,
                sha256=item.sha256,
                size_bytes=item.size_bytes,
                file_metadata=dict(item.metadata),
            )
            for item in promoted.files
        ]
    )
    try:
        if materialize is not None:
            # Establish parent rows before a materializer flushes child features. This remains one
            # transaction, so any materializer failure rolls the complete version back.
            session.flush()
            materialize(session, version_id)
        job.state = AssessmentState.SUCCEEDED
        job.progress = 100
        job.lease_until = None
        job.completed_at = now
        job.dataset_version_id = version_id
        # Preserve the request-side source identity (for example the Thailand bootstrap source
        # checksum) while recording the immutable managed manifest.  This lets a later bootstrap
        # prove that the same bytes were already imported, even when a different Admin runs it.
        job.manifest = {
            **dict(job.manifest or {}),
            "managed_manifest": dict(promoted.manifest),
        }
        job.report = report
        session.commit()
    except Exception:
        session.rollback()
        raise
    return version_id


def finish_import(
    session: Session,
    claim: ImportClaim,
    *,
    dataset_version_id: UUID,
    report: dict[str, object],
    now: datetime | None = None,
) -> bool:
    """Finalize once; stale attempts cannot promote a version."""

    now = now or datetime.now(UTC)
    result = session.execute(
        update(DataImportJob)
        .where(
            DataImportJob.id == claim.import_id,
            DataImportJob.state == AssessmentState.RUNNING,
            DataImportJob.attempt == claim.attempt,
            DataImportJob.lease_until >= now,
            DataImportJob.dataset_version_id.is_(None),
        )
        .values(
            state=AssessmentState.SUCCEEDED,
            progress=100,
            lease_until=None,
            completed_at=now,
            dataset_version_id=dataset_version_id,
            report=report,
        )
        .execution_options(synchronize_session=False)
    )
    session.commit()
    return bool(result.rowcount)


def requeue_failed_import(session: Session, import_id: UUID) -> bool:
    """Retry one unpublished terminal import without creating another immutable identity."""

    result = session.execute(
        update(DataImportJob)
        .where(
            DataImportJob.id == import_id,
            DataImportJob.state.in_([AssessmentState.FAILED, AssessmentState.CANCELLED]),
            DataImportJob.dataset_version_id.is_(None),
        )
        .values(
            state=AssessmentState.QUEUED,
            progress=0,
            lease_until=None,
            started_at=None,
            completed_at=None,
            error_code=None,
            report=None,
        )
        .execution_options(synchronize_session=False)
    )
    session.commit()
    return bool(result.rowcount)


def fail_import(
    session: Session,
    claim: ImportClaim,
    *,
    error_code: str,
    report: dict[str, object],
    now: datetime | None = None,
) -> bool:
    now = now or datetime.now(UTC)
    result = session.execute(
        update(DataImportJob)
        .where(
            DataImportJob.id == claim.import_id,
            DataImportJob.state == AssessmentState.RUNNING,
            DataImportJob.attempt == claim.attempt,
            DataImportJob.lease_until >= now,
        )
        .values(
            state=AssessmentState.FAILED,
            lease_until=None,
            completed_at=now,
            error_code=error_code,
            report=report,
        )
        .execution_options(synchronize_session=False)
    )
    session.commit()
    return bool(result.rowcount)
