from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import HTTPException, Request, Response, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from api.settings import Settings
from core.access_models import AppUser, UserStatus
from core.db import read_secret
from core.identity import IdentityLinkResult, MembershipView, load_active_memberships

SESSION_COOKIE = "grp_session"
AUTH_TRANSACTION_COOKIE = "grp_auth_transaction"


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
    value = _serializer(settings, "grp-session-v1").dumps(
        {
            "user_id": str(result.user_id),
            "issued_at": issued_at or int(datetime.now(UTC).timestamp()),
            "session_id": session_id or str(uuid4()),
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


def load_principal(request: Request, session: Session, settings: Settings) -> CurrentPrincipal:
    value = request.cookies.get(SESSION_COOKIE)
    if not value:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Please sign in")
    try:
        data = _serializer(settings, "grp-session-v1").loads(
            value, max_age=settings.session_idle_minutes * 60
        )
        issued_at = int(data["issued_at"])
        user_id = UUID(str(data["user_id"]))
        session_id = str(data["session_id"])
    except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired"
        ) from error
    age = int(datetime.now(UTC).timestamp()) - issued_at
    if age < 0 or age > settings.session_max_hours * 3600:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
    user = session.get(AppUser, user_id)
    if user is None or user.status != UserStatus.ACTIVE:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access not authorized")
    memberships = load_active_memberships(session, user.id)
    if not memberships and not user.is_platform_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access not authorized")
    return CurrentPrincipal(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_platform_admin=user.is_platform_admin,
        memberships=memberships,
        issued_at=issued_at,
        session_id=session_id,
    )
