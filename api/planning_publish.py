"""Short-lived, session-bound claims for publishing an already displayed SIG draft.

The browser may return this token, but it cannot alter the pack, question, draft or evidence
without invalidating the signature.  This lets ``publish_answer`` check the exact text the
person reviewed instead of running the model and evidence lookup a second time.
"""

from __future__ import annotations

from typing import Any

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from api.errors import GrpError
from api.settings import Settings
from core.db import read_secret

PUBLISH_TOKEN_MAX_AGE_SECONDS = 15 * 60


def _serializer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(
        read_secret(settings.session_secret_file), salt="grp-planning-publish-v1"
    )


def encode_publish_token(
    settings: Settings,
    *,
    user_id: str,
    session_id: str,
    hub_id: str,
    claims: dict[str, Any],
) -> str:
    return _serializer(settings).dumps(
        {
            "version": 1,
            "user_id": user_id,
            "session_id": session_id,
            "hub_id": hub_id,
            **claims,
        }
    )


def decode_publish_token(
    settings: Settings,
    token: str,
    *,
    user_id: str,
    session_id: str,
    hub_id: str,
) -> dict[str, Any]:
    try:
        claims = _serializer(settings).loads(token, max_age=PUBLISH_TOKEN_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired) as error:
        raise GrpError(
            409,
            "PUBLISH_DRAFT_EXPIRED",
            "This draft can no longer be published. Run the evidence check again.",
        ) from error
    if not isinstance(claims, dict) or any(
        claims.get(key) != expected
        for key, expected in {
            "version": 1,
            "user_id": user_id,
            "session_id": session_id,
            "hub_id": hub_id,
        }.items()
    ):
        raise GrpError(403, "ACCESS_NOT_AUTHORIZED", "Access not authorized.")
    required = ("pack_id", "question", "place", "draft", "area", "evidence")
    if (
        not all(key in claims for key in required)
        or not all(isinstance(claims[key], str) for key in required[:4])
        or not isinstance(claims["area"], dict)
        or not isinstance(claims["evidence"], dict)
    ):
        raise GrpError(
            409,
            "PUBLISH_DRAFT_EXPIRED",
            "This draft can no longer be published. Run the evidence check again.",
        )
    return claims
