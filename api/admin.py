from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from api.dependencies import DatabaseSession
from api.errors import GrpError, access_not_authorized, not_found, validation_failed
from api.sessions import CurrentPrincipal, load_principal
from api.settings import get_settings
from grp.admin import (
    HubAccessDenied,
    ItemNotFound,
    LastAdminRequired,
    assign_member_as_actor,
    list_admin_hubs,
    list_hub_members,
    membership_access_message,
    update_hub_member,
)

router = APIRouter(prefix="/admin", tags=["admin"])


class MembershipAssignment(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    role: Literal["ndmo_planner", "hub_expert", "admin", "planner"] = "hub_expert"


class MembershipUpdate(BaseModel):
    role: Literal["ndmo_planner", "hub_expert", "admin", "planner"] | None = None
    status: Literal["active", "disabled"] | None = None


def authenticated_user(
    request: Request,
    session: DatabaseSession,
) -> CurrentPrincipal:
    return load_principal(request, session, get_settings())


AuthenticatedUser = Annotated[CurrentPrincipal, Depends(authenticated_user)]


def _bad_request(error: ValueError) -> GrpError:
    """Map domain errors to Appendix D codes without revealing other Hubs."""

    if isinstance(error, LastAdminRequired):
        return GrpError(409, "LAST_ADMIN_REQUIRED", "A Hub must keep at least one Admin.")
    if isinstance(error, ItemNotFound):
        return not_found()
    if isinstance(error, HubAccessDenied):
        return access_not_authorized()
    return validation_failed(str(error))


@router.get(
    "/hubs",
    summary="List Hubs the current administrator may manage",
    openapi_extra={"x-grp-access": "protected"},
)
def administered_hubs(
    principal: AuthenticatedUser,
    session: DatabaseSession,
) -> dict[str, object]:
    try:
        hubs = list_admin_hubs(session, actor_user_id=principal.user_id)
    except ValueError as error:
        raise _bad_request(error) from error
    return {"hubs": hubs}


@router.post(
    "/hubs/{hub_code}/members",
    summary="Assign the first active role for a verified identity",
    openapi_extra={"x-grp-access": "protected"},
)
def create_hub_membership(
    hub_code: str,
    assignment: MembershipAssignment,
    principal: AuthenticatedUser,
    session: DatabaseSession,
) -> dict[str, object]:
    try:
        result = assign_member_as_actor(
            session,
            actor_user_id=principal.user_id,
            email=assignment.email,
            hub_code=hub_code,
            role=assignment.role,
        )
        session.commit()
    except ValueError as error:
        session.rollback()
        raise _bad_request(error) from error
    return {"changed": result.changed, "message": result.message}


@router.get(
    "/hubs/{hub_code}/members",
    summary="List Hub members visible to a Hub or Platform Admin",
    openapi_extra={"x-grp-access": "protected"},
)
def hub_members(
    hub_code: str,
    principal: AuthenticatedUser,
    session: DatabaseSession,
) -> dict[str, object]:
    try:
        members = list_hub_members(
            session, actor_user_id=principal.user_id, hub_code=hub_code
        )
    except ValueError as error:
        raise _bad_request(error) from error
    return {"hub_code": hub_code.lower(), "members": members}


@router.patch(
    "/hubs/{hub_code}/members/{member_id}",
    summary="Change a Hub member role or access state",
    openapi_extra={"x-grp-access": "protected"},
)
def change_hub_membership(
    hub_code: str,
    member_id: UUID,
    update: MembershipUpdate,
    principal: AuthenticatedUser,
    session: DatabaseSession,
) -> dict[str, object]:
    if update.role is None and update.status is None:
        raise validation_failed("Provide role or status.")
    try:
        result = update_hub_member(
            session,
            actor_user_id=principal.user_id,
            hub_code=hub_code,
            member_id=member_id,
            role=update.role,
            membership_status=update.status,
        )
        session.commit()
    except ValueError as error:
        session.rollback()
        raise _bad_request(error) from error
    return {"changed": result.changed, "message": result.message}


@router.get(
    "/hubs/{hub_code}/members/{member_id}/access-message",
    summary="Get the ready-to-copy SERVIR access message",
    openapi_extra={"x-grp-access": "protected"},
)
def access_message(
    hub_code: str,
    member_id: UUID,
    principal: AuthenticatedUser,
    session: DatabaseSession,
) -> dict[str, str]:
    try:
        message = membership_access_message(
            session,
            actor_user_id=principal.user_id,
            hub_code=hub_code,
            member_id=member_id,
            grp_address=get_settings().grp_public_base_url,
        )
    except ValueError as error:
        raise _bad_request(error) from error
    return {"message": message}
