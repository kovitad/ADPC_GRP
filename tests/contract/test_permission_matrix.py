"""GRP-ARC-001 Section 9.4 permission matrix for the routes that exist today.

Requests go through the real session cookie, CSRF check, rate limiter and database
membership lookup; nothing is overridden except the database and settings.
"""

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
import api.auth
from api.dependencies import database_session
from api.main import app
from api.rate_limits import limiter
from api.sessions import CSRF_COOKIE, set_session_cookie
from api.settings import Settings
from core.access_models import AppUser, Base, HubMembership
from core.identity import IdentityLinkResult
from grp.admin import assign_member, bootstrap_platform_admin, ensure_hub

ACTORS = ("anonymous", "planner", "hub_admin", "other_hub_admin", "platform_admin")

# route key -> expected status per actor, in ACTORS order.
MATRIX = {
    "list_access_requests": (401, 403, 403, 403, 200),
    "list_administered_hubs": (401, 200, 200, 200, 200),
    "list_members": (401, 403, 200, 404, 200),
    "add_member": (401, 403, 200, 404, 200),
    "change_member": (401, 403, 200, 404, 200),
    "access_message": (401, 403, 200, 404, 200),
}


@pytest.fixture(scope="module")
def world(tmp_path_factory) -> Iterator[dict]:
    secret = tmp_path_factory.mktemp("secrets") / "session_secret"
    secret.write_text("contract-session-secret-with-enough-length", encoding="utf-8")
    settings = Settings(_env_file=None, session_secret_file=secret)
    patch = pytest.MonkeyPatch()
    for module in (api.access, api.admin, api.auth):
        patch.setattr(module, "get_settings", lambda: settings)

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        bootstrap_platform_admin(session, "owner@example.test")
        for code in ("adpc", "other"):
            ensure_hub(session, actor_email="owner@example.test", code=code, name=f"{code} Hub")
        for email, hub, role in (
            ("planner@example.test", "adpc", "planner"),
            ("hub-admin@example.test", "adpc", "admin"),
            ("other-admin@example.test", "other", "admin"),
        ):
            assign_member(
                session, actor_email="owner@example.test", email=email, hub_code=hub, role=role
            )
        session.commit()
        users = {user.email: user.id for user in session.scalars(select(AppUser))}
        planner_membership = session.scalar(
            select(HubMembership.id).where(
                HubMembership.user_id == users["planner@example.test"]
            )
        )

    def test_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[database_session] = test_session
    try:
        yield {
            "settings": settings,
            "users": {
                "planner": users["planner@example.test"],
                "hub_admin": users["hub-admin@example.test"],
                "other_hub_admin": users["other-admin@example.test"],
                "platform_admin": users["owner@example.test"],
            },
            "planner_membership": planner_membership,
        }
    finally:
        app.dependency_overrides.clear()
        patch.undo()


def _client(world: dict, actor: str) -> tuple[TestClient, dict[str, str]]:
    client = TestClient(app)
    if actor == "anonymous":
        return client, {}
    response = Response()
    set_session_cookie(
        response,
        world["settings"],
        IdentityLinkResult(allowed=True, reason="allowed", user_id=world["users"][actor]),
        issued_at=int(datetime.now(UTC).timestamp()) - 5,
    )
    for header in response.headers.getlist("set-cookie"):
        name, value = header.split(";", 1)[0].split("=", 1)
        client.cookies.set(name, value)
    return client, {"X-CSRF-Token": client.cookies[CSRF_COOKIE]}


def _call(client: TestClient, headers: dict[str, str], route: str, world: dict, actor: str):
    member = world["planner_membership"]
    if route == "list_access_requests":
        return client.get("/api/v1/admin/access-requests")
    if route == "list_administered_hubs":
        return client.get("/api/v1/admin/hubs")
    if route == "list_members":
        return client.get("/api/v1/admin/hubs/adpc/members")
    if route == "add_member":
        return client.post(
            "/api/v1/admin/hubs/adpc/members",
            json={"email": f"added-by-{actor}@example.test", "role": "planner"},
            headers=headers,
        )
    if route == "change_member":
        # Same values: exercises authorization without revoking the planner's session.
        return client.patch(
            f"/api/v1/admin/hubs/adpc/members/{member}",
            json={"role": "planner", "status": "active"},
            headers=headers,
        )
    return client.get(f"/api/v1/admin/hubs/adpc/members/{member}/access-message")


@pytest.mark.contract
@pytest.mark.parametrize("route", sorted(MATRIX))
@pytest.mark.parametrize("actor", ACTORS)
def test_permission_matrix(world, route: str, actor: str) -> None:
    limiter.reset()
    client, headers = _client(world, actor)

    response = _call(client, headers, route, world, actor)

    expected = MATRIX[route][ACTORS.index(actor)]
    assert response.status_code == expected, response.text
    if expected >= 400:
        assert set(response.json()["error"]) == {"code", "message", "support_ref"}


@pytest.mark.contract
def test_hub_admin_sees_only_own_hub(world) -> None:
    limiter.reset()
    client, _ = _client(world, "hub_admin")

    hubs = client.get("/api/v1/admin/hubs").json()["hubs"]
    unknown = client.get("/api/v1/admin/hubs/missing/members")

    message = client.get(
        f"/api/v1/admin/hubs/adpc/members/{world['planner_membership']}/access-message"
    ).json()["message"]

    assert [hub["code"] for hub in hubs] == ["adpc"]
    assert world["settings"].grp_public_base_url in message
    assert unknown.status_code == 404


@pytest.mark.contract
def test_person_is_rate_limited_after_sixty_requests_a_minute(world) -> None:
    limiter.reset()
    client, _ = _client(world, "planner")

    statuses = [client.get("/api/v1/me").status_code for _ in range(61)]
    limiter.reset()

    assert statuses[:60] == [200] * 60
    assert statuses[60] == 429
