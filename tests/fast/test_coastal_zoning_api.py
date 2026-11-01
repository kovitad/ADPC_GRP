"""Coastal-zoning lifecycle routes are Hub-scoped, idempotent, and auditable."""

from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi import Response
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import api.access
import api.coastal_zoning
import api.permissions
from api.dependencies import database_session
from api.main import app
from api.mcp_client import McpToolResult
from api.sessions import CSRF_COOKIE, set_session_cookie
from api.settings import Settings
from core.access_models import AppUser, AuditEvent, Base
from core.coastal_zoning.models import (
    CoastalZoningArtifact,
    CoastalZoningReviewLog,
    CoastalZoningRun,
    CoastalZoningStep,
    CoastalZoningZone,
)
from core.identity import IdentityLinkResult
from grpcli.admin import assign_member, bootstrap_platform_admin, ensure_hub

AOI = {
    "type": "Feature",
    "geometry": {
        "type": "Polygon",
        "coordinates": [[[110.45, -6.95], [110.7, -6.95], [110.7, -6.75], [110.45, -6.95]]],
    },
    "properties": {"name": "Test coast", "source": "drawn"},
}


@pytest.fixture
def world(tmp_path, monkeypatch) -> Iterator[dict]:
    secret = tmp_path / "session_secret"
    secret.write_text("coastal-api-session-secret-long-enough", encoding="utf-8")
    settings = Settings(
        _env_file=None,
        grp_env="dev",
        session_secret_file=secret,
        storage_root=tmp_path / "storage",
        coastal_zoning_enabled=True,
    )
    for module in (api.access, api.coastal_zoning, api.permissions):
        monkeypatch.setattr(module, "get_settings", lambda: settings)
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        bootstrap_platform_admin(session, "owner@example.test")
        ensure_hub(session, actor_email="owner@example.test", code="adpc", name="ADPC Hub")
        ensure_hub(session, actor_email="owner@example.test", code="other", name="Other Hub")
        assign_member(
            session,
            actor_email="owner@example.test",
            email="planner@example.test",
            hub_code="adpc",
            role="ndmo_planner",
        )
        assign_member(
            session,
            actor_email="owner@example.test",
            email="outsider@example.test",
            hub_code="other",
            role="admin",
        )
        session.commit()
        users = {user.email: user.id for user in session.scalars(select(AppUser))}

    def test_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[database_session] = test_session
    try:
        yield {"settings": settings, "engine": engine, "users": users}
    finally:
        app.dependency_overrides.clear()


def _client(world: dict, email: str) -> TestClient:
    response = Response()
    set_session_cookie(
        response,
        world["settings"],
        IdentityLinkResult(allowed=True, reason="allowed", user_id=world["users"][email]),
        issued_at=int(datetime.now(UTC).timestamp()) - 5,
        session_id=f"session-{email}",
    )
    client = TestClient(app)
    for header in response.headers.getlist("set-cookie"):
        name, value = header.split(";", 1)[0].split("=", 1)
        client.cookies.set(name, value)
    client.headers["X-CSRF-Token"] = client.cookies[CSRF_COOKIE]
    return client


def _submit(client: TestClient, *, key: str = "coastal-key-1", name: str = "Demak"):
    return client.post(
        "/api/v1/coastal-zoning/runs",
        headers={"Idempotency-Key": key},
        json={
            "hub_code": "adpc",
            "aoi": AOI,
            "site_name": name,
            "country": "ID",
            "params": {"reserve_m": 100},
            "language": "en",
        },
    )


