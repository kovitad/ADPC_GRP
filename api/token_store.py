from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Lock

MAX_TOKENS = 500


@dataclass(frozen=True)
class SessionAccessToken:
    value: str
    expires_at: datetime


class SessionTokenStore:
    """Keep short-lived upstream tokens in process memory, never in cookies or the database."""

    def __init__(self) -> None:
        self._tokens: dict[str, SessionAccessToken] = {}
        self._lock = Lock()

    def put(self, session_id: str, value: str, expires_in: int) -> None:
        safe_lifetime = max(60, min(expires_in, 12 * 60 * 60))
        token = SessionAccessToken(
            value=value,
            expires_at=datetime.now(UTC) + timedelta(seconds=safe_lifetime),
        )
        with self._lock:
            now = datetime.now(UTC)
            for key in [key for key, item in self._tokens.items() if item.expires_at <= now]:
                del self._tokens[key]
            if len(self._tokens) >= MAX_TOKENS and session_id not in self._tokens:
                # Drop the token closest to expiry; that person simply signs in again.
                del self._tokens[min(self._tokens, key=lambda key: self._tokens[key].expires_at)]
            self._tokens[session_id] = token

    def get(self, session_id: str) -> str | None:
        with self._lock:
            token = self._tokens.get(session_id)
            if token is None:
                return None
            if token.expires_at <= datetime.now(UTC):
                self._tokens.pop(session_id, None)
                return None
            return token.value

    def delete(self, session_id: str) -> None:
        with self._lock:
            self._tokens.pop(session_id, None)


session_token_store = SessionTokenStore()
