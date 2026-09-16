from fastapi import APIRouter, Request, Response

from api.dependencies import DatabaseSession
from api.sessions import load_principal, set_session_cookie
from api.settings import get_settings
from core.identity import IdentityLinkResult

router = APIRouter(tags=["access"])


@router.get(
    "/me",
    summary="Read the current GRP identity and memberships",
    openapi_extra={"x-grp-access": "protected"},
)
def current_user(
    request: Request,
    response: Response,
    session: DatabaseSession,
) -> dict[str, object]:
    """Reload account and role mappings on every request and refresh idle expiry."""

    settings = get_settings()
    principal = load_principal(request, session, settings)
    result = IdentityLinkResult(
        allowed=True,
        reason="allowed",
        user_id=principal.user_id,
        email=principal.email,
        display_name=principal.display_name,
        is_platform_admin=principal.is_platform_admin,
        memberships=principal.memberships,
    )
    set_session_cookie(
        response,
        settings,
        result,
        issued_at=principal.issued_at,
        session_id=principal.session_id,
    )
    return {
        "user_id": str(principal.user_id),
        "email": principal.email,
        "display_name": principal.display_name,
        "is_platform_admin": principal.is_platform_admin,
        "memberships": [
            {
                "hub_id": str(membership.hub_id),
                "hub_code": membership.hub_code,
                "hub_name": membership.hub_name,
                "role": membership.role,
            }
            for membership in principal.memberships
        ],
    }
