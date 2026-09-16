from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import Response
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import api.access
import api.admin
import api.auth
from api.dependencies import database_session
from api.main import app
from api.sessions import CSRF_COOKIE, SESSION_COOKIE, set_session_cookie
from api.settings import Settings
from core.access_models import AppUser, Base, HubMembership
from core.identity import IdentityLinkResult
from grp.admin import assign_member, bootstrap_platform_admin, ensure_hub


@pytest.fixture
def secured_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple]:
    secret = tmp_path / "session_secret"
    secret.write_text("test-session-secret-with-enough-length", encoding="utf-8")
    settings = Settings(session_secret_file=secret)
    for module in (api.access, api.admin, api.auth):
        monkeypatch.setattr(module, "get_settings", lambda: settings)

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        bootstrap_platform_admin(session, "owner@example.test")
        ensure_hub(session, actor_email="owner@example.test", code="adpc", name="ADPC Hub")
        assign_member(
            session,
            actor_email="owner@example.test",
            email="planner@example.test",
            hub_code="adpc",
            role="planner",
        )
        session.commit()

    def test_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[database_session] = test_session
    try:
        yield settings, engine
    finally:
        app.dependency_overrides.clear()


def _signed_in_client(settings: Settings, engine, email: str, issued_at: int) -> TestClient:
    with Session(engine) as session:
        user_id = session.scalar(select(AppUser.id).where(AppUser.email == email))
    response = Response()
    set_session_cookie(
        response,
        settings,
        IdentityLinkResult(allowed=True, reason="allowed", user_id=user_id),
        issued_at=issued_at,
    )
    client = TestClient(app)
    for header in response.headers.getlist("set-cookie"):
        name, value = header.split(";", 1)[0].split("=", 1)
        client.cookies.set(name, value)
    return client


def _now() -> int:
    from datetime import UTC, datetime

    return int(datetime.now(UTC).timestamp())


def test_state_changing_request_requires_csrf_token(secured_app) -> None:
    settings, engine = secured_app
    client = _signed_in_client(settings, engine, "owner@example.test", _now() - 5)
    body = {"email": "new@example.test", "role": "planner"}

    missing = client.post("/api/v1/admin/hubs/adpc/members", json=body)
    wrong = client.post(
        "/api/v1/admin/hubs/adpc/members", json=body, headers={"X-CSRF-Token": "forged"}
    )
    accepted = client.post(
        "/api/v1/admin/hubs/adpc/members",
        json=body,
        headers={"X-CSRF-Token": client.cookies[CSRF_COOKIE]},
    )

    assert missing.status_code == 403
    assert missing.json()["error"]["code"] == "ACCESS_NOT_AUTHORIZED"
    assert wrong.status_code == 403
    assert accepted.status_code == 200
    # Reads stay usable without the header.
    assert client.get("/api/v1/me").status_code == 200


def test_role_change_ends_the_affected_persons_session(secured_app) -> None:
    settings, engine = secured_app
    owner = _signed_in_client(settings, engine, "owner@example.test", _now() - 5)
    planner = _signed_in_client(settings, engine, "planner@example.test", _now() - 5)
    with Session(engine) as session:
        membership_id = session.scalar(
            select(HubMembership.id)
            .join(AppUser, AppUser.id == HubMembership.user_id)
            .where(AppUser.email == "planner@example.test")
        )
    assert planner.get("/api/v1/me").status_code == 200

    changed = owner.patch(
        f"/api/v1/admin/hubs/adpc/members/{membership_id}",
        json={"role": "admin"},
        headers={"X-CSRF-Token": owner.cookies[CSRF_COOKIE]},
    )

    assert changed.status_code == 200
    after = planner.get("/api/v1/me")
    assert after.status_code == 401
    assert after.json()["error"]["code"] == "NOT_SIGNED_IN"
    assert owner.get("/api/v1/me").status_code == 200


def test_sign_out_revokes_a_copied_session_cookie(secured_app) -> None:
    settings, engine = secured_app
    client = _signed_in_client(settings, engine, "planner@example.test", _now() - 5)
    copied = client.cookies[SESSION_COOKIE]

    forged = client.post("/api/v1/auth/logout")
    signed_out = client.post(
        "/api/v1/auth/logout", headers={"X-CSRF-Token": client.cookies[CSRF_COOKIE]}
    )
    replay = TestClient(app)
    replay.cookies.set(SESSION_COOKIE, copied)

    assert forged.status_code == 403
    assert signed_out.status_code == 200
    assert replay.get("/api/v1/me").status_code == 401
