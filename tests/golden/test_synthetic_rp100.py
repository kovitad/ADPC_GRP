"""Golden test (Section 15.1) on the SYNTHETIC RP100 case, end to end through the API and worker.

Also covers the Section 8.5 stop-safely cases and Section 8.2 idempotency.
"""

import csv
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

pytest.importorskip("rasterio")

from fastapi import Response  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import api.access  # noqa: E402
import api.admin  # noqa: E402
import api.assessments  # noqa: E402
import api.permissions  # noqa: E402
from api.dependencies import database_session  # noqa: E402
from api.main import app  # noqa: E402
from api.rate_limits import limiter  # noqa: E402
from api.sessions import CSRF_COOKIE, set_session_cookie  # noqa: E402
from api.settings import Settings  # noqa: E402
from core.access_models import AppUser, AuditEvent, Base  # noqa: E402
from core.assessment_jobs import claim_next_job, process_job  # noqa: E402
from core.assessment_models import Assessment, AssessmentFeature, Feature  # noqa: E402
from core.identity import IdentityLinkResult  # noqa: E402
from core.storage import LocalStorage  # noqa: E402
from grpcli.admin import assign_member, bootstrap_platform_admin, ensure_hub  # noqa: E402
from grpcli.seed import seed_synthetic_rp100  # noqa: E402

CASE = Path(__file__).parent / "synthetic_rp100"


@pytest.fixture
def world(tmp_path, monkeypatch) -> Iterator[dict]:
    secret = tmp_path / "session_secret"
    secret.write_text("golden-session-secret-with-enough-length", encoding="utf-8")
    settings = Settings(
        _env_file=None, session_secret_file=secret, allow_draft_methods=True,
        storage_root=tmp_path / "data",
    )
    for module in (api.access, api.admin, api.assessments, api.permissions):
        monkeypatch.setattr(module, "get_settings", lambda: settings)
    storage = LocalStorage(settings.storage_root)
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        bootstrap_platform_admin(session, "owner@example.test")
        for code in ("adpc", "other"):
            ensure_hub(session, actor_email="owner@example.test", code=code, name=f"{code} Hub")
        assign_member(session, actor_email="owner@example.test", email="planner@example.test",
                      hub_code="adpc", role="planner")
        assign_member(session, actor_email="owner@example.test", email="other@example.test",
                      hub_code="other", role="admin")
        seed = seed_synthetic_rp100(session, storage)
        session.commit()
        users = {user.email: user.id for user in session.scalars(select(AppUser))}

    def test_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[database_session] = test_session
    limiter.reset()
    try:
        yield {"settings": settings, "engine": engine, "storage": storage, "seed": seed,
               "users": users}
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


def _body(world: dict, **overrides) -> dict:
    seed = world["seed"]
    body = {
        "hub_code": "adpc",
        "boundary_id": seed.boundary_id,
        "hazard": {"type": "flood", "return_period_years": 100,
                   "dataset_version_id": seed.hazard_version_id},
        "evacuation_centers_dataset_version_id": seed.centers_version_id,
        "vulnerability_dataset_version_id": None,
        "method": {"key": "center-flood-overlay", "version": "1.0.0"},
    }
    body.update(overrides)
    return body


def _submit(client: TestClient, body: dict, key: str | None = None):
    return client.post("/api/v1/assessments", json=body,
                       headers={"Idempotency-Key": key or str(uuid4())})


def _run_worker(world: dict) -> str | None:
    with Session(world["engine"]) as session:
        assessment_id = claim_next_job(session, lease_minutes=15)
        if assessment_id is None:
            return None
        return process_job(session, world["storage"], assessment_id)


def test_synthetic_case_matches_hand_designed_expected_result_exactly(world) -> None:
    client = _client(world, "planner@example.test")

    submitted = _submit(client, _body(world))
    assessment_id = submitted.json()["assessment_id"]
    queued = client.get(f"/api/v1/assessments/{assessment_id}").json()
    not_ready = client.get(f"/api/v1/assessments/{assessment_id}/result")
    final_state = _run_worker(world)
    result = client.get(f"/api/v1/assessments/{assessment_id}/result").json()
    centers = client.get(f"/api/v1/assessments/{assessment_id}/centers?size=200").json()

    assert submitted.status_code == 202
    assert submitted.headers["Location"] == f"/api/v1/assessments/{assessment_id}"
    assert submitted.headers["Retry-After"] == "5"
    assert queued["state"] == "queued"
    assert not_ready.status_code == 409
    assert not_ready.json()["error"]["code"] == "ASSESSMENT_NOT_READY"
    assert final_state == "succeeded"

    expected_summary = json.loads((CASE / "expected_summary.json").read_text(encoding="utf-8"))
    assert result["summary"] == expected_summary
    assert result["map"]["version_id"] == world["seed"].hazard_version_id
    assert result["map"]["return_period_years"] == 100
    assert result["map"]["palette"] == "red_depth_v1"
    assert result["map"]["image_url"].endswith("/overlay.png")

    with (CASE / "expected_centers.csv").open(encoding="utf-8", newline="") as handle:
        expected = [
            {**row, "flood_depth_m": float(row["flood_depth_m"]) if row["flood_depth_m"] else None}
            for row in csv.DictReader(handle)
        ]
    actual = [
        {k: center[k] for k in ("name", "status", "reason_code", "flood_depth_m")}
        for center in centers["centers"]
    ]
    assert actual == expected
    assert centers["total"] == expected_summary["in_scope"]

    # Trust facts are separate and honest about synthetic, unapproved inputs (principle 6).
    assert result["synthetic"] is True
    assert result["input_compatible"] is True
    assert result["input_warning"] is None
    assert result["trust"]["scientifically_approved"] is False
    assert any("SYNTHETIC" in gap for gap in result["gaps"])
    assert result["sharing_state"] == "private"


