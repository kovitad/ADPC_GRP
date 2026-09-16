from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from api.dependencies import DatabaseSession
from api.sessions import CurrentPrincipal, load_principal
from api.settings import get_settings
from grp.admin import assign_member, list_access_requests

router = APIRouter(prefix="/admin", tags=["admin"])


class MembershipAssignment(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    role: Literal["planner", "admin"] = "planner"


def platform_admin(
    request: Request,
    session: DatabaseSession,
) -> CurrentPrincipal:
    principal = load_principal(request, session, get_settings())
    if not principal.is_platform_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform Admin access required",
        )
    return principal


PlatformAdmin = Annotated[CurrentPrincipal, Depends(platform_admin)]


@router.get(
    "/access-requests",
    summary="List verified identities awaiting GRP membership",
    openapi_extra={"x-grp-access": "protected"},
)
def pending_access_requests(
    principal: PlatformAdmin,
    session: DatabaseSession,
) -> dict[str, list[dict[str, str]]]:
    del principal
    return {"requests": [{"email": email} for email in list_access_requests(session)]}


@router.post(
    "/hubs/{hub_code}/members",
    summary="Assign the first active role for a verified identity",
    openapi_extra={"x-grp-access": "protected"},
)
def create_hub_membership(
    hub_code: str,
    assignment: MembershipAssignment,
    principal: PlatformAdmin,
    session: DatabaseSession,
) -> dict[str, object]:
    try:
        result = assign_member(
            session,
            actor_email=principal.email,
            email=assignment.email,
            hub_code=hub_code,
            role=assignment.role,
        )
        session.commit()
    except ValueError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    return {"changed": result.changed, "message": result.message}
