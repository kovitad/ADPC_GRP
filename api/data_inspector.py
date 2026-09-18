"""Admin data inspector over the read-only source folder (ADR-0006).

Describes unapproved files so an Admin can see what arrived, what is wrong with it and what is
missing, before anyone writes a loader against it. Nothing here is an assessment: no result is
produced, no version is pinned, and none of it may be shown to a planner or sent to SIG.

The API never opens a GIS file (AD-03). It lists folders, fingerprints them, and hands the
reading to the worker.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter
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

router = APIRouter(prefix="/data-inspector", tags=["data-inspector"])


class InspectionAsk(BaseModel):
    folder: str = Field(default="", max_length=400)


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
        "notice": "Unapproved source data. Nothing here is a GRP result.",
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
        "state": inspection.state,
        "error_code": inspection.error_code,
        "support_ref": inspection.support_ref,
        "created_at": inspection.created_at.isoformat(),
        "completed_at": (
            inspection.completed_at.isoformat() if inspection.completed_at else None
        ),
        "report": inspection.report if inspection.state == AssessmentState.SUCCEEDED else None,
    }
