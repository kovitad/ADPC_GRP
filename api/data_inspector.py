"""Admin data inspector over the read-only source folder (ADR-0006).

Describes delivered source files so an Admin can see what arrived, what is wrong with it and what is
missing, before anyone writes a loader against it. Nothing here is an assessment: no result is
produced, no version is pinned, and none of it may be shown to a planner or sent to SIG.

The API never opens a GIS file (AD-03). It lists folders, fingerprints them, and hands the
reading to the worker.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel, Field

from api.dependencies import DatabaseSession
from api.errors import GrpError, new_support_ref, not_found, validation_failed
from api.permissions import AdminUser
from api.settings import Settings, data_inspector_available, get_settings
from core.access_models import MembershipRole
from core.data_folder import DataFolderError, list_folders
from core.inspection_jobs import request_inspection
from core.inspection_models import DatasetInspection
from core.models import AssessmentState
from core.storage import LocalStorage

router = APIRouter(prefix="/data-inspector", tags=["data-inspector"])


class InspectionAsk(BaseModel):
    folder: str = Field(default="", max_length=400)
    profile: Literal["general", "grp_baseline", "flood_depth", "points_boundaries"] = (
        "grp_baseline"
    )


class PreviewAsk(BaseModel):
    # An English or Thai district name, or its admin code.
    district: str = Field(min_length=1, max_length=200)


def _available(settings: Settings) -> Path:
    """The configured source root, or an Appendix D error explaining why there is none."""

    if not data_inspector_available(settings):
        raise not_found()
    root = settings.data_in_root
    if not root.exists() or not root.is_dir():
        raise GrpError(
            409,
            "VALIDATION_FAILED",
            "No source data folder is configured. On Docker Desktop, check that "
            ".local/data-in is mounted read-only into the api and worker containers.",
        )
    return root


def _hub_for(principal: AdminUser) -> UUID | None:
    """The Hub to record the inspection against, if the person acts for one.

    The source folder belongs to the server, not to a Hub, so a Platform Admin who is a
    member of none may still inspect it. The report is the same folder either way.
    """

    for member in principal.memberships:
        if member.role == MembershipRole.ADMIN:
            return member.hub_id
    return principal.memberships[0].hub_id if principal.memberships else None


@router.get(
    "/folders",
    summary="List the folders available in the read-only source data folder",
    openapi_extra={"x-grp-access": "protected"},
)
def source_folders(principal: AdminUser) -> dict[str, object]:
    root = _available(get_settings())
    return {
        "root_label": str(root),
        "folders": list_folders(root),
        "notice": "Delivered source data before ingestion. Nothing here is a GRP result.",
    }


@router.post(
    "/inspections",
    summary="Return the cached report for a folder, or queue one",
    openapi_extra={"x-grp-access": "protected"},
)
def ask_for_inspection(
    ask: InspectionAsk,
    principal: AdminUser,
    session: DatabaseSession,
) -> dict[str, object]:
    root = _available(get_settings())
    try:
        result = request_inspection(
            session,
            root=root,
            folder=ask.folder,
            profile=ask.profile,
            hub_id=_hub_for(principal),
            user_id=principal.user_id,
            support_ref=new_support_ref(),
        )
    except DataFolderError as error:
        session.rollback()
        raise validation_failed(str(error)) from error
    return {
        "inspection_id": str(result.inspection_id),
        "state": result.state,
        "from_cache": result.cached,
    }


@router.get(
    "/inspections/{inspection_id}",
    summary="Get one inspection and its report when it is ready",
    openapi_extra={"x-grp-access": "protected"},
)
def read_inspection(
    inspection_id: UUID,
    principal: AdminUser,
    session: DatabaseSession,
) -> dict[str, object]:
    _available(get_settings())
    inspection = session.get(DatasetInspection, inspection_id)
    if inspection is None:
        raise not_found()
    return {
        "inspection_id": str(inspection.id),
        "folder": inspection.folder,
        "district": inspection.district,
        "profile": inspection.profile,
        "state": inspection.state,
        "error_code": inspection.error_code,
        "support_ref": inspection.support_ref,
        "created_at": inspection.created_at.isoformat(),
        "completed_at": (
            inspection.completed_at.isoformat() if inspection.completed_at else None
        ),
        # A preview that named no known district keeps its reason so the page can say it.
        "report": (
            inspection.report
            if inspection.state == AssessmentState.SUCCEEDED
            or (inspection.report or {}).get("not_found")
            else None
        ),
    }


@router.post(
    "/previews",
    summary="Queue a delivered-data preview of one district (or return the stored one)",
    openapi_extra={"x-grp-access": "protected"},
)
def ask_for_preview(
    ask: PreviewAsk,
    principal: AdminUser,
    session: DatabaseSession,
) -> dict[str, object]:
    root = _available(get_settings())
    try:
        result = request_inspection(
            session,
            root=root,
            folder="",
            district=ask.district,
            hub_id=_hub_for(principal),
            user_id=principal.user_id,
            support_ref=new_support_ref(),
        )
    except DataFolderError as error:
        session.rollback()
        raise validation_failed(str(error)) from error
    return {
        "inspection_id": str(result.inspection_id),
        "state": result.state,
        "from_cache": result.cached,
    }


@router.get(
    "/previews/{inspection_id}/flood.png",
    summary="Display-only flood depth picture for a district preview",
    openapi_extra={"x-grp-access": "protected"},
    response_class=Response,
)
def preview_flood_picture(
    inspection_id: UUID,
    principal: AdminUser,
    session: DatabaseSession,
) -> Response:
    settings = get_settings()
    _available(settings)
    inspection = session.get(DatasetInspection, inspection_id)
    flood = ((inspection.report or {}).get("flood") or {}) if inspection else {}
    key = flood.get("image_key")
    storage = LocalStorage(settings.storage_root)
    if not inspection or not inspection.district or not key or not storage.exists(str(key)):
        raise not_found()
    return Response(
        storage.read_bytes(str(key)),
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=3600"},
    )
