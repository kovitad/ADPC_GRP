"""Queue and lease controls for data-library imports (ADR-0008).

A worker attempt number acts as its fencing token: after a lease expires and another worker claims
the job, the stale worker can neither renew nor finalize that job.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.data_library_models import DataImportJob
from core.models import AssessmentState


@dataclass(frozen=True)
class ImportRequest:
    import_id: UUID
    state: str
    reused: bool


@dataclass(frozen=True)
class ImportClaim:
    import_id: UUID
    attempt: int


def request_import(
    session: Session,
    *,
    hub_id: UUID | None,
    requested_by: UUID,
    idempotency_key: str,
    category: str,
    source_ref: str,
    support_ref: str,
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
        hub_id=hub_id,
        requested_by=requested_by,
        idempotency_key=idempotency_key,
        category=category,
        source_mode="source_folder",
        source_ref=source_ref,
        state=AssessmentState.QUEUED,
        support_ref=support_ref,
        manifest={},
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
    )
    session.commit()
    return bool(result.rowcount)


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
        )
        .values(
            state=AssessmentState.FAILED,
            lease_until=None,
            completed_at=now,
            error_code=error_code,
            report=report,
        )
    )
    session.commit()
    return bool(result.rowcount)
