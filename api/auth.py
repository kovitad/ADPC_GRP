from __future__ import annotations

import hmac
import secrets
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse

from api.dependencies import DatabaseSession
from api.oidc import (
    IdentityProviderError,
    ServirSigIdentityProvider,
    generate_pkce_pair,
)
from api.sessions import (
    AUTH_TRANSACTION_COOKIE,
    SESSION_COOKIE,
    decode_auth_transaction,
    encode_auth_transaction,
    secure_cookie,
    set_session_cookie,
)
from api.settings import Settings, get_settings
from core.identity import link_verified_identity

router = APIRouter(prefix="/auth", tags=["auth"])


def _screen(state: str, intent: str = "sign_in") -> RedirectResponse:
    if intent == "register":
        location = f"/register.html?registration={state}"
    elif intent == "admin":
        location = f"/admin-login.html?auth={state}"
    else:
        location = f"/?auth={state}"
    return RedirectResponse(url=location, status_code=status.HTTP_303_SEE_OTHER)


def _provider_configured(settings: Settings) -> bool:
    return bool(
        settings.sig_mcp_base_url
        and settings.servir_auth_client_id
        and settings.servir_auth_redirect_uri
        and settings.session_secret_file.is_file()
    )


@router.get(
    "/login",
    summary="Begin SERVIR sign-in",
    status_code=status.HTTP_303_SEE_OTHER,
    openapi_extra={"x-grp-access": "public"},
)
async def begin_login(
    intent: Literal["sign_in", "register", "admin"] = Query(default="sign_in"),
) -> RedirectResponse:
    """Start an authorization-code flow against the configured SERVIR OIDC app."""

    settings = get_settings()
    if not _provider_configured(settings):
        return _screen("unavailable", intent)
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier, challenge = generate_pkce_pair()
    provider: ServirSigIdentityProvider | None = None
    try:
        provider = ServirSigIdentityProvider(settings)
        location = await provider.authorization_url(state, nonce, challenge)
        transaction = encode_auth_transaction(
            settings,
            {
                "state": state,
                "nonce": nonce,
                "code_verifier": verifier,
                "intent": intent,
            },
        )
    except (IdentityProviderError, OSError):
        return _screen("unavailable", intent)
    finally:
        if provider is not None:
            await provider.close()
    response = RedirectResponse(url=location, status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        AUTH_TRANSACTION_COOKIE,
        transaction,
        max_age=600,
        httponly=True,
        secure=secure_cookie(settings),
        samesite="lax",
        path="/api/v1/auth",
    )
    return response


@router.get(
    "/callback",
    summary="Complete SERVIR sign-in",
    status_code=status.HTTP_303_SEE_OTHER,
    openapi_extra={"x-grp-access": "public"},
)
async def complete_login(
    request: Request,
    session: DatabaseSession,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> RedirectResponse:
    """Verify the callback, link an approved member, and create a GRP session."""

    settings = get_settings()
    transaction_cookie = request.cookies.get(AUTH_TRANSACTION_COOKIE)
    if not transaction_cookie or not _provider_configured(settings):
        return _screen("failed")
    intent = "sign_in"
    try:
        transaction = decode_auth_transaction(settings, transaction_cookie)
        if transaction.get("intent") in {"register", "admin"}:
            intent = transaction["intent"]
        if error or not code or not state:
            return _screen("failed", intent)
        if not hmac.compare_digest(transaction.get("state", ""), state):
            return _screen("failed", intent)
        provider = ServirSigIdentityProvider(settings)
        try:
            identity = await provider.exchange_callback(
                code,
                transaction["nonce"],
                transaction["code_verifier"],
            )
        finally:
            await provider.close()
        result = link_verified_identity(session, identity, request_intent=intent)
        session.commit()
    except (HTTPException, IdentityProviderError, KeyError, OSError):
        session.rollback()
        return _screen("failed", intent)

    if not result.allowed:
        response = _screen("pending", intent)
    elif intent == "admin" and not result.is_platform_admin:
        response = _screen("not_admin", intent)
    else:
        response = RedirectResponse(url="/workspace.html", status_code=status.HTTP_303_SEE_OTHER)
        set_session_cookie(response, settings, result)
    response.delete_cookie(AUTH_TRANSACTION_COOKIE, path="/api/v1/auth")
    return response


@router.get(
    "/logout",
    summary="End the GRP session",
    status_code=status.HTTP_303_SEE_OTHER,
    openapi_extra={"x-grp-access": "public"},
)
def logout() -> RedirectResponse:
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response
