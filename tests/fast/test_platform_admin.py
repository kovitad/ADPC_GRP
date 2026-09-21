"""Platform Admin functions: Hub close/reopen, AI setting, AI test call, manual reset."""

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi import Response
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import api.access
import api.admin
import api.ai
import api.ai_gateway
import api.auth
import api.permissions
import api.platform
from api.dependencies import database_session
from api.main import app
from api.rate_limits import limiter
from api.sessions import CSRF_COOKIE, set_session_cookie
from api.settings import Settings
from core.access_models import AppUser, AuditEvent, Base
from core.identity import IdentityLinkResult
from grpcli.admin import assign_member, bootstrap_platform_admin, ensure_hub


@pytest.fixture
def platform(tmp_path, monkeypatch) -> Iterator[dict]:
    secret = tmp_path / "session_secret"
    secret.write_text("platform-session-secret-with-enough-length", encoding="utf-8")
    settings = Settings(
        _env_file=None, session_secret_file=secret, ai_feature_enabled=True, ai_model="test-model"
    )
    for module in (api.access, api.admin, api.ai, api.auth, api.permissions, api.platform):
        monkeypatch.setattr(module, "get_settings", lambda: settings)
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        bootstrap_platform_admin(session, "owner@example.test")
        ensure_hub(session, actor_email="owner@example.test", code="adpc", name="ADPC Hub")
        assign_member(session, actor_email="owner@example.test", email="planner@example.test",
                      hub_code="adpc", role="planner")
        session.commit()
        users = {user.email: user.id for user in session.scalars(select(AppUser))}

    def test_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[database_session] = test_session
    limiter.reset()
    try:
        yield {"settings": settings, "engine": engine, "users": users, "monkeypatch": monkeypatch}
    finally:
        app.dependency_overrides.clear()


def _client(world: dict, email: str) -> TestClient:
    response = Response()
    set_session_cookie(
        response,
        world["settings"],
        IdentityLinkResult(allowed=True, reason="allowed", user_id=world["users"][email]),
        issued_at=int(datetime.now(UTC).timestamp()) - 5,
    )
    client = TestClient(app)
    for header in response.headers.getlist("set-cookie"):
        name, value = header.split(";", 1)[0].split("=", 1)
        client.cookies.set(name, value)
    client.headers["X-CSRF-Token"] = client.cookies[CSRF_COOKIE]
    return client


def test_closing_a_hub_removes_member_access_and_reopening_restores_it(platform) -> None:
    owner = _client(platform, "owner@example.test")
    planner = _client(platform, "planner@example.test")
    assert planner.get("/api/v1/me").status_code == 200

    closed = owner.patch("/api/v1/platform/hubs/adpc", json={"status": "closed"})
    denied = planner.get("/api/v1/me")
    reopened = owner.patch("/api/v1/platform/hubs/adpc", json={"status": "active"})

    assert closed.json()["message"] == "Hub closed"
    assert denied.status_code == 403
    assert reopened.status_code == 200
    assert planner.get("/api/v1/me").status_code == 200


def test_create_hub_and_list(platform) -> None:
    owner = _client(platform, "owner@example.test")

    created = owner.post("/api/v1/platform/hubs", json={"code": "rcmrd", "name": "RCMRD Hub"})
    invalid = owner.post("/api/v1/platform/hubs", json={"code": "Bad Code!", "name": "X"})
    hubs = owner.get("/api/v1/platform/hubs").json()["hubs"]

    assert created.json()["changed"] is True
    assert invalid.status_code == 422
    assert [hub["code"] for hub in hubs] == ["adpc", "rcmrd"]


def test_ai_test_call_uses_allowance_and_admin_can_reset(platform) -> None:
    owner = _client(platform, "owner@example.test")
    planner = _client(platform, "planner@example.test")

    async def provider(settings, *, instructions, prompt, hub_code):
        return "Gateway works.", "test-model", 30, 10

    platform["monkeypatch"].setattr(api.ai_gateway, "call_openai", provider)

    off = owner.post("/api/v1/ai/test-call", json={})
    owner.put(
        "/api/v1/platform/ai-usage/setting",
        json={"token_limit_per_person": 1000, "ai_enabled": True},
    )
    called = owner.post("/api/v1/ai/test-call", json={"message": "ping"})
    planner_denied = planner.post("/api/v1/ai/test-call", json={})
    people = owner.get("/api/v1/platform/ai-usage/people").json()["people"]
    owner_row = next(row for row in people if row["email"] == "owner@example.test")
    reset = owner.post(f"/api/v1/platform/ai-usage/people/{owner_row['user_id']}/reset")
    after = owner.get("/api/v1/me/ai-usage").json()

    assert off.status_code == 403 and off.json()["error"]["code"] == "AI_OFF"
    assert called.status_code == 200
    assert called.json()["usage"]["tokens_used"] == 40
    assert planner_denied.status_code == 403
    assert owner_row["tokens_used"] == 40
    assert reset.json()["tokens_used_before"] == 40
    assert after["tokens_used"] == 0 and after["status"] == "active"
    with Session(platform["engine"]) as session:
        actions = set(session.scalars(select(AuditEvent.action)))
    assert {"ai_allowance_reset", "admin_viewed_usage", "ai_enabled_changed"} <= actions


def test_security_log_scoped_to_hub_admin(platform) -> None:
    owner = _client(platform, "owner@example.test")
    planner = _client(platform, "planner@example.test")

    all_events = owner.get("/api/v1/admin/audit-events").json()["events"]
    hub_events = owner.get("/api/v1/admin/audit-events?hub_code=adpc").json()["events"]

    assert {"platform_admin_bootstrapped", "member_added"} <= {e["action"] for e in all_events}
    assert {e["action"] for e in hub_events} <= {"hub_created", "member_added"}
    assert planner.get("/api/v1/admin/audit-events").status_code == 403
