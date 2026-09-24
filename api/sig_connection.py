"""Keep a session's SIG connection usable by renewing the access token before it dies.

The SIG access token is short-lived (commonly one hour) while a GRP session lasts up to
`session_max_hours`. Without renewal the planner is told to sign in again part-way through a
session even though nothing is wrong with the GRP session. ADR-0017 records the decision.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Lock

from api.oidc import IdentityProviderError, ServirSigIdentityProvider
from api.settings import Settings
from api.token_store import SessionAccessToken, session_token_store

# Renew a little before expiry so a lookup that takes a few seconds never starts on a token
# that dies mid-call.
RENEW_SKEW_SECONDS = 120
MAX_RENEWAL_LOCKS = 500

_renewal_locks: dict[str, asyncio.Lock] = {}
_renewal_locks_guard = Lock()


@dataclass(frozen=True)
class SigConnection:
    """What the caller needs to decide between running a lookup and asking for a sign-in."""

    access_token: str | None
    expires_in_seconds: int | None
    renewable: bool

    @property
    def connected(self) -> bool:
        return self.access_token is not None


DISCONNECTED = SigConnection(access_token=None, expires_in_seconds=None, renewable=False)


def _renewal_lock(session_id: str) -> asyncio.Lock:
    with _renewal_locks_guard:
        lock = _renewal_locks.get(session_id)
        if lock is None:
            if len(_renewal_locks) >= MAX_RENEWAL_LOCKS:
                # Only locks nobody holds can be dropped, or two requests could renew at once.
                for key in [key for key, item in _renewal_locks.items() if not item.locked()]:
                    del _renewal_locks[key]
            lock = _renewal_locks.setdefault(session_id, asyncio.Lock())
        return lock


def _view(record: SessionAccessToken, moment: datetime) -> SigConnection:
    return SigConnection(
        access_token=record.value if record.usable_at(moment) else None,
        expires_in_seconds=record.seconds_remaining(moment),
        renewable=record.renewable_at(moment),
    )


async def _renew(
    settings: Settings, session_id: str, seen: SessionAccessToken
) -> SessionAccessToken | None:
    async with _renewal_lock(session_id):
        current = session_token_store.record(session_id)
        if current is None:
            return None
        now = datetime.now(UTC)
        if current.value != seen.value and current.usable_at(now):
            # Another request renewed it while this one waited for the lock.
            return current
        if not current.renewable_at(now) or current.refresh_token is None:
            return current
        provider: ServirSigIdentityProvider | None = None
        try:
            provider = ServirSigIdentityProvider(settings)
            renewed = await provider.renew_access_token(current.refresh_token)
        except (IdentityProviderError, OSError):
            # Fail soft: the person keeps whatever life the current token has left, and the
            # planning page then asks for a sign-in rather than showing a server error.
            return session_token_store.record(session_id)
        finally:
            if provider is not None:
                await provider.close()
        session_token_store.renew(
            session_id,
            renewed.access_token,
            renewed.expires_in,
            renewed.refresh_token or current.refresh_token,
        )
        return session_token_store.record(session_id)


async def sig_connection(settings: Settings, session_id: str) -> SigConnection:
    """Report the session's SIG connection, renewing the access token first when it is due."""

    record = session_token_store.record(session_id)
    if record is None:
        return DISCONNECTED
    now = datetime.now(UTC)
    due = record.expires_at - timedelta(seconds=RENEW_SKEW_SECONDS)
    if due > now or not record.renewable_at(now):
        return _view(record, now)
    renewed = await _renew(settings, session_id, record)
    if renewed is None:
        return DISCONNECTED
    return _view(renewed, datetime.now(UTC))


async def sig_access_token(settings: Settings, session_id: str) -> str | None:
    """The access token to call SIG with right now, or None when a sign-in is needed."""

    return (await sig_connection(settings, session_id)).access_token


def forget(session_id: str) -> None:
    """Drop the session's token, its renewal lock and any lookup it started, at sign-out."""

    from api.sig_jobs import sig_lookups

    session_token_store.delete(session_id)
    sig_lookups.forget_session(session_id)
    with _renewal_locks_guard:
        lock = _renewal_locks.get(session_id)
        if lock is not None and not lock.locked():
            del _renewal_locks[session_id]