def test_live_coverage_is_pinned_to_the_person_and_can_queue_a_run(world, monkeypatch) -> None:
    async def token(*_args):
        return "delegated-token"

    class FakeMcp:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def call_tool(self, name, arguments):
            assert name == "assemble_pack"
            assert arguments["geometry"]["type"] == "Polygon"
            layers = {
                layer: {"title": layer, "grid": {}} for layer in api.coastal_zoning.KENYA_LAYERS
            }
            return McpToolResult(
                [],
                {
                    "status": "ok",
                    "pack_id": "pack-live-test",
                    "layers": layers,
                    "gaps": ["One declared test gap."],
                },
                False,
            )

    monkeypatch.setattr(api.coastal_zoning, "sig_access_token", token)
    monkeypatch.setattr(api.coastal_zoning, "SigMcpClient", FakeMcp)
    client = _client(world, "planner@example.test")
    lamu = {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[40.84, -2.20], [40.90, -2.20], [40.90, -2.14], [40.84, -2.20]]],
        },
        "properties": {"source": "drawn"},
    }

    checked = client.post(
        "/api/v1/coastal-zoning/coverage",
        json={"hub_code": "adpc", "country": "KE", "aoi": lamu},
    )
    assert checked.status_code == 200, checked.text
    coverage = checked.json()
    assert coverage["ready"] and coverage["pack_id"] == "pack-live-test"

    queued = client.post(
        "/api/v1/coastal-zoning/runs",
        headers={"Idempotency-Key": "coverage-backed-run"},
        json={
            "hub_code": "adpc",
            "coverage_id": coverage["coverage_id"],
            "aoi": lamu,
            "site_name": "Lamu test",
            "country": "KE",
            "params": coverage["defaults"],
            "language": "en",
        },
    )
    assert queued.status_code == 202, queued.text
    with Session(world["engine"]) as session:
        artifact = session.scalar(
            select(CoastalZoningArtifact).where(
                CoastalZoningArtifact.run_id == UUID(queued.json()["run_id"])
            )
        )
        assert artifact is not None
        assert artifact.kind == "coverage_pack"


def test_create_is_idempotent_and_has_ten_trace_steps(world) -> None:
    client = _client(world, "planner@example.test")
    first = _submit(client)
    second = _submit(client)

    assert first.status_code == second.status_code == 202, first.text
    assert first.json()["run_id"] == second.json()["run_id"]
    assert first.headers["location"].endswith(first.json()["run_id"])
    detail = client.get(first.headers["location"])
    trace = client.get(f"{first.headers['location']}/trace")
    assert detail.status_code == trace.status_code == 200
    assert len(detail.json()["steps"]) == len(trace.json()["steps"]) == 10
    assert detail.json()["versions"]["mcp_authentication"] == "delegated_user_mcp"

    with Session(world["engine"]) as session:
        assert session.scalar(select(func.count()).select_from(CoastalZoningRun)) == 1
        assert session.scalar(select(func.count()).select_from(CoastalZoningStep)) == 10
        assert session.scalar(select(func.count()).select_from(AuditEvent)) >= 1


def test_changed_idempotency_request_conflicts_and_cross_hub_is_hidden(world) -> None:
    owner = _client(world, "planner@example.test")
    created = _submit(owner, key="coastal-key-2")
    conflict = _submit(owner, key="coastal-key-2", name="A different coast")
    outsider = _client(world, "outsider@example.test")

    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert outsider.get(created.headers["location"]).status_code == 404
    assert outsider.post(f"{created.headers['location']}/cancel").status_code == 404


def test_only_an_admin_can_review_zone_names_and_notes(world) -> None:
    planner = _client(world, "planner@example.test")
    created = _submit(planner, key="review-run").json()
    run_id = UUID(created["run_id"])
    with Session(world["engine"]) as session:
        run = session.get(CoastalZoningRun, run_id)
        run.status = "succeeded"
        session.add(
            CoastalZoningZone(
                run_id=run_id,
                zone_id="C1",
                kind="coastal",
                display_name="Draft coast",
                rank=None,
                score=None,
                area_km2=1.25,
                geometry={"type": "MultiPolygon", "coordinates": []},
                facts={"basis": "map-grid estimate"},
            )
        )
        session.commit()

    denied = planner.post(
        f"/api/v1/coastal-zoning/runs/{run_id}/review",
        json={"zones": [{"zone_id": "C1", "display_name": "Reviewed coast"}]},
    )
    assert denied.status_code == 404

    admin = _client(world, "owner@example.test")
    reviewed = admin.post(
        f"/api/v1/coastal-zoning/runs/{run_id}/review",
        json={
            "zones": [
                {
                    "zone_id": "C1",
                    "display_name": "Reviewed coast",
                    "note": "ADJUSTED by the reviewer.",
                }
            ]
        },
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["review_state"] == "reviewed"
    with Session(world["engine"]) as session:
        zone = session.get(CoastalZoningZone, (run_id, "C1"))
        assert zone.display_name == "Reviewed coast"
        assert zone.note == "ADJUSTED by the reviewer."
        assert session.scalar(select(func.count()).select_from(CoastalZoningReviewLog)) == 3


def test_owner_can_cancel_a_queued_run(world) -> None:
    client = _client(world, "planner@example.test")
    created = _submit(client, key="coastal-key-cancel")

    cancelled = client.post(f"{created.headers['location']}/cancel")

    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
