from collections.abc import Iterator
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api.admin import platform_admin
from api.dependencies import database_session
from api.main import app
from api.sessions import CurrentPrincipal
from core.access_models import AppUser, Base
from core.identity import VerifiedIdentity, link_verified_identity
from grp.admin import bootstrap_platform_admin, ensure_hub


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
    app.dependency_overrides[platform_admin] = lambda: principal
    try:
        client = TestClient(app)
        pending = client.get("/api/v1/admin/access-requests")
        assigned = client.post(
            "/api/v1/admin/hubs/adpc/members",
            json={"email": "expert@example.test", "role": "planner"},
        )
        after = client.get("/api/v1/admin/access-requests")
    finally:
        app.dependency_overrides.clear()

    assert pending.status_code == 200
    assert pending.json() == {"requests": [{"email": "expert@example.test"}]}
    assert assigned.status_code == 200
    assert assigned.json()["changed"] is True
    assert after.json() == {"requests": []}


def test_admin_access_queue_is_not_public() -> None:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)

    def test_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[database_session] = test_session
    try:
        response = TestClient(app).get("/api/v1/admin/access-requests")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401
