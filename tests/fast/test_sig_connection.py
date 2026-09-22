"""The SIG connection renews itself while a GRP session lasts (ADR-0017)."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from api import sig_connection
from api.oidc import IdentityProviderError, RenewedAccessToken
from api.settings import Settings
from api.token_store import SessionAccessToken, session_token_store

SETTINGS = Settings(_env_file=None, grp_env="dev")


class FakeProvider:
    """Stands in for the SERVIR provider; counts renewals and can be told to fail."""

    calls: list[str] = []
    fail = False

    def __init__(self, settings) -> None:
        self.settings = settings

    async def renew_access_token(self, refresh_token: str) -> RenewedAccessToken:
        FakeProvider.calls.append(refresh_token)
        if FakeProvider.fail:
            raise IdentityProviderError("SERVIR access token could not be renewed")
        await asyncio.sleep(0)
        return RenewedAccessToken(
            access_token="renewed-access-token",
            expires_in=3600,
            refresh_token="rotated-refresh-token",
        )

    async def close(self) -> None:
        return None


@pytest.fixture(autouse=True)
def provider(monkeypatch):
    FakeProvider.calls = []
    FakeProvider.fail = False
    monkeypatch.setattr(sig_connection, "ServirSigIdentityProvider", FakeProvider)
    yield FakeProvider
    for session_id in list(session_token_store._tokens):
        sig_connection.forget(session_id)


def _store(session_id: str, *, expires_in: int, refresh_token: str | None, renewable_in: int):
    """Place a record directly so a test can describe a token that is already expired."""

    now = datetime.now(UTC)
    session_token_store._tokens[session_id] = SessionAccessToken(
        value="original-access-token",
        expires_at=now + timedelta(seconds=expires_in),
        refresh_token=refresh_token,
        renewable_until=now + timedelta(seconds=renewable_in) if refresh_token else None,
    )


def test_token_close_to_expiry_is_renewed_before_the_lookup_runs() -> None:
    _store("session-a", expires_in=30, refresh_token="refresh-1", renewable_in=3600)

    token = asyncio.run(sig_connection.sig_access_token(SETTINGS, "session-a"))

    assert token == "renewed-access-token"
    assert FakeProvider.calls == ["refresh-1"]
    stored = session_token_store.record("session-a")
    assert stored.value == "renewed-access-token"
    # The rotated refresh token replaces the used one, or the next renewal is refused.
    assert stored.refresh_token == "rotated-refresh-token"


def test_expired_token_is_renewed_rather_than_forcing_a_sign_in() -> None:
    _store("session-b", expires_in=-10, refresh_token="refresh-2", renewable_in=3600)

    connection = asyncio.run(sig_connection.sig_connection(SETTINGS, "session-b"))

    assert connection.connected and connection.access_token == "renewed-access-token"
    assert connection.expires_in_seconds > 3000


def test_healthy_token_is_not_renewed() -> None:
    _store("session-c", expires_in=3600, refresh_token="refresh-3", renewable_in=3600)

    connection = asyncio.run(sig_connection.sig_connection(SETTINGS, "session-c"))

    assert connection.access_token == "original-access-token"
    assert connection.renewable is True
    assert FakeProvider.calls == []


def test_a_failed_renewal_keeps_whatever_life_the_token_has_left() -> None:
    FakeProvider.fail = True
    _store("session-d", expires_in=30, refresh_token="refresh-4", renewable_in=3600)

    connection = asyncio.run(sig_connection.sig_connection(SETTINGS, "session-d"))

    assert connection.access_token == "original-access-token"
    assert connection.expires_in_seconds <= 30


def test_expired_token_with_no_refresh_token_asks_for_a_sign_in() -> None:
    _store("session-e", expires_in=-10, refresh_token=None, renewable_in=0)

    connection = asyncio.run(sig_connection.sig_connection(SETTINGS, "session-e"))

    assert connection.connected is False and connection.access_token is None
    assert FakeProvider.calls == []


def test_renewal_never_outlives_the_grp_session() -> None:
    _store("session-f", expires_in=-10, refresh_token="refresh-6", renewable_in=-1)

    connection = asyncio.run(sig_connection.sig_connection(SETTINGS, "session-f"))

    assert connection.connected is False
    assert FakeProvider.calls == []


def test_two_lookups_at_once_renew_only_once() -> None:
    _store("session-g", expires_in=30, refresh_token="refresh-7", renewable_in=3600)

    async def both() -> list[str | None]:
        return list(
            await asyncio.gather(
                sig_connection.sig_access_token(SETTINGS, "session-g"),
                sig_connection.sig_access_token(SETTINGS, "session-g"),
            )
        )

    assert asyncio.run(both()) == ["renewed-access-token", "renewed-access-token"]
    assert FakeProvider.calls == ["refresh-7"]


def test_unknown_session_is_not_connected() -> None:
    connection = asyncio.run(sig_connection.sig_connection(SETTINGS, "session-none"))

    assert connection == sig_connection.DISCONNECTED
    assert FakeProvider.calls == []


def test_forget_drops_the_token_and_its_renewal_lock() -> None:
    _store("session-h", expires_in=3600, refresh_token="refresh-8", renewable_in=3600)
    sig_connection._renewal_lock("session-h")

    sig_connection.forget("session-h")

    assert session_token_store.record("session-h") is None
    assert "session-h" not in sig_connection._renewal_locks
