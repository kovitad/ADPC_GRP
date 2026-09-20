from __future__ import annotations

import hmac
import secrets
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, RedirectResponse

from api.dependencies import DatabaseSession
from api.errors import GrpError
from api.oidc import (
    IdentityProviderError,
    ServirSigIdentityProvider,
    generate_pkce_pair,
)
from api.planning_cache import planning_answer_cache
from api.sessions import (
    AUTH_TRANSACTION_COOKIE,
    CSRF_HEADER,
    SESSION_COOKIE,
    clear_session_cookies,
    csrf_token,
    decode_auth_transaction,
    decode_session_cookie,
    encode_auth_transaction,
    revoke_user_sessions,
    secure_cookie,
    set_session_cookie,
)
from api.settings import Settings, get_settings, planning_chat_available
from api.token_store import session_token_store
from core.access_models import AppUser, AuditEvent, AuditResult
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
            authenticated = await provider.exchange_callback(
                code,
                transaction["nonce"],
                transaction["code_verifier"],
            )
        finally:
            await provider.close()
        result = link_verified_identity(session, authenticated.identity, request_intent=intent)
        session.commit()
    except (HTTPException, IdentityProviderError, KeyError, OSError):
        session.rollback()
        return _screen("failed", intent)

    if not result.allowed:
        response = _screen("pending", intent)
    elif intent == "admin" and not (
        result.is_platform_admin or any(item.role == "admin" for item in result.memberships)
    ):
        response = _screen("not_admin", intent)
    else:
        location = "/workspace.html#admin-panel" if intent == "admin" else "/workspace.html"
        response = RedirectResponse(url=location, status_code=status.HTTP_303_SEE_OTHER)
        session_id = str(uuid4())
        planning_answer_cache.delete_user(str(result.user_id))
        set_session_cookie(response, settings, result, session_id=session_id)
        if planning_chat_available(settings):
            # Interim exception (ADR-0002, ADR-0004): SIG MCP token kept in memory, dev only.
            session_token_store.put(
                session_id, authenticated.access_token, authenticated.expires_in
            )
    response.delete_cookie(AUTH_TRANSACTION_COOKIE, path="/api/v1/auth")
    return response


@router.post(
    "/logout",
    summary="End the GRP session",
    openapi_extra={"x-grp-access": "public"},
)
def logout(request: Request, session: DatabaseSession) -> JSONResponse:
    """End the GRP session on the server and in the browser (SIG sign-in is unchanged).

    POST with the CSRF header so another site cannot sign a person out.
    """

    settings = get_settings()
    value = request.cookies.get(SESSION_COOKIE)
    if value:
        try:
            decoded = decode_session_cookie(settings, value)
            supplied = request.headers.get(CSRF_HEADER, "")
            if not hmac.compare_digest(supplied, csrf_token(settings, decoded["session_id"])):
                raise GrpError(403, "ACCESS_NOT_AUTHORIZED", "Access not authorized.")
            session_token_store.delete(decoded["session_id"])
            planning_answer_cache.delete_session(decoded["session_id"])
            user = session.get(AppUser, UUID(decoded["user_id"]))
            if user is not None:
                revoke_user_sessions(user)
                session.add(
                    AuditEvent(
                        actor_user_id=user.id,
                        actor_kind="person",
                        action="sign_out",
                        target_type="app_user",
                        target_id=str(user.id),
                        result=AuditResult.SUCCESS,
                    )
                )
                session.commit()
        except GrpError as error:
            session.rollback()
            if error.code == "ACCESS_NOT_AUTHORIZED":
                raise
        except (ValueError, OSError):
            session.rollback()
    response = JSONResponse({"signed_out": True, "location": "/"})
    clear_session_cookies(response)
    return response
