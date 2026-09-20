"""Admin API for versioned platform baseline data (ADR-0008)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Header
from sqlalchemy import func, select

from api.dependencies import DatabaseSession
from api.errors import GrpError, new_support_ref, not_found
from api.permissions import AdminUser, PlatformAdmin
from api.settings import get_settings
from core.access_models import AuditEvent
from core.assessment_models import Boundary, Dataset, DatasetVersion
from core.boundary_import import BOUNDARY_SOURCE_REF, BOUNDARY_STEM, REQUIRED_SUFFIXES
from core.data_import_jobs import request_import
from core.data_library_models import DataImportJob, DatasetFile
from core.models import AssessmentState

router = APIRouter(prefix="/data-library", tags=["data-library"])


def _boundary_source_available() -> bool:
    folder = get_settings().data_in_root / BOUNDARY_SOURCE_REF
    return all((folder / f"{BOUNDARY_STEM}{suffix}").is_file() for suffix in REQUIRED_SUFFIXES)


def _version_payload(session: DatabaseSession, version: DatasetVersion) -> dict[str, object]:
    feature_count = session.scalar(
        select(func.count())
        .select_from(Boundary)
        .where(Boundary.collection_version_id == version.id)
    )
    file_count = session.scalar(
        select(func.count())
        .select_from(DatasetFile)
        .where(DatasetFile.dataset_version_id == version.id)
    )
    return {
        "version_id": str(version.id),
        "readiness": version.readiness,
        "edition": version.meta.get("edition"),
        "feature_count": feature_count or 0,
        "supported_count": version.meta.get("supported_count", 0),
        "file_count": file_count or 0,
        "sha256": version.sha256,
        "importer_version": version.importer_version,
        "created_at": version.created_at.isoformat(),
        "is_current": version.is_current,
    }


@router.get(
    "",
    summary="Read platform baseline versions and import availability",
    openapi_extra={"x-grp-access": "protected"},
)
def data_library(principal: AdminUser, session: DatabaseSession) -> dict[str, object]:
    versions = session.scalars(
        select(DatasetVersion)
        .join(Dataset, Dataset.id == DatasetVersion.dataset_id)
        .where(Dataset.type == "boundary", Dataset.owner_kind == "platform")
        .order_by(DatasetVersion.created_at.desc())
    ).all()
    running = session.scalar(
        select(DataImportJob)
        .where(
            DataImportJob.category == "boundary",
            DataImportJob.state.in_([AssessmentState.QUEUED, AssessmentState.RUNNING]),
        )
        .order_by(DataImportJob.created_at.desc())
    )
    return {
        "can_import_platform_baseline": principal.is_platform_admin,
        "boundary": {
            "source_available": _boundary_source_available(),
            "source_ref": BOUNDARY_SOURCE_REF,
            "required_files": [f"{BOUNDARY_STEM}{suffix}" for suffix in REQUIRED_SUFFIXES],
            "active_import_id": str(running.id) if running else None,
            "versions": [_version_payload(session, version) for version in versions],
        },
        "vulnerability": {
            "state": "not_imported",
            "message": (
                "Process separately on the deployment VM; scientific meaning pending DEP-07."
            ),
        },
    }


@router.post(
    "/imports/boundaries",
    summary="Queue the accepted Thailand district-boundary baseline import",
    openapi_extra={"x-grp-access": "protected"},
)
def import_boundaries(
    principal: PlatformAdmin,
    session: DatabaseSession,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128),
) -> dict[str, object]:
    if not _boundary_source_available():
        raise GrpError(
            409,
            "VALIDATION_FAILED",
            "The accepted district-boundary source files are not available on this server.",
        )
    existing = session.scalar(
        select(DataImportJob)
        .where(
            DataImportJob.category == "boundary",
            DataImportJob.state.in_([AssessmentState.QUEUED, AssessmentState.RUNNING]),
        )
        .order_by(DataImportJob.created_at.desc())
    )
    if existing is not None:
        return {"import_id": str(existing.id), "state": existing.state, "reused": True}

    support_ref = new_support_ref()
    result = request_import(
        session,
        hub_id=None,
        requested_by=principal.user_id,
        idempotency_key=idempotency_key,
        category="boundary",
        source_ref=BOUNDARY_SOURCE_REF,
        support_ref=support_ref,
    )
    session.add(
        AuditEvent(
            actor_user_id=principal.user_id,
            actor_kind="person",
            hub_id=None,
            action="platform_baseline_import_requested",
            target_type="data_import_job",
            target_id=str(result.import_id),
            new_value={"category": "boundary", "source_ref": BOUNDARY_SOURCE_REF},
            result="success",
            support_ref=support_ref,
        )
    )
    session.commit()
    return {"import_id": str(result.import_id), "state": result.state, "reused": result.reused}


@router.get(
    "/imports/{import_id}",
    summary="Read one platform baseline import",
    openapi_extra={"x-grp-access": "protected"},
)
def read_import(
    import_id: UUID, principal: AdminUser, session: DatabaseSession
) -> dict[str, object]:
    job = session.get(DataImportJob, import_id)
    if job is None or job.category != "boundary":
        raise not_found()
    version = (
        session.get(DatasetVersion, job.dataset_version_id) if job.dataset_version_id else None
    )
    return {
        "import_id": str(job.id),
        "category": job.category,
        "state": job.state,
        "progress": job.progress,
        "error_code": job.error_code,
        "support_ref": job.support_ref,
        "report": job.report
        if job.state in (AssessmentState.SUCCEEDED, AssessmentState.FAILED)
        else None,
        "created_at": job.created_at.isoformat(),
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "version": _version_payload(session, version) if version else None,
    }
