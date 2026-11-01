"""Coastal-zoning persistence is resumable and keeps verdicts server-bound (ADR-0070)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from core.access_models import AppUser, Base, Hub
from core.coastal_zoning.jobs import (
    PIPELINE_STEPS,
    ZoningTransitionError,
    acknowledge_cancellation,
    claim_next_run,
    complete_step,
    fail_step,
    new_run_steps,
    request_cancellation,
    retry_failed_run,
    start_step,
    update_step_progress,
)
from core.coastal_zoning.models import (
    CoastalZoningRun,
    CoastalZoningStep,
    CoastalZoningZone,
    ZoningRunState,
    ZoningStepState,
)


@pytest.fixture
def world():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        hub = Hub(code="adpc", name="ADPC")
        user = AppUser(email="coastal@example.test", is_platform_admin=False)
        session.add_all([hub, user])
        session.commit()
        yield session, hub.id, user.id, engine


def _run(session: Session, hub_id, user_id, *, key: str = "coastal-run-1") -> CoastalZoningRun:
    run = CoastalZoningRun(
        hub_id=hub_id,
        owner_id=user_id,
        idempotency_key=key,
        request_sha256="a" * 64,
        site_name="Synthetic coast",
        country="ID",
        aoi_geojson={"type": "Polygon", "coordinates": []},
        aoi_source="drawn",
        aoi_sha256="b" * 64,
        profile="no_hazard",
        scale="local",
        params=[{"name": "reserve_m", "value": 100, "source": "hub_default"}],
        status=ZoningRunState.QUEUED,
        versions={"rules": "pending-starter-kit"},
        trace_id=f"trace-{key}",
        support_ref="GRP-COASTAL-TEST",
    )
    session.add(run)
    session.flush()
    session.add_all(new_run_steps(run.id))
    session.commit()
    return run


@pytest.mark.fast
def test_run_starts_with_all_ten_named_checkpoints(world) -> None:
    session, hub_id, user_id, _ = world
    run = _run(session, hub_id, user_id)

    steps = session.scalars(
        select(CoastalZoningStep)
        .where(CoastalZoningStep.run_id == run.id)
        .order_by(CoastalZoningStep.sequence)
    ).all()

    assert [(step.sequence, step.step_key, step.label) for step in steps] == list(PIPELINE_STEPS)
    assert {step.status for step in steps} == {ZoningStepState.QUEUED}


@pytest.mark.fast
def test_claim_reclaims_only_after_lease_expiry(world) -> None:
    session, hub_id, user_id, _ = world
    run = _run(session, hub_id, user_id)
    now = datetime(2026, 10, 23, 9, 0, tzinfo=UTC)

    assert claim_next_run(session, lease_minutes=15, now=now) == run.id
    assert claim_next_run(session, lease_minutes=15, now=now + timedelta(minutes=5)) is None
    assert claim_next_run(session, lease_minutes=15, now=now + timedelta(minutes=16)) == run.id

    session.refresh(run)
    assert run.status == ZoningRunState.RUNNING
    assert run.attempt == 2


@pytest.mark.fast
def test_checkpoint_records_progress_and_failure_duration(world) -> None:
    session, hub_id, user_id, _ = world
    run = _run(session, hub_id, user_id)
    now = datetime(2026, 10, 23, 9, 0, tzinfo=UTC)
    claim_next_run(session, lease_minutes=15, now=now)

    start_step(session, run.id, "P1_resolve", now=now)
    update_step_progress(
        session,
        run.id,
        "P1_resolve",
        done=1,
        total=2,
        summary="AOI normalized; checking coast coverage.",
    )
    fail_step(
        session,
        run.id,
        "P1_resolve",
        code="COAST_COVERAGE_UNAVAILABLE",
        summary="Coast coverage could not be confirmed.",
        now=now + timedelta(seconds=2),
    )

    step = session.scalar(select(CoastalZoningStep).where(CoastalZoningStep.run_id == run.id))
    session.refresh(run)
    assert step.status == ZoningStepState.FAILED
    assert step.duration_ms == 2000
    assert step.attempts == 1
    assert step.done == 1
    assert run.status == ZoningRunState.FAILED
    assert run.error["code"] == "COAST_COVERAGE_UNAVAILABLE"


@pytest.mark.fast
def test_retry_preserves_completed_checkpoint_and_requeues_failure(world) -> None:
    session, hub_id, user_id, _ = world
    run = _run(session, hub_id, user_id)
    now = datetime(2026, 10, 23, 9, 0, tzinfo=UTC)
    claim_next_run(session, lease_minutes=15, now=now)
    start_step(session, run.id, "P1_resolve", now=now)
    complete_step(
        session,
        run.id,
        "P1_resolve",
        summary="AOI normalized.",
        detail={"artifact": "aoi.geojson"},
        now=now + timedelta(seconds=1),
    )
    start_step(session, run.id, "P2_inventory", now=now + timedelta(seconds=1))
    fail_step(
        session,
        run.id,
        "P2_inventory",
        code="SIG_UNAVAILABLE",
        summary="Evidence inventory is unavailable.",
        now=now + timedelta(seconds=3),
    )

    retry_failed_run(session, run)
    steps = {
        step.step_key: step
        for step in session.scalars(
            select(CoastalZoningStep).where(CoastalZoningStep.run_id == run.id)
        )
    }

    assert run.status == ZoningRunState.QUEUED
    assert steps["P1_resolve"].status == ZoningStepState.COMPLETED
    assert steps["P1_resolve"].detail == {"artifact": "aoi.geojson"}
    assert steps["P2_inventory"].status == ZoningStepState.QUEUED
    assert steps["P2_inventory"].attempts == 1
    assert steps["P2_inventory"].detail == {}


@pytest.mark.fast
def test_running_cancellation_is_acknowledged_between_work_units(world) -> None:
    session, hub_id, user_id, _ = world
    run = _run(session, hub_id, user_id)
    now = datetime(2026, 10, 23, 9, 0, tzinfo=UTC)
    claim_next_run(session, lease_minutes=15, now=now)
    start_step(session, run.id, "P1_resolve", now=now)

    request_cancellation(session, run, now=now + timedelta(seconds=1))
    assert run.status == ZoningRunState.RUNNING
    assert run.cancellation_requested is True

    acknowledge_cancellation(session, run.id, now=now + timedelta(seconds=2))
    step = session.scalar(select(CoastalZoningStep).where(CoastalZoningStep.run_id == run.id))
    assert run.status == ZoningRunState.CANCELLED
    assert run.lease_until is None
    assert step.status == ZoningStepState.SKIPPED
    assert step.duration_ms == 2000


@pytest.mark.fast
def test_steps_must_execute_in_order(world) -> None:
    session, hub_id, user_id, _ = world
    run = _run(session, hub_id, user_id)
    claim_next_run(session, lease_minutes=15, now=datetime(2026, 10, 23, 9, 0, tzinfo=UTC))

    with pytest.raises(ZoningTransitionError, match="earlier"):
        start_step(session, run.id, "P2_inventory")


@pytest.mark.fast
def test_zone_stores_receipt_id_but_no_verdict_column(world) -> None:
    session, hub_id, user_id, engine = world
    run = _run(session, hub_id, user_id)
    zone = CoastalZoningZone(
        run_id=run.id,
        zone_id="C1",
        kind="coastal",
        display_name="Candidate coast 1",
        area_km2=1.25,
        geometry={"type": "Polygon", "coordinates": []},
        facts={"basis": "map_grid"},
        receipt_id="receipt-123",
    )
    session.add(zone)
    session.commit()

    columns = {column["name"] for column in inspect(engine).get_columns("coastal_zoning_zone")}
    assert zone.receipt_id == "receipt-123"
    assert "verdict" not in columns
    assert "passed" not in columns
