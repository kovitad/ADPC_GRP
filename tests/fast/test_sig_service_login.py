"""Section 9.6: the SIG service role reads evidence with its own machine login only."""

import hashlib
from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import api.integrations.sig as sig
from api.dependencies import database_session
from api.main import app
from api.rate_limits import limiter
from api.settings import Settings
from core.access_models import AuditEvent, Base
from grp.admin import rotate_sig_service_token


@pytest.fixture
def sig_app(tmp_path, monkeypatch) -> Iterator[tuple]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    hash_file = tmp_path / "sig_service_token_hash"
    with Session(engine) as session:
        token = rotate_sig_service_token(session, hash_file)
        session.commit()
    settings = Settings(_env_file=None, sig_service_token_hash_file=hash_file)
    monkeypatch.setattr(sig, "get_settings", lambda: settings)

    def test_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[database_session] = test_session
    limiter.reset()
    try:
        yield engine, token, hash_file, monkeypatch, settings
    finally:
        app.dependency_overrides.clear()
        limiter.reset()


def _evidence(client: TestClient, headers: dict[str, str] | None = None):
    return client.get(f"/api/v1/integrations/sig/assessments/{uuid4()}/evidence", headers=headers)


def test_rotation_stores_only_a_hash_and_logs(sig_app) -> None:
    engine, token, hash_file, *_ = sig_app
    stored = hash_file.read_text(encoding="utf-8").strip()

    assert token not in stored
    assert stored == hashlib.sha256(token.encode()).hexdigest()
    with Session(engine) as session:
        assert session.scalar(select(AuditEvent.action)) == "credential_rotated"


def test_valid_service_token_reaches_endpoint_and_private_results_are_404(sig_app) -> None:
    engine, token, *_ = sig_app
    response = _evidence(TestClient(app), {"Authorization": f"Bearer {token}"})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    with Session(engine) as session:
        assert "sig_evidence_read" in set(session.scalars(select(AuditEvent.action)))


@pytest.mark.parametrize(
    "headers",
    [
        None,
        {"Authorization": "Bearer " + "x" * 64},
        {"Authorization": "Basic abc"},
        {"Authorization": "Bearer short"},
    ],
    ids=["missing", "wrong-token", "wrong-scheme", "too-short"],
)
def test_wrong_or_missing_service_token_is_denied(sig_app, headers) -> None:
    assert _evidence(TestClient(app), headers).status_code == 401


def test_ip_allowlist_blocks_other_callers(sig_app) -> None:
    _, token, hash_file, monkeypatch, _ = sig_app
    restricted = Settings(
        _env_file=None, sig_service_token_hash_file=hash_file, sig_allowed_ips=["203.0.113.9"]
    )
    monkeypatch.setattr(sig, "get_settings", lambda: restricted)

    response = _evidence(TestClient(app), {"Authorization": f"Bearer {token}"})

    assert response.status_code == 403


def test_service_reads_are_rate_limited(sig_app) -> None:
    _, token, *_ = sig_app
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {token}"}
    statuses = [_evidence(client, headers).status_code for _ in range(31)]

    assert statuses[:30] == [404] * 30
    assert statuses[30] == 429
