from fastapi import APIRouter, status
from fastapi.responses import RedirectResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get(
    "/login",
    summary="Begin SERVIR sign-in",
    status_code=status.HTTP_303_SEE_OTHER,
    openapi_extra={"x-grp-access": "public"},
)
def begin_login() -> RedirectResponse:
    """Return to the sign-in screen until the SERVIR OIDC adapter is configured."""

    return RedirectResponse(url="/?auth=unavailable", status_code=status.HTTP_303_SEE_OTHER)


# Increment 2 continues with the SERVIR OIDC callback, logout, secure GRP
# sessions, identity linking, and database-backed membership checks.
