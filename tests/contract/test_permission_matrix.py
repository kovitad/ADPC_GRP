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
import api.ai
import api.auth
import api.data_inspector
import api.integrations.sig
import api.permissions
import api.platform
from api.dependencies import database_session
from api.main import app
from api.rate_limits import limiter
from api.sessions import CSRF_COOKIE, set_session_cookie
from api.settings import Settings
from core.access_models import AppUser, Base, HubMembership
from core.identity import IdentityLinkResult
from grpcli.admin import assign_member, bootstrap_platform_admin, ensure_hub

ACTORS = ("anonymous", "planner", "hub_admin", "other_hub_admin", "platform_admin")

# route key -> expected status per actor, in ACTORS order.
MATRIX = {
    "list_administered_hubs": (401, 200, 200, 200, 200),
    "list_members": (401, 403, 200, 404, 200),
    "add_member": (401, 403, 200, 404, 200),
    "change_member": (401, 403, 200, 404, 200),
    "access_message": (401, 403, 200, 404, 200),
    "my_ai_usage": (401, 200, 200, 200, 200),
    "hub_security_log": (401, 403, 200, 200, 200),
    "read_ai_setting": (401, 403, 403, 403, 200),
    "change_ai_setting": (401, 403, 403, 403, 200),
    "people_ai_usage": (401, 403, 403, 403, 200),
    "reset_ai_usage": (401, 403, 403, 403, 200),
    "list_all_hubs": (401, 403, 403, 403, 200),
    "create_hub": (401, 403, 403, 403, 200),
    "change_hub_status": (401, 403, 403, 403, 200),
    "platform_health": (401, 403, 403, 403, 200),
    # Human sessions are never the SIG service, whoever they are.
    "sig_evidence_with_session": (401, 401, 401, 401, 401),
    # ADR-0006: the data inspector is for Admins. A Hub Expert or Planner is not one.
    "source_folders": (401, 403, 200, 200, 200),
    "ask_for_inspection": (401, 403, 200, 200, 200),
    "ask_for_preview": (401, 403, 200, 200, 200),
    # No picture exists for a made-up id: allowed callers get 404, the rest are refused first.
    "preview_flood_picture": (401, 403, 404, 404, 404),
}


@pytest.fixture(scope="module")
def world(tmp_path_factory) -> Iterator[dict]:
    secret = tmp_path_factory.mktemp("secrets") / "session_secret"
    secret.write_text("contract-session-secret-with-enough-length", encoding="utf-8")
    data_in = tmp_path_factory.mktemp("data-in")
    (data_in / "notes.txt").write_text("a file, so the folder is not empty", encoding="utf-8")
    for folder in (
        "administrative_boundary/district_boundary",
        "evacuation_centers/shelters",
        "floods/flood_depth_rp100",
    ):
        (data_in / folder).mkdir(parents=True)
        (data_in / folder / "placeholder.txt").write_text("x", encoding="utf-8")
    settings = Settings(
        _env_file=None,
        session_secret_file=secret,
        data_inspector_enabled=True,
        data_in_root=data_in,
    )
    patch = pytest.MonkeyPatch()
    for module in (
        api.access, api.admin, api.ai, api.auth, api.integrations.sig,
        api.permissions, api.platform, api.data_inspector,
    ):
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
    if route == "access_message":
        return client.get(f"/api/v1/admin/hubs/adpc/members/{member}/access-message")
    user_id = world["users"]["planner"]
    requests = {
        "my_ai_usage": ("GET", "/api/v1/me/ai-usage", None),
        "hub_security_log": ("GET", "/api/v1/admin/audit-events", None),
        "read_ai_setting": ("GET", "/api/v1/platform/ai-usage/setting", None),
        "change_ai_setting": (
            "PUT",
            "/api/v1/platform/ai-usage/setting",
            {"token_limit_per_person": 200000, "ai_enabled": False},
        ),
        "people_ai_usage": ("GET", "/api/v1/platform/ai-usage/people", None),
        "reset_ai_usage": ("POST", f"/api/v1/platform/ai-usage/people/{user_id}/reset", None),
        "list_all_hubs": ("GET", "/api/v1/platform/hubs", None),
        "create_hub": ("POST", "/api/v1/platform/hubs", {"code": "adpc", "name": "adpc Hub"}),
        "change_hub_status": ("PATCH", "/api/v1/platform/hubs/adpc", {"status": "active"}),
        "platform_health": ("GET", "/api/v1/platform/health", None),
        "sig_evidence_with_session": (
            "GET",
            f"/api/v1/integrations/sig/assessments/{user_id}/evidence",
            None,
        ),
        "source_folders": ("GET", "/api/v1/data-inspector/folders", None),
        "ask_for_inspection": ("POST", "/api/v1/data-inspector/inspections", {"folder": ""}),
        "ask_for_preview": ("POST", "/api/v1/data-inspector/previews", {"district": "Pua"}),
        "preview_flood_picture": (
            "GET",
            f"/api/v1/data-inspector/previews/{user_id}/flood.png",
            None,
        ),
    }
    method, path, body = requests[route]
    return client.request(method, path, json=body, headers=headers)


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
