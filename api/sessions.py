from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import HTTPException, Request, Response, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from api.errors import GrpError, access_not_authorized, not_signed_in
from api.rate_limits import limiter
from api.settings import Settings
from core.access_models import AppUser, UserStatus
from core.db import read_secret
from core.identity import IdentityLinkResult, MembershipView, load_active_memberships

SESSION_COOKIE = "grp_session"
CSRF_COOKIE = "grp_csrf"
CSRF_HEADER = "X-CSRF-Token"
AUTH_TRANSACTION_COOKIE = "grp_auth_transaction"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass(frozen=True)
class CurrentPrincipal:
    user_id: UUID
    email: str
    display_name: str | None
    is_platform_admin: bool
    memberships: tuple[MembershipView, ...]
    issued_at: int
    session_id: str


def _serializer(settings: Settings, salt: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(read_secret(settings.session_secret_file), salt=salt)


def secure_cookie(settings: Settings) -> bool:
    return settings.grp_public_base_url.startswith("https://")


def csrf_token(settings: Settings, session_id: str) -> str:
    """Derive the per-session CSRF token; it is useless without the HttpOnly session cookie."""

    key = read_secret(settings.session_secret_file).encode()
    return hmac.new(key, f"grp-csrf-v1:{session_id}".encode(), hashlib.sha256).hexdigest()


def encode_auth_transaction(settings: Settings, transaction: dict[str, str]) -> str:
    return _serializer(settings, "grp-auth-transaction-v1").dumps(transaction)


def decode_auth_transaction(settings: Settings, value: str) -> dict[str, str]:
    try:
        data = _serializer(settings, "grp-auth-transaction-v1").loads(value, max_age=600)
    except (BadSignature, SignatureExpired) as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid login state"
        ) from error
    if not isinstance(data, dict) or not all(isinstance(key, str) for key in data):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid login state")
    return {str(key): str(value) for key, value in data.items()}


def decode_session_cookie(settings: Settings, value: str) -> dict[str, str]:
    try:
        data = _serializer(settings, "grp-session-v1").loads(
            value, max_age=settings.session_idle_minutes * 60
        )
        if not isinstance(data, dict):
            raise ValueError("session payload is not an object")
        return {
            "user_id": str(data["user_id"]),
            "issued_at": str(data["issued_at"]),
            "session_id": str(data["session_id"]),
        }
    except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError) as error:
        raise not_signed_in() from error


def set_session_cookie(
    response: Response,
    settings: Settings,
    result: IdentityLinkResult,
    *,
    issued_at: int | None = None,
    session_id: str | None = None,
) -> None:
    if result.user_id is None:
        raise ValueError("An allowed identity result must contain a user ID")
    session_id = session_id or str(uuid4())
    value = _serializer(settings, "grp-session-v1").dumps(
        {
            "user_id": str(result.user_id),
            "issued_at": issued_at or int(datetime.now(UTC).timestamp()),
            "session_id": session_id,
        }
    )
    response.set_cookie(
        SESSION_COOKIE,
        value,
        max_age=settings.session_idle_minutes * 60,
        httponly=True,
        secure=secure_cookie(settings),
        samesite="lax",
        path="/",
    )
    # Readable by same-origin scripts so they can echo it in the CSRF header (Section 13.1).
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token(settings, session_id),
        max_age=settings.session_idle_minutes * 60,
        httponly=False,
        secure=secure_cookie(settings),
        samesite="strict",
        path="/",
    )


def clear_session_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


def revoke_user_sessions(user: AppUser, now: datetime | None = None) -> None:
    """End every GRP session of this person issued up to now (sign-out, role or access change)."""

    user.sessions_valid_after = now or datetime.now(UTC)


def _session_revoked(user: AppUser, issued_at: int) -> bool:
    if user.sessions_valid_after is None:
        return False
    valid_after = user.sessions_valid_after
    if valid_after.tzinfo is None:
        valid_after = valid_after.replace(tzinfo=UTC)
    return issued_at <= int(valid_after.timestamp())


def load_principal(request: Request, session: Session, settings: Settings) -> CurrentPrincipal:
    value = request.cookies.get(SESSION_COOKIE)
    if not value:
        raise not_signed_in()
    data = decode_session_cookie(settings, value)
    try:
        issued_at = int(data["issued_at"])
        user_id = UUID(data["user_id"])
    except (KeyError, TypeError, ValueError) as error:
        raise not_signed_in() from error
    session_id = data["session_id"]
    age = int(datetime.now(UTC).timestamp()) - issued_at
    if age < 0 or age > settings.session_max_hours * 3600:
        raise not_signed_in()
    if request.method.upper() not in SAFE_METHODS:
        supplied = request.headers.get(CSRF_HEADER, "")
        if not supplied or not hmac.compare_digest(supplied, csrf_token(settings, session_id)):
            raise GrpError(403, "ACCESS_NOT_AUTHORIZED", "Access not authorized.")
    limiter.check(
        "api_requests_per_person_per_minute",
        str(user_id),
        settings.rate_limits["api_requests_per_person_per_minute"],
        60,
    )
    user = session.get(AppUser, user_id)
    if user is not None and _session_revoked(user, issued_at):
        raise not_signed_in()
    if user is None or user.status != UserStatus.ACTIVE:
        raise access_not_authorized()
    memberships = load_active_memberships(session, user.id)
    if not memberships and not user.is_platform_admin:
        raise access_not_authorized()
    return CurrentPrincipal(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_platform_admin=user.is_platform_admin,
        memberships=memberships,
        issued_at=issued_at,
        session_id=session_id,
    )
