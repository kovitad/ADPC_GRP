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
from core.assessment_models import Boundary, Dataset, DatasetVersion, Feature
from core.boundary_import import (
    BOUNDARY_SOURCE_REF,
    BOUNDARY_STEM,
)
from core.boundary_import import (
    REQUIRED_SUFFIXES as BOUNDARY_REQUIRED_SUFFIXES,
)
from core.data_import_jobs import request_import
from core.data_library_models import DataImportJob, DatasetFile
from core.hazard_import import HAZARD_SOURCE_REF, hazard_source_available
from core.models import AssessmentState
from core.shelter_import import (
    REQUIRED_SUFFIXES as SHELTER_REQUIRED_SUFFIXES,
)
from core.shelter_import import (
    SHELTER_SOURCE_REF,
    SHELTER_STEM,
)

router = APIRouter(prefix="/data-library", tags=["data-library"])


def _boundary_source_available() -> bool:
    folder = get_settings().data_in_root / BOUNDARY_SOURCE_REF
    return all(
        (folder / f"{BOUNDARY_STEM}{suffix}").is_file()
        for suffix in BOUNDARY_REQUIRED_SUFFIXES
    )


def _shelter_source_available() -> bool:
    folder = get_settings().data_in_root / SHELTER_SOURCE_REF
    return all(
        (folder / f"{SHELTER_STEM}{suffix}").is_file()
        for suffix in SHELTER_REQUIRED_SUFFIXES
    )


def _version_payload(session: DatabaseSession, version: DatasetVersion) -> dict[str, object]:
    dataset = session.get(Dataset, version.dataset_id)
    feature_model = Boundary if dataset and dataset.type == "boundary" else Feature
    version_column = (
        Boundary.collection_version_id
        if feature_model is Boundary
        else Feature.dataset_version_id
    )
    feature_count = session.scalar(
        select(func.count()).select_from(feature_model).where(version_column == version.id)
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
        "tile_count": version.meta.get("tile_count"),
        "district_name_mismatch_count": version.meta.get("district_name_mismatch_count"),
        "outside_boundary_count": version.meta.get("outside_boundary_count"),
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
    shelter_versions = session.scalars(
        select(DatasetVersion)
        .join(Dataset, Dataset.id == DatasetVersion.dataset_id)
        .where(Dataset.type == "evacuation_centers", Dataset.owner_kind == "platform")
        .order_by(DatasetVersion.created_at.desc())
    ).all()
    hazard_versions = session.scalars(
        select(DatasetVersion)
        .join(Dataset, Dataset.id == DatasetVersion.dataset_id)
        .where(Dataset.type == "hazard", Dataset.owner_kind == "platform")
        .order_by(DatasetVersion.created_at.desc())
    ).all()
    active_jobs = {
        job.category: job
        for job in session.scalars(
            select(DataImportJob)
            .where(
                DataImportJob.category.in_(["boundary", "evacuation_centers", "hazard"]),
                DataImportJob.state.in_([AssessmentState.QUEUED, AssessmentState.RUNNING]),
            )
            .order_by(DataImportJob.created_at)
        ).all()
    }
    return {
        "can_import_platform_baseline": principal.is_platform_admin,
        "boundary": {
            "source_available": _boundary_source_available(),
            "source_ref": BOUNDARY_SOURCE_REF,
            "required_files": [
                f"{BOUNDARY_STEM}{suffix}" for suffix in BOUNDARY_REQUIRED_SUFFIXES
            ],
            "active_import_id": str(active_jobs["boundary"].id)
            if "boundary" in active_jobs
            else None,
            "versions": [_version_payload(session, version) for version in versions],
        },
        "evacuation_centers": {
            "source_available": _shelter_source_available(),
            "source_ref": SHELTER_SOURCE_REF,
            "required_files": [
                f"{SHELTER_STEM}{suffix}" for suffix in SHELTER_REQUIRED_SUFFIXES
            ],
            "requires_boundaries": not bool(versions),
            "active_import_id": str(active_jobs["evacuation_centers"].id)
            if "evacuation_centers" in active_jobs
            else None,
            "versions": [_version_payload(session, version) for version in shelter_versions],
        },
        "hazard": {
            "source_available": hazard_source_available(get_settings().data_in_root),
            "source_ref": HAZARD_SOURCE_REF,
            "required_files": ["exactly six GeoTIFF tiles"],
            "active_import_id": str(active_jobs["hazard"].id)
            if "hazard" in active_jobs
            else None,
            "versions": [_version_payload(session, version) for version in hazard_versions],
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


@router.post(
    "/imports/evacuation-centers",
    summary="Queue the accepted DDPM evacuation-centre baseline import",
    openapi_extra={"x-grp-access": "protected"},
)
def import_evacuation_centers(
    principal: PlatformAdmin,
    session: DatabaseSession,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128),
) -> dict[str, object]:
    if not _shelter_source_available():
        raise GrpError(
            409,
            "VALIDATION_FAILED",
            "The accepted evacuation-centre source files are not available on this server.",
        )
    boundary_exists = session.scalar(
        select(DatasetVersion.id)
        .join(Dataset, Dataset.id == DatasetVersion.dataset_id)
        .where(Dataset.type == "boundary", Dataset.owner_kind == "platform")
        .limit(1)
    )
    if boundary_exists is None:
        raise GrpError(
            409,
            "VALIDATION_FAILED",
            "Import the platform district boundaries before evacuation centres.",
        )
    existing = session.scalar(
        select(DataImportJob)
        .where(
            DataImportJob.category == "evacuation_centers",
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
        category="evacuation_centers",
        source_ref=SHELTER_SOURCE_REF,
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
            new_value={"category": "evacuation_centers", "source_ref": SHELTER_SOURCE_REF},
            result="success",
            support_ref=support_ref,
        )
    )
    session.commit()
    return {"import_id": str(result.import_id), "state": result.state, "reused": result.reused}


@router.post(
    "/imports/hazard-rp100",
    summary="Queue the accepted six-tile RP100 flood-depth baseline import",
    openapi_extra={"x-grp-access": "protected"},
)
def import_hazard_rp100(
    principal: PlatformAdmin,
    session: DatabaseSession,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128),
) -> dict[str, object]:
    if not hazard_source_available(get_settings().data_in_root):
        raise GrpError(
            409,
            "VALIDATION_FAILED",
            "The six accepted RP100 GeoTIFF files are not available on this server.",
        )
    existing = session.scalar(
        select(DataImportJob)
        .where(
            DataImportJob.category == "hazard",
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
        category="hazard",
        source_ref=HAZARD_SOURCE_REF,
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
            new_value={"category": "hazard", "source_ref": HAZARD_SOURCE_REF},
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
    if job is None or job.category not in {"boundary", "evacuation_centers", "hazard"}:
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
