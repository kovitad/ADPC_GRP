"""Replay (ADR-0044): same engines, own namespace, forward-only clock, nothing written live."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import Response
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import api.access
import api.flood_pilot
import api.permissions
import core.flood_evidence.incident_store as store
from api.dependencies import database_session
from api.errors import GrpError
from api.main import app
from api.rate_limits import limiter
from api.sessions import CSRF_COOKIE, set_session_cookie
from api.settings import Settings
from core.access_models import AppUser, Base, Hub
from core.flood_evidence.config import pilot_config
from core.flood_evidence.ingest import Pulled, ingest_body, utc
from core.flood_evidence.models import (
    FETCH_NETWORK_ERROR,
    FETCH_OK,
    FloodAssetExposure,
    FloodIncident,
    FloodIncidentEvent,
    FloodIncidentRun,
    FloodObservation,
    FloodReplay,
    FloodSourceFetch,
)
from core.flood_evidence.replay import (
    READY,
    ReplayRejected,
    advance,
    create_replay,
    replay_config,
    restart,
    step,
    wipe,
)
from core.identity import IdentityLinkResult
from core.storage import LocalStorage
from grpcli.admin import assign_member, bootstrap_platform_admin, ensure_hub

CONFIG = pilot_config("bangkok")
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "floodboard"
ROADS = (FIXTURES / "roads_20261003.geojson").read_bytes()
REPORTS = (FIXTURES / "reports_20261003.csv").read_bytes()
# Wide enough to hold the central-Bangkok fixture roads, so incidents form in both namespaces.
WIDE = [{"type": "Polygon", "coordinates": [[[100.3, 13.5], [100.9, 13.5], [100.9, 14.1],
                                               [100.3, 14.1], [100.3, 13.5]]]}]
TABLES = (FloodSourceFetch, FloodObservation, FloodAssetExposure, FloodIncident,
          FloodIncidentEvent, FloodIncidentRun)


def _newest_road_time() -> datetime:
    return max(datetime.fromtimestamp(f["properties"]["updated"] / 1000, UTC)
               for f in json.loads(ROADS)["features"])


def _deeper() -> bytes:
    collection = json.loads(ROADS)
    for feature in collection["features"]:
        feature["properties"]["depthCm"] = 55
    return json.dumps(collection).encode()


@pytest.fixture
def world(tmp_path, monkeypatch) -> Iterator[dict]:
    monkeypatch.setattr(store, "demo_outlines", lambda _config: WIDE)
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    storage = LocalStorage(tmp_path / "storage")
    t0 = _newest_road_time()
    with Session(engine) as session:
        bootstrap_platform_admin(session, "owner@example.test")
        ensure_hub(session, actor_email="owner@example.test", code="adpc", name="ADPC Hub")
        assign_member(session, actor_email="owner@example.test", email="officer@example.test",
                      hub_code="adpc", role="planner")
        roads = CONFIG.source("floodboard_roads")
        reports = CONFIG.source("floodboard_reports")
        # A small live history: roads, reports, a failed pull, then changed roads.
        ingest_body(session, storage, CONFIG, roads, Pulled(200, ROADS, FETCH_OK), t0)
        ingest_body(session, storage, CONFIG, reports, Pulled(200, REPORTS, FETCH_OK),
                    t0 + timedelta(minutes=1))
        ingest_body(session, storage, CONFIG, roads, Pulled(None, None, FETCH_NETWORK_ERROR),
                    t0 + timedelta(minutes=10))
        ingest_body(session, storage, CONFIG, roads, Pulled(200, _deeper(), FETCH_OK),
                    t0 + timedelta(minutes=20))
        session.commit()
        users = {u.email: u.id for u in session.scalars(select(AppUser))}
        hub = session.scalar(select(Hub.id).where(Hub.code == "adpc"))
    yield {"engine": engine, "storage": storage, "t0": t0, "users": users, "hub": hub,
           "now": t0 + timedelta(hours=1)}


def _counts(session, pilot_id):
    return {m.__tablename__: session.scalar(select(func.count()).select_from(m)
                                            .where(m.pilot_id == pilot_id)) for m in TABLES}


def _build(session, world, end_minutes=30):
    replay = create_replay(session, CONFIG, start_at=world["t0"] - timedelta(minutes=1),
                           end_at=world["t0"] + timedelta(minutes=end_minutes),
                           user_id=world["users"]["officer@example.test"], hub_id=world["hub"],
                           now=world["now"])
    advance(replay, replay.end_at)
    while step(session, world["storage"], replay):
        pass
    session.commit()
    return replay


def test_a_replay_reproduces_the_live_timeline_without_touching_live_rows(world) -> None:
    with Session(world["engine"]) as session:
        live_before = _counts(session, "bangkok")
        replay = _build(session, world)
        assert replay.status == READY and replay.steps_done == replay.steps_total == 4
        assert _counts(session, "bangkok") == live_before

        def runs(pilot_id):
            return [r.active_count for r in session.scalars(
                select(FloodIncidentRun).where(FloodIncidentRun.pilot_id == pilot_id)
                .order_by(FloodIncidentRun.snapshot_at))]

        def incidents(pilot_id):
            return sorted(tuple(i.road_keys) for i in session.scalars(
                select(FloodIncident).where(FloodIncident.pilot_id == pilot_id)))

        assert runs(replay.replay_pilot_id) == runs("bangkok") and runs("bangkok")
        assert incidents(replay.replay_pilot_id) == incidents("bangkok")
        # The failed pull is replayed as a failure, and raw bytes are not copied.
        fetches = list(session.scalars(select(FloodSourceFetch).where(
            FloodSourceFetch.pilot_id == replay.replay_pilot_id)))
        assert sum(f.outcome == FETCH_NETWORK_ERROR for f in fetches) == 1
        live_keys = set(session.scalars(select(FloodSourceFetch.storage_key).where(
            FloodSourceFetch.pilot_id == "bangkok")))
        assert {f.storage_key for f in fetches if f.storage_key} <= live_keys


def test_the_replay_clock_only_moves_forward_and_restart_rebuilds(world) -> None:
    with Session(world["engine"]) as session:
        replay = create_replay(session, CONFIG, start_at=world["t0"] - timedelta(minutes=1),
                               end_at=world["t0"] + timedelta(minutes=30),
                               user_id=world["users"]["officer@example.test"],
                               hub_id=world["hub"], now=world["now"])
        advance(replay, world["t0"] + timedelta(minutes=5))
        while step(session, world["storage"], replay):
            pass
        assert utc(replay.processed_at) == world["t0"] + timedelta(minutes=1)
        assert replay_config(replay).clock == utc(replay.processed_at)
        with pytest.raises(ReplayRejected):
            advance(replay, world["t0"])
        restart(session, replay)
        assert replay.processed_at is None and _counts(session, replay.replay_pilot_id)[
            "flood_source_fetch"] == 0


def test_wiping_a_replay_leaves_no_rows_and_never_touches_live(world) -> None:
    with Session(world["engine"]) as session:
        replay = _build(session, world)
        live = _counts(session, "bangkok")
        wipe(session, replay.replay_pilot_id)
        session.commit()
        assert all(n == 0 for n in _counts(session, replay.replay_pilot_id).values())
        assert _counts(session, "bangkok") == live
        with pytest.raises(ValueError):
            wipe(session, "bangkok")


@pytest.mark.parametrize(
    ("start", "end", "code"),
    [(30, 10, "bad_window"), (-60 * 13, 0, "window_too_long"), (-600, -590, "no_data")],
)
def test_bad_replay_windows_are_refused(world, start, end, code) -> None:
    t0 = world["t0"]
    with Session(world["engine"]) as session, pytest.raises(ReplayRejected) as error:
        create_replay(session, CONFIG, start_at=t0 + timedelta(minutes=start),
                      end_at=t0 + timedelta(minutes=end),
                      user_id=world["users"]["officer@example.test"], hub_id=world["hub"],
                      now=world["now"])
    assert error.value.code == code


def test_reads_in_a_replay_cannot_look_past_its_clock(world) -> None:
    with Session(world["engine"]) as session:
        replay = _build(session, world, end_minutes=5)
        config = replay_config(replay)
        clock = utc(replay.processed_at)
        assert api.flood_pilot.now_for(config) == clock
        with pytest.raises(GrpError):
            api.flood_pilot._as_of((clock + timedelta(minutes=1)).isoformat(), config)


# --- Through the API: a replay looks like a replay and records nothing ----------------------


def _client(settings, user_id) -> TestClient:
    response = Response()
    set_session_cookie(response, settings,
                       IdentityLinkResult(allowed=True, reason="allowed", user_id=user_id),
                       issued_at=int(datetime.now(UTC).timestamp()) - 5,
                       session_id=f"session-{user_id}")
    client = TestClient(app)
    for header in response.headers.getlist("set-cookie"):
        name, value = header.split(";", 1)[0].split("=", 1)
        client.cookies.set(name, value)
    client.headers["X-CSRF-Token"] = client.cookies[CSRF_COOKIE]
    return client


def test_a_replay_refuses_officer_writes_and_gives_no_ai(world, tmp_path, monkeypatch) -> None:
    secret = tmp_path / "session_secret"
    secret.write_text("flood-replay-session-secret-long-enough", encoding="utf-8")
    settings = Settings(_env_file=None, grp_env="dev", session_secret_file=secret)
    for module in (api.access, api.permissions, api.flood_pilot):
        monkeypatch.setattr(module, "get_settings", lambda: settings)

    def test_session() -> Iterator[Session]:
        with Session(world["engine"]) as session:
            yield session

    app.dependency_overrides[database_session] = test_session
    limiter.reset()
    try:
        with Session(world["engine"]) as session:
            replay = _build(session, world)
            rid = replay.replay_pilot_id
            incident = session.scalars(select(FloodIncident).where(
                FloodIncident.pilot_id == rid)).first()
        client = _client(settings, world["users"]["officer@example.test"])
        base = f"/api/v1/pilot/flood/{rid}"
        assert client.get(f"{base}/incidents").status_code == 200
        review = client.post(f"{base}/incidents/{incident.id}/reviews",
                             json={"action": "flooding_seen"})
        assert review.status_code == 409 and review.json()["error"]["code"] == "REPLAY_READ_ONLY"
        access = client.post(f"{base}/facilities/access",
                             json={"asset_id": "osm:node/1", "action": "access_disrupted"})
        assert access.status_code == 409
        asked = client.post(f"{base}/ask", json={"question": "What changed?"}).json()
        assert asked["withheld"]["reason"] == "replay" and asked["computed"]
        assert asked["facts"][-1]["replay"] is True
        # Replays are never listed as pilots, and an unknown replay ID is not found.
        assert client.get("/api/v1/pilot/flood").json()["pilots"] == [
            {"pilot_id": "bangkok", "title": CONFIG.title}]
        assert client.get("/api/v1/pilot/flood/r00000000000/incidents").status_code == 404
        with Session(world["engine"]) as session:
            assert session.scalar(select(FloodReplay)) is not None
    finally:
        app.dependency_overrides.clear()
