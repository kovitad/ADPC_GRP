"""Shared request principals for the Section 9.4 permission matrix."""

from typing import Annotated

from fastapi import Depends, Request

from api.dependencies import DatabaseSession
from api.errors import access_not_authorized
from api.sessions import CurrentPrincipal, load_principal
from api.settings import get_settings


def signed_in_member(request: Request, session: DatabaseSession) -> CurrentPrincipal:
    return load_principal(request, session, get_settings())


def platform_admin(request: Request, session: DatabaseSession) -> CurrentPrincipal:
    principal = load_principal(request, session, get_settings())
    if not principal.is_platform_admin:
        raise access_not_authorized()
    return principal


SignedInMember = Annotated[CurrentPrincipal, Depends(signed_in_member)]
PlatformAdmin = Annotated[CurrentPrincipal, Depends(platform_admin)]
