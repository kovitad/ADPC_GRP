from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from threading import Lock

MAX_TOKENS = 500
MAX_ACCESS_SECONDS = 12 * 60 * 60


@dataclass(frozen=True)
class SessionAccessToken:
    """One person's upstream SIG token, with the refresh token that can renew it."""

    value: str
    expires_at: datetime
    refresh_token: str | None = None
    renewable_until: datetime | None = None

    def usable_at(self, moment: datetime) -> bool:
        return self.expires_at > moment

    def renewable_at(self, moment: datetime) -> bool:
        return bool(self.refresh_token) and self.renewable_until is not None and (
            self.renewable_until > moment
        )

    def seconds_remaining(self, moment: datetime) -> int:
        return max(0, int((self.expires_at - moment).total_seconds()))

    @property
    def retain_until(self) -> datetime:
        """When the record is worthless: the access token is dead and cannot be renewed."""

        if self.renewable_until is not None:
            return max(self.expires_at, self.renewable_until)
        return self.expires_at


class SessionTokenStore:
    """Keep short-lived upstream tokens in process memory, never in cookies or the database."""

    def __init__(self) -> None:
        self._tokens: dict[str, SessionAccessToken] = {}
        self._lock = Lock()

    def put(
        self,
        session_id: str,
        value: str,
        expires_in: int,
        *,
        refresh_token: str | None = None,
        renewable_for: int | None = None,
    ) -> None:
        now = datetime.now(UTC)
        safe_lifetime = max(60, min(expires_in, MAX_ACCESS_SECONDS))
        token = SessionAccessToken(
            value=value,
            expires_at=now + timedelta(seconds=safe_lifetime),
            refresh_token=refresh_token,
            # Renewal never outlives the GRP session it belongs to. Without a stated window
            # it lasts exactly as long as the access token, so renewal is simply never used.
            renewable_until=(
                now
                + timedelta(
                    seconds=max(
                        0,
                        min(
                            safe_lifetime if renewable_for is None else renewable_for,
                            MAX_ACCESS_SECONDS,
                        ),
                    )
                )
                if refresh_token
                else None
            ),
        )
        with self._lock:
            self._evict(now, keep=session_id)
            self._tokens[session_id] = token

    def renew(self, session_id: str, value: str, expires_in: int, refresh_token: str) -> None:
        """Replace the access token in place, keeping the session's original renewal window."""

        now = datetime.now(UTC)
        safe_lifetime = max(60, min(expires_in, MAX_ACCESS_SECONDS))
        with self._lock:
            existing = self._tokens.get(session_id)
            if existing is None:
                return
            self._tokens[session_id] = replace(
                existing,
                value=value,
                expires_at=now + timedelta(seconds=safe_lifetime),
                refresh_token=refresh_token,
            )

    def get(self, session_id: str) -> str | None:
        """The access token if it can be used right now, without renewing it."""

        record = self.record(session_id)
        if record is None or not record.usable_at(datetime.now(UTC)):
            return None
        return record.value

    def record(self, session_id: str) -> SessionAccessToken | None:
        """The stored token, including an expired one that a refresh token can still renew."""

        with self._lock:
            token = self._tokens.get(session_id)
            if token is None:
                return None
            if token.retain_until <= datetime.now(UTC):
                del self._tokens[session_id]
                return None
            return token

    def delete(self, session_id: str) -> None:
        with self._lock:
            self._tokens.pop(session_id, None)

    def _evict(self, now: datetime, *, keep: str) -> None:
        for key in [key for key, item in self._tokens.items() if item.retain_until <= now]:
            del self._tokens[key]
        if len(self._tokens) >= MAX_TOKENS and keep not in self._tokens:
            # Drop the token closest to being worthless; that person simply signs in again.
            del self._tokens[min(self._tokens, key=lambda key: self._tokens[key].retain_until)]


session_token_store = SessionTokenStore()
