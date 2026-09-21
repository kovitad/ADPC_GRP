from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api.admin import authenticated_user
from api.dependencies import database_session
from api.main import app
from api.planning_access import planner_membership
from api.sessions import CurrentPrincipal
from core.access_models import AppUser, Base, Hub, HubMembership
from core.identity import MembershipView, VerifiedIdentity, link_verified_identity
from grpcli.admin import assign_member, bootstrap_platform_admin, ensure_hub


def test_admin_access_queue_and_membership_assignment() -> None:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        bootstrap_platform_admin(session, "owner@example.test")
        ensure_hub(
            session,
            actor_email="owner@example.test",
            code="adpc",
            name="ADPC Hub",
        )
        link_verified_identity(
            session,
            VerifiedIdentity(
                issuer="https://identity.example.test",
                subject="pending-user",
                verified_email="expert@example.test",
                display_name="Example Expert",
            ),
        )
        owner_id = session.scalar(select(AppUser.id).where(AppUser.email == "owner@example.test"))
        assert owner_id is not None
        session.commit()

    def test_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    principal = CurrentPrincipal(
        user_id=owner_id,
        email="owner@example.test",
        display_name=None,
        is_platform_admin=True,
        memberships=(),
        issued_at=0,
        session_id=str(uuid4()),
    )
    app.dependency_overrides[database_session] = test_session
    app.dependency_overrides[authenticated_user] = lambda: principal
    try:
        client = TestClient(app)
        assigned = client.post(
            "/api/v1/admin/hubs/adpc/members",
            json={"email": "expert@example.test", "role": "hub_expert"},
        )
        ndmo = client.post(
            "/api/v1/admin/hubs/adpc/members",
            json={"email": "ndmo@example.test", "role": "ndmo_planner"},
        )
    finally:
        app.dependency_overrides.clear()

    assert assigned.status_code == 200
    assert assigned.json()["changed"] is True
    assert ndmo.status_code == 200
    assert ndmo.json()["changed"] is True
    assert "/api/v1/admin/access-requests" not in app.openapi()["paths"]


@pytest.mark.parametrize("role", ["ndmo_planner", "hub_expert"])
def test_new_planning_roles_can_access_their_own_hub(role: str) -> None:
    hub_id = uuid4()
    principal = CurrentPrincipal(
        user_id=uuid4(),
        email="member@example.test",
        display_name=None,
        is_platform_admin=False,
        memberships=(MembershipView(hub_id, "adpc", "ADPC Hub", role),),
        issued_at=0,
        session_id=str(uuid4()),
    )

    membership = planner_membership(principal, "adpc")

    assert membership.role == role


def test_hub_admin_can_manage_own_hub_but_cannot_remove_last_admin() -> None:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        bootstrap_platform_admin(session, "owner@example.test")
        ensure_hub(
            session,
            actor_email="owner@example.test",
            code="adpc",
            name="ADPC Hub",
        )
        assign_member(
            session,
            actor_email="owner@example.test",
            email="hub-admin@example.test",
            hub_code="adpc",
            role="admin",
        )
        hub_admin = session.scalar(
            select(AppUser).where(AppUser.email == "hub-admin@example.test")
        )
        membership = session.scalar(
            select(HubMembership).where(HubMembership.user_id == hub_admin.id)
        )
        session.commit()
        assert hub_admin is not None and membership is not None
        hub_admin_id = hub_admin.id
        membership_id = membership.id
        hub_id = membership.hub_id

    def test_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    principal = CurrentPrincipal(
        user_id=hub_admin_id,
        email="hub-admin@example.test",
        display_name="Hub Admin",
        is_platform_admin=False,
        memberships=(
            MembershipView(
                hub_id=hub_id,
                hub_code="adpc",
                hub_name="ADPC Hub",
                role="admin",
            ),
        ),
        issued_at=0,
        session_id=str(uuid4()),
    )
    app.dependency_overrides[database_session] = test_session
    app.dependency_overrides[authenticated_user] = lambda: principal
    try:
        client = TestClient(app)
        assigned = client.post(
            "/api/v1/admin/hubs/adpc/members",
            json={"email": "planner@example.test", "role": "planner"},
        )
        listed = client.get("/api/v1/admin/hubs/adpc/members")
        denied = client.patch(
            f"/api/v1/admin/hubs/adpc/members/{membership_id}",
            json={"status": "disabled"},
        )
        planner = next(
            member
            for member in listed.json()["members"]
            if member["email"] == "planner@example.test"
        )
        promoted = client.patch(
            f"/api/v1/admin/hubs/adpc/members/{planner['id']}",
            json={"role": "admin"},
        )
        disabled = client.patch(
            f"/api/v1/admin/hubs/adpc/members/{membership_id}",
            json={"status": "disabled"},
        )
    finally:
        app.dependency_overrides.clear()

    assert assigned.status_code == 200
    assert listed.status_code == 200
    assert {member["email"] for member in listed.json()["members"]} == {
        "hub-admin@example.test",
        "planner@example.test",
    }
    assert denied.status_code == 409
    assert denied.json()["error"]["code"] == "LAST_ADMIN_REQUIRED"
    assert promoted.status_code == 200
    assert disabled.status_code == 200


def test_planner_cannot_manage_hub_or_read_another_hubs_members() -> None:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        bootstrap_platform_admin(session, "owner@example.test")
        for code in ("adpc", "other"):
            ensure_hub(
                session,
                actor_email="owner@example.test",
                code=code,
                name=f"{code} Hub",
            )
        assign_member(
            session,
            actor_email="owner@example.test",
            email="planner@example.test",
            hub_code="adpc",
            role="planner",
        )
        planner_id = session.scalar(
            select(AppUser.id).where(AppUser.email == "planner@example.test")
        )
        hub_id = session.scalar(select(Hub.id).where(Hub.code == "adpc"))
        session.commit()

    def test_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    principal = CurrentPrincipal(
        user_id=planner_id,
        email="planner@example.test",
        display_name=None,
        is_platform_admin=False,
        memberships=(MembershipView(hub_id, "adpc", "adpc Hub", "planner"),),
        issued_at=0,
        session_id=str(uuid4()),
    )
    app.dependency_overrides[database_session] = test_session
    app.dependency_overrides[authenticated_user] = lambda: principal
    try:
        client = TestClient(app)
        own = client.get("/api/v1/admin/hubs/adpc/members")
        other = client.get("/api/v1/admin/hubs/other/members")
        add = client.post(
            "/api/v1/admin/hubs/adpc/members",
            json={"email": "guest@example.test", "role": "planner"},
        )
    finally:
        app.dependency_overrides.clear()

    assert own.status_code == 403
    assert own.json()["error"]["code"] == "ACCESS_NOT_AUTHORIZED"
    # Another Hub is indistinguishable from an unknown one.
    assert other.status_code == 404
    assert add.status_code == 403


def test_admin_members_route_is_not_public() -> None:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)

    def test_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[database_session] = test_session
    try:
        response = TestClient(app).get("/api/v1/admin/hubs/adpc/members")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401
