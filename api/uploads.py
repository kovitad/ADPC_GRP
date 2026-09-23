"""Developer-only browser upload into job-scoped local quarantine."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from fastapi import APIRouter, Header, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from api.dependencies import DatabaseSession
from api.errors import GrpError, new_support_ref, not_found
from api.permissions import PlatformAdmin
from api.settings import get_settings
from core.access_models import AuditEvent, uuid7
from core.assessment_models import Dataset, DatasetVersion
from core.browser_uploads import (
    BrowserUploadError,
    extract_shelter_archive,
    upload_directory,
)
from core.data_library_models import DataImportJob
from core.models import AssessmentState

router = APIRouter(prefix="/uploads", tags=["uploads"])

_ZIP_CONTENT_TYPES = {"application/zip", "application/x-zip-compressed"}


def _existing_import(
    session: DatabaseSession, requested_by, idempotency_key: str
) -> DataImportJob | None:
    return session.scalar(
        select(DataImportJob).where(
            DataImportJob.requested_by == requested_by,
            DataImportJob.idempotency_key == idempotency_key,
        )
    )


def _upload_response(job: DataImportJob, *, reused: bool) -> dict[str, object]:
    """Return one stable response shape for the first request and every retry."""

    manifest = job.manifest or {}
    files = manifest.get("filenames", [])
    return {
        "import_id": str(job.id),
        "state": job.state,
        "reused": reused,
        "received_bytes": int(manifest.get("compressed_bytes", 0)),
        "files": list(files) if isinstance(files, list) else [],
        "support_ref": job.support_ref,
    }


@router.post(
    "/evacuation-centers",
    summary="Upload a shelter Shapefile ZIP into local quarantine",
    openapi_extra={"x-grp-access": "protected"},
)
async def upload_evacuation_centers(
    request: Request,
    principal: PlatformAdmin,
    session: DatabaseSession,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128),
    upload_filename: str = Header(alias="X-Upload-Filename", min_length=1, max_length=200),
) -> dict[str, object]:
    settings = get_settings()
    if settings.grp_env != "dev" or not settings.shelter_browser_upload_enabled:
        raise not_found()

    existing = _existing_import(session, principal.user_id, idempotency_key)
    if existing is not None:
        return _upload_response(existing, reused=True)

    content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
    if content_type not in _ZIP_CONTENT_TYPES:
        raise GrpError(415, "UNSUPPORTED_MEDIA_TYPE", "Upload one ZIP file.")
    filename = Path(upload_filename.replace("\\", "/")).name
    if filename != upload_filename or not filename.casefold().endswith(".zip"):
        raise GrpError(422, "VALIDATION_FAILED", "The upload filename must end in .zip.")
    declared = request.headers.get("content-length")
    if declared and (not declared.isdigit() or int(declared) > settings.shelter_upload_max_bytes):
        raise GrpError(413, "UPLOAD_TOO_LARGE", "The shelter ZIP exceeds the upload limit.")
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
            "Import the platform district boundaries before uploading evacuation centres.",
        )

    import_id = uuid7()
    base = upload_directory(settings.storage_root, import_id)
    partial = base / "bundle.zip.partial"
    archive = base / "bundle.zip"
    received = 0
    try:
        base.mkdir(parents=True, exist_ok=False)
        with partial.open("xb") as output:
            async for chunk in request.stream():
                received += len(chunk)
                if received > settings.shelter_upload_max_bytes:
                    raise GrpError(
                        413, "UPLOAD_TOO_LARGE", "The shelter ZIP exceeds the upload limit."
                    )
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        if received == 0:
            raise GrpError(422, "VALIDATION_FAILED", "The uploaded ZIP is empty.")
        os.replace(partial, archive)
        prepared = extract_shelter_archive(
            archive,
            settings.storage_root,
            import_id,
            max_uncompressed_bytes=settings.shelter_upload_max_uncompressed_bytes,
        )
        archive.unlink(missing_ok=True)
        support_ref = new_support_ref()
        job = DataImportJob(
            id=import_id,
            hub_id=None,
            requested_by=principal.user_id,
            idempotency_key=idempotency_key,
            category="evacuation_centers",
            source_ref=prepared.source_ref,
            support_ref=support_ref,
            source_mode="browser_upload",
            state=AssessmentState.QUEUED,
            manifest={
                "original_filename": filename,
                "filenames": list(prepared.filenames),
                "compressed_bytes": prepared.compressed_bytes,
                "uncompressed_bytes": prepared.uncompressed_bytes,
            },
        )
        session.add_all(
            [
                job,
                AuditEvent(
                    actor_user_id=principal.user_id,
                    actor_kind="person",
                    hub_id=None,
                    action="shelter_browser_upload_queued",
                    target_type="data_import_job",
                    target_id=str(import_id),
                    new_value={
                        "category": "evacuation_centers",
                        "source_mode": "browser_upload",
                        "compressed_bytes": prepared.compressed_bytes,
                    },
                    result="success",
                    support_ref=support_ref,
                ),
            ]
        )
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            shutil.rmtree(base, ignore_errors=True)
            existing = _existing_import(session, principal.user_id, idempotency_key)
            if existing is None:
                raise
            return _upload_response(existing, reused=True)
        return _upload_response(job, reused=False)
    except BrowserUploadError as exc:
        shutil.rmtree(base, ignore_errors=True)
        raise GrpError(422, "VALIDATION_FAILED", str(exc)) from None
    except Exception:
        shutil.rmtree(base, ignore_errors=True)
        raise