def test_same_idempotency_key_returns_same_job_and_different_body_conflicts(world) -> None:
    client = _client(world, "planner@example.test")

    first = _submit(client, _body(world), key="retry-key-0001")
    again = _submit(client, _body(world), key="retry-key-0001")
    changed = _submit(
        client,
        _body(world, hazard={"type": "flood", "return_period_years": 50,
                             "dataset_version_id": world["seed"].hazard_version_id}),
        key="retry-key-0001",
    )

    assert first.json()["assessment_id"] == again.json()["assessment_id"]
    assert changed.status_code == 409
    assert changed.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    with Session(world["engine"]) as session:
        assert len(session.scalars(select(Assessment)).all()) == 1


@pytest.mark.parametrize(
    "override, code",
    [
        ({"boundary_id": str(uuid4())}, "UNSUPPORTED_AREA"),
        ({"hazard": {"type": "flood", "return_period_years": 25,
                     "dataset_version_id": None}}, "UNSUPPORTED_SCENARIO"),
        ({"evacuation_centers_dataset_version_id": str(uuid4())}, "INPUT_VERSION_MISSING"),
        ({"method": {"key": "center-flood-overlay", "version": "9.9.9"}}, "VALIDATION_FAILED"),
    ],
    ids=["unknown-area", "unsupported-return-period", "missing-dataset", "unknown-method"],
)
def test_invalid_inputs_stop_before_a_job_exists(world, override, code) -> None:
    body = _body(world, **override)
    if body["hazard"]["dataset_version_id"] is None:
        body["hazard"]["dataset_version_id"] = world["seed"].hazard_version_id

    response = _submit(_client(world, "planner@example.test"), body)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == code
    with Session(world["engine"]) as session:
        assert session.scalars(select(Assessment)).all() == []


def test_draft_method_is_refused_where_drafts_are_not_allowed(world, monkeypatch) -> None:
    strict = Settings(_env_file=None, session_secret_file=world["settings"].session_secret_file,
                      allow_draft_methods=False)
    monkeypatch.setattr(api.assessments, "get_settings", lambda: strict)

    response = _submit(_client(world, "planner@example.test"), _body(world))

    assert response.status_code == 422
    assert "not approved" in response.json()["error"]["message"]


def test_changed_input_file_fails_the_job_and_uses_no_other_data(world) -> None:
    client = _client(world, "planner@example.test")
    assessment_id = _submit(client, _body(world)).json()["assessment_id"]
    with Session(world["engine"]) as session:
        feature = session.scalar(select(Feature).where(Feature.name == "Synthetic School A"))
        feature.lon = 100.0605  # someone edits the locked center data after submission
        session.commit()

    state = _run_worker(world)
    status = client.get(f"/api/v1/assessments/{assessment_id}").json()

    assert state == "failed"
    assert status["error_code"] == "INPUT_FINGERPRINT_MISMATCH"
    with Session(world["engine"]) as session:
        assert session.scalars(select(AssessmentFeature)).all() == []


def test_access_removed_while_queued_cancels_job(world) -> None:
    client = _client(world, "planner@example.test")
    assessment_id = _submit(client, _body(world)).json()["assessment_id"]
    owner = _client(world, "owner@example.test")
    members = owner.get("/api/v1/admin/hubs/adpc/members").json()["members"]
    planner = next(m for m in members if m["email"] == "planner@example.test")

    disabled = owner.patch(f"/api/v1/admin/hubs/adpc/members/{planner['id']}",
                           json={"status": "disabled"})

    assert disabled.status_code == 200
    with Session(world["engine"]) as session:
        job = session.get(Assessment, __import__("uuid").UUID(assessment_id))
        assert job.state == "cancelled" and job.error_code == "ACCESS_NOT_AUTHORIZED"
    assert _run_worker(world) is None


def test_cancel_queued_job(world) -> None:
    client = _client(world, "planner@example.test")
    assessment_id = _submit(client, _body(world)).json()["assessment_id"]

    cancelled = client.post(f"/api/v1/assessments/{assessment_id}/cancel")
    again = client.post(f"/api/v1/assessments/{assessment_id}/cancel")

    assert cancelled.json()["state"] == "cancelled"
    assert again.status_code == 409
    assert _run_worker(world) is None


def test_other_hub_and_platform_admin_cannot_see_or_submit(world) -> None:
    planner = _client(world, "planner@example.test")
    assessment_id = _submit(planner, _body(world)).json()["assessment_id"]
    other = _client(world, "other@example.test")
    owner = _client(world, "owner@example.test")

    assert other.get(f"/api/v1/assessments/{assessment_id}").status_code == 404
    assert owner.get(f"/api/v1/assessments/{assessment_id}").status_code == 404
    assert _submit(other, _body(world)).status_code == 404  # hub_code adpc is not theirs
    # A Platform Admin has no Hub role, so naming a Hub finds nothing (Section 9.4).
    assert _submit(owner, _body(world)).status_code == 404
    assert _submit(owner, _body(world, hub_code='')).status_code == 422


def test_submit_and_success_are_in_the_security_log(world) -> None:
    client = _client(world, "planner@example.test")
    _submit(client, _body(world))
    _run_worker(world)

    with Session(world["engine"]) as session:
        actions = set(session.scalars(select(AuditEvent.action)))
    assert {"assessment_submitted", "assessment_succeeded"} <= actions
