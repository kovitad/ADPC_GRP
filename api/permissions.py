"""Shared request principals for the Section 9.4 permission matrix."""

from typing import Annotated

from fastapi import Depends, Request

from api.dependencies import DatabaseSession
from api.errors import access_not_authorized
from api.sessions import CurrentPrincipal, load_principal
from api.settings import get_settings
from core.access_models import MembershipRole


def signed_in_member(request: Request, session: DatabaseSession) -> CurrentPrincipal:
    return load_principal(request, session, get_settings())


def platform_admin(request: Request, session: DatabaseSession) -> CurrentPrincipal:
    principal = load_principal(request, session, get_settings())
    if not principal.is_platform_admin:
        raise access_not_authorized()
    return principal


def admin_user(request: Request, session: DatabaseSession) -> CurrentPrincipal:
    """A Platform Admin, or a Hub Admin of any Hub. Not Planners or Hub Experts.

    `PLANNING_MEMBER_ROLES` deliberately includes Admin, so it cannot be used here: it would
    also admit Hub Experts.
    """

    principal = load_principal(request, session, get_settings())
    if principal.is_platform_admin:
        return principal
    if any(member.role == MembershipRole.ADMIN for member in principal.memberships):
        return principal
    raise access_not_authorized()


SignedInMember = Annotated[CurrentPrincipal, Depends(signed_in_member)]
PlatformAdmin = Annotated[CurrentPrincipal, Depends(platform_admin)]
AdminUser = Annotated[CurrentPrincipal, Depends(admin_user)]
