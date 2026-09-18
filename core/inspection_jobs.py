"""Queue, cache and run data inspections (ADR-0006).

An inspection is a background job for the same reason an assessment is: reading GIS files is
the worker's work, never the API's (AD-03). It is deliberately *not* an assessment — it
produces no result, pins no versions, and nothing it reports may reach a planner.

The cache is keyed by the fingerprint of every file in scope, so a stored report is reused only
while those exact files are unchanged.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from core.data_folder import (
    DataFolderError,
    folder_fingerprint,
    list_files,
    resolve_folder,
)
from core.inspection_models import DatasetInspection
from core.models import AssessmentState

logger = logging.getLogger("grp.worker.inspection")
MAX_ATTEMPTS = 2


@dataclass(frozen=True)
class InspectionRequest:
    inspection_id: UUID
    state: str
    cached: bool


def request_inspection(
    session: Session,
    *,
    root: Path,
    folder: str,
    hub_id: UUID | None,
    user_id: UUID,
    support_ref: str,
) -> InspectionRequest:
    """Return the cached report for this folder, or queue a job to build one.

    Raises DataFolderError when the folder cannot be used. Fingerprinting reads the files, which
    is cheap compared with opening them as GIS layers, and keeps the API free of GIS (AD-03).
    """

    target = resolve_folder(root, folder)
    files = list_files(target, root)
    if not files:
        raise DataFolderError("That folder holds no files.")
    fingerprint = folder_fingerprint(files)
    relative = "" if target == root.resolve() else target.relative_to(root.resolve()).as_posix()

    cached = session.scalar(
        select(DatasetInspection)
        .where(
            DatasetInspection.folder == relative,
            DatasetInspection.fingerprint == fingerprint,
            DatasetInspection.state.in_(
                (AssessmentState.SUCCEEDED, AssessmentState.QUEUED, AssessmentState.RUNNING)
            ),
        )
        .order_by(DatasetInspection.created_at.desc())
    )
    if cached is not None:
        return InspectionRequest(
            cached.id, cached.state, cached.state == AssessmentState.SUCCEEDED
        )

    inspection = DatasetInspection(
        hub_id=hub_id,
        requested_by=user_id,
        folder=relative,
        fingerprint=fingerprint,
        state=AssessmentState.QUEUED,
        support_ref=support_ref,
    )
    session.add(inspection)
    session.commit()
    return InspectionRequest(inspection.id, inspection.state, False)


def claim_next_inspection(
    session: Session, *, lease_minutes: int, now: datetime | None = None
) -> UUID | None:
    """Claim one queued inspection (or one whose lease expired) with SKIP LOCKED.

    Same locking rule as assessments, so two workers never run the same inspection twice.
    """

    now = now or datetime.now(UTC)
    inspection = session.scalar(
        select(DatasetInspection)
        .where(
            or_(
                DatasetInspection.state == AssessmentState.QUEUED,
                (DatasetInspection.state == AssessmentState.RUNNING)
                & (DatasetInspection.lease_until < now),
            )
        )
        .order_by(DatasetInspection.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if inspection is None:
        return None
    inspection.state = AssessmentState.RUNNING
    inspection.lease_until = now + timedelta(minutes=lease_minutes)
    inspection.attempt += 1
    inspection.started_at = inspection.started_at or now
    session.commit()
    return inspection.id


def process_inspection(session: Session, root: Path, inspection_id: UUID) -> str:
    """Run one claimed inspection to a final state. Returns the resulting state."""

    # GIS libraries load only in the worker; the API never imports them (AD-03).
    from core.dataset_scan import scan_folder

    inspection = session.get(DatasetInspection, inspection_id)
    if inspection is None or inspection.state != AssessmentState.RUNNING:
        return inspection.state if inspection else "missing"

    try:
        target = resolve_folder(root, inspection.folder)
        files = list_files(target, root)
        if folder_fingerprint(files) != inspection.fingerprint:
            # The files changed while the job waited; the report would describe something else.
            return _fail(session, inspection, "INPUT_FINGERPRINT_MISMATCH", "files changed")
        report = scan_folder(target, root, files)
    except DataFolderError as error:
        return _fail(session, inspection, "VALIDATION_FAILED", str(error))
    except (OperationalError, OSError) as error:
        session.rollback()
        return _retry_or_fail(session, inspection_id, error)

    report["files"] = [
        {
            "path": item.relative_path,
            "size_bytes": item.size_bytes,
            "fingerprint": item.fingerprint,
            "fully_fingerprinted": item.fully_fingerprinted,
        }
        for item in files
    ]
    report["fingerprint"] = inspection.fingerprint
    report["partly_fingerprinted"] = not all(item.fully_fingerprinted for item in files)
    inspection.report = report
    inspection.state = AssessmentState.SUCCEEDED
    inspection.lease_until = None
    inspection.completed_at = datetime.now(UTC)
    session.commit()
    logger.info("Inspection %s described %d layers", inspection_id, len(report["layers"]))
    return inspection.state


def _fail(session: Session, inspection: DatasetInspection, code: str, detail: str) -> str:
    inspection.state = AssessmentState.FAILED
    inspection.error_code = code
    inspection.lease_until = None
    inspection.completed_at = datetime.now(UTC)
    session.commit()
    logger.warning("Inspection %s failed: %s (%s)", inspection.id, code, detail)
    return inspection.state


def _retry_or_fail(session: Session, inspection_id: UUID, error: Exception) -> str:
    inspection = session.get(DatasetInspection, inspection_id)
    if inspection.attempt >= MAX_ATTEMPTS:
        return _fail(session, inspection, "VALIDATION_FAILED", type(error).__name__)
    inspection.state = AssessmentState.QUEUED
    inspection.lease_until = None
    session.commit()
    return inspection.state
