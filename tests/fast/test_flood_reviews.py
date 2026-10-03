"""Officer reviews (ADR-0042): human evidence that is time-bound, audited and never inherited."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import Response
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import api.access
import api.permissions
from api.dependencies import database_session
from api.main import app
from api.rate_limits import limiter
from api.sessions import CSRF_COOKIE, set_session_cookie
from api.settings import Settings
from core.access_models import AppUser, AuditEvent, Base, Hub
from core.flood_evidence.assets import asset_registry
from core.flood_evidence.cameras import camera_registry
from core.flood_evidence.config import pilot_config
from core.flood_evidence.incident_store import incident_detail, list_incidents
from core.flood_evidence.models import FloodIncident, FloodReview
from core.flood_evidence.reviews import (
    NOTE_MAX,
    ReviewRejected,
    facility_overrides,
    incident_verification,
    review_facility,
    review_incident,
)
from core.identity import IdentityLinkResult
from grpcli.admin import assign_member, bootstrap_platform_admin, ensure_hub

CONFIG = pilot_config("bangkok")
NOW = datetime.now(UTC).replace(microsecond=0)
ASSET = asset_registry("bangkok")[0][0].asset_id


@pytest.fixture
def world(tmp_path, monkeypatch) -> Iterator[dict]:
    secret = tmp_path / "session_secret"
    secret.write_text("flood-review-session-secret-long-enough", encoding="utf-8")
    settings = Settings(_env_file=None, grp_env="dev", session_secret_file=secret)
    for module in (api.access, api.permissions):
        monkeypatch.setattr(module, "get_settings", lambda: settings)
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        bootstrap_platform_admin(session, "owner@example.test")
        ensure_hub(session, actor_email="owner@example.test", code="adpc", name="ADPC Hub")
        ensure_hub(session, actor_email="owner@example.test", code="other", name="Other Hub")
        assign_member(session, actor_email="owner@example.test", email="officer@example.test",
                      hub_code="adpc", role="planner")
        assign_member(session, actor_email="owner@example.test", email="outsider@example.test",
                      hub_code="other", role="admin")
        incident = FloodIncident(
            pilot_id="bangkok", status="active", opened_at=NOW, last_active_at=NOW,
            last_snapshot_at=NOW, road_keys=["a" * 16, "b" * 16], bbox=[100.5, 13.8, 100.6, 13.9],
            rule_version="test",
            summary={"road_keys": ["a" * 16, "b" * 16], "report_keys": [], "contrary_keys": [],
                     "confidence": "low", "conflict": False, "reasons": [],
                     "source_families": ["traffy"], "freshness_basis": "newest_report",
                     "newest_evidence_at": NOW.isoformat(), "freshness": "current",
                     "rule_version": "test", "center": [100.55, 13.85]},
        )
        session.add(incident)
        session.commit()
        users = {u.email: u.id for u in session.scalars(select(AppUser))}
        hub = session.scalar(select(Hub.id).where(Hub.code == "adpc"))
        incident_id = incident.id

    def test_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[database_session] = test_session
    limiter.reset()
    try:
        yield {"settings": settings, "engine": engine, "users": users, "hub": hub,
               "incident": incident_id}
    finally:
        app.dependency_overrides.clear()


def _client(world: dict, email: str, *, csrf: bool = True) -> TestClient:
    response = Response()
    set_session_cookie(
        response, world["settings"],
        IdentityLinkResult(allowed=True, reason="allowed", user_id=world["users"][email]),
        issued_at=int(datetime.now(UTC).timestamp()) - 5, session_id=f"session-{email}",
    )
    client = TestClient(app)
    for header in response.headers.getlist("set-cookie"):
        name, value = header.split(";", 1)[0].split("=", 1)
        client.cookies.set(name, value)
    if csrf:
        client.headers["X-CSRF-Token"] = client.cookies[CSRF_COOKIE]
    return client


def _review_url(world: dict) -> str:
    return f"/api/v1/pilot/flood/bangkok/incidents/{world['incident']}/reviews"


def test_an_officer_review_is_recorded_shown_and_audited(world) -> None:
    client = _client(world, "officer@example.test")
    answer = client.post(_review_url(world), json={"action": "flooding_seen", "note": "Knee deep"})
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["verification"] == "officer_saw_flooding"
    assert body["reviews"][0]["note"] == "Knee deep" and body["reviews"][0]["current"]
    assert body["confidence"] == "low"  # the engine's answer is kept apart from the human one
    assert any(e["kind"] == "officer_review" for e in body["events"])
    with Session(world["engine"]) as session:
        audit = session.scalar(select(AuditEvent).where(
            AuditEvent.action == "flood_pilot.incident_review"))
        assert audit.hub_id == world["hub"] and audit.actor_user_id == world["users"][
            "officer@example.test"]
        assert "Knee" not in str(audit.new_value)  # the note itself stays out of the audit log


def test_a_post_without_the_csrf_header_is_refused(world) -> None:
    client = _client(world, "officer@example.test", csrf=False)
    assert client.post(_review_url(world), json={"action": "dry_seen"}).status_code == 403
    with Session(world["engine"]) as session:
        assert session.scalar(select(FloodReview)) is None


def test_another_hub_and_a_platform_admin_without_membership_cannot_write(world) -> None:
    for email in ("outsider@example.test", "owner@example.test"):
        answer = _client(world, email).post(_review_url(world), json={"action": "dry_seen"})
        assert answer.status_code == 403


@pytest.mark.parametrize(
    "body",
    [
        {"action": "flooded_probably"},
        {"action": "dry_seen", "note": "x" * (NOTE_MAX + 1)},
        {"action": "dry_seen", "camera_id": camera_registry("bangkok")[0].camera_id},
    ],
)
def test_unknown_actions_long_notes_and_placeholder_cameras_are_refused(world, body) -> None:
    assert _client(world, "officer@example.test").post(_review_url(world), json=body).status_code \
        == 422


def test_facility_access_is_confirmed_then_withdrawn_and_never_set_to_accessible(world) -> None:
    client = _client(world, "officer@example.test")
    url = "/api/v1/pilot/flood/bangkok/facilities/access"
    confirmed = client.post(url, json={"asset_id": ASSET, "action": "access_disrupted"})
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["access_state"] == "access_disrupted_confirmed"
    withdrawn = client.post(url, json={"asset_id": ASSET, "action": "withdraw"})
    assert withdrawn.json()["access_state"] in {"access_unknown", "access_under_review"}
    assert client.post(url, json={"asset_id": ASSET, "action": "accessible"}).status_code == 422
    assert client.post(url, json={"asset_id": "osm:node/0", "action": "withdraw"}).status_code \
        == 404


# --- Rules without HTTP ---------------------------------------------------------------------


@pytest.fixture
def session(world) -> Iterator[Session]:
    with Session(world["engine"]) as db:
        yield db


def _review(session, world, action="flooding_seen", at=NOW):
    review = review_incident(session, CONFIG, incident_id=world["incident"],
                             user_id=world["users"]["officer@example.test"], hub_id=world["hub"],
                             action=action, camera_id=None, note=None, now=at)
    session.commit()
    return review


def test_a_review_expires_after_three_hours(session, world) -> None:
    _review(session, world)
    incident = session.get(FloodIncident, world["incident"])
    assert incident_verification(session, CONFIG, [incident], NOW + timedelta(hours=2))
    later = NOW + timedelta(hours=3, seconds=1)
    assert not incident_verification(session, CONFIG, [incident], later)


def test_a_review_does_not_follow_an_incident_whose_roads_all_changed(session, world) -> None:
    _review(session, world)
    incident = session.get(FloodIncident, world["incident"])
    incident.road_keys = ["c" * 16]
    session.commit()
    assert not incident_verification(session, CONFIG, [incident], NOW + timedelta(minutes=5))


def test_an_officer_seeing_dry_puts_the_incident_first(session, world) -> None:
    _review(session, world, "dry_seen")
    [first] = list_incidents(session, CONFIG, NOW + timedelta(minutes=1))["incidents"]
    assert first["verification"] == "officer_saw_dry"
    detail = incident_detail(session, CONFIG, world["incident"], NOW + timedelta(minutes=1))
    assert detail["reviews"][0]["by"] == "officer@example.test"


def test_a_closed_incident_cannot_be_reviewed(session, world) -> None:
    session.get(FloodIncident, world["incident"]).status = "closed"
    session.commit()
    with pytest.raises(ReviewRejected):
        _review(session, world)


def test_a_facility_confirmation_expires(session, world) -> None:
    review_facility(session, CONFIG, asset_id=ASSET, user_id=world["users"][
        "officer@example.test"], hub_id=world["hub"], action="access_disrupted", note=None, now=NOW)
    session.commit()
    assert ASSET in facility_overrides(session, CONFIG, NOW + timedelta(hours=1))
    assert ASSET not in facility_overrides(session, CONFIG, NOW + timedelta(hours=4))
