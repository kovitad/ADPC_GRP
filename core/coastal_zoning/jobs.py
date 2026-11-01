"""Persistent coastal-zoning job lifecycle and P1-P10 checkpoints.

This module does not perform GIS or network work. The worker pipeline will call these transitions
once the approved rules and SIG service authentication are available.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from core.coastal_zoning.models import (
    CoastalZoningRun,
    CoastalZoningStep,
    ZoningRunState,
    ZoningStepState,
)

PIPELINE_STEPS = (
    (10, "P1_resolve", "Resolve area"),
    (20, "P2_inventory", "Inventory evidence"),
    (30, "P3_pull_tiles", "Pull map tiles"),
    (40, "P4_mosaic", "Build input mosaic"),
    (50, "P5_zone", "Apply zoning rules"),
    (60, "P6_pick_zones", "Pick candidate zones"),
    (70, "P7_evidence", "Assemble zone evidence"),
    (80, "P8_brief_gate", "Draft and verify zone briefs"),
    (90, "P9_rank", "Rank verified zones"),
    (100, "P10_package", "Package report artifacts"),
)


class ZoningTransitionError(ValueError):
    """A requested run or checkpoint transition is not valid."""


def new_run_steps(run_id: UUID) -> list[CoastalZoningStep]:
    return [
        CoastalZoningStep(
            run_id=run_id,
            sequence=sequence,
            step_key=key,
            label=label,
            status=ZoningStepState.QUEUED,
            attempts=0,
            detail={},
        )
        for sequence, key, label in PIPELINE_STEPS
    ]


def claim_next_run(
    session: Session, *, lease_minutes: int, now: datetime | None = None
) -> UUID | None:
    """Claim one queued run or reclaim an expired run without exposing user credentials."""

    now = now or datetime.now(UTC)
    run = session.scalar(
        select(CoastalZoningRun)
        .where(
            or_(
                CoastalZoningRun.status == ZoningRunState.QUEUED,
                (CoastalZoningRun.status == ZoningRunState.RUNNING)
                & (CoastalZoningRun.lease_until < now),
            ),
            CoastalZoningRun.cancellation_requested.is_(False),
        )
        .order_by(CoastalZoningRun.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if run is None:
        return None
    run.status = ZoningRunState.RUNNING
    run.lease_until = now + timedelta(minutes=lease_minutes)
    run.attempt += 1
    run.started_at = run.started_at or now
    session.commit()
    return run.id


def renew_lease(
    session: Session,
    run_id: UUID,
    *,
    lease_minutes: int,
    now: datetime | None = None,
) -> bool:
    """Renew only an active, non-cancelled run. Returns false after ownership is lost."""

    now = now or datetime.now(UTC)
    run = session.get(CoastalZoningRun, run_id)
    if (
        run is None
        or run.status != ZoningRunState.RUNNING
        or run.cancellation_requested
        or run.lease_until is None
        or run.lease_until < now
    ):
        return False
    run.lease_until = now + timedelta(minutes=lease_minutes)
    session.commit()
    return True


def start_step(
    session: Session, run_id: UUID, step_key: str, *, now: datetime | None = None
) -> CoastalZoningStep:
    now = now or datetime.now(UTC)
    run = _active_run(session, run_id)
    if run.cancellation_requested:
        raise ZoningTransitionError("Cancellation was requested")
    step = _step(session, run_id, step_key)
    if step.status == ZoningStepState.COMPLETED:
        return step
    earlier = session.scalar(
        select(CoastalZoningStep.id)
        .where(
            CoastalZoningStep.run_id == run_id,
            CoastalZoningStep.sequence < step.sequence,
            CoastalZoningStep.status.not_in([ZoningStepState.COMPLETED, ZoningStepState.SKIPPED]),
        )
        .limit(1)
    )
    if earlier is not None:
        raise ZoningTransitionError("An earlier pipeline step is incomplete")
    if step.status not in {
        ZoningStepState.QUEUED,
        ZoningStepState.FAILED,
        ZoningStepState.RUNNING,
    }:
        raise ZoningTransitionError("The pipeline step cannot be started")
    if step.status != ZoningStepState.RUNNING:
        step.attempts += 1
        step.started_at = now
        step.finished_at = None
        step.duration_ms = None
    step.status = ZoningStepState.RUNNING
    session.flush()
    return step


def update_step_progress(
    session: Session,
    run_id: UUID,
    step_key: str,
    *,
    done: int,
    total: int,
    summary: str,
) -> None:
    if done < 0 or total < 0 or done > total:
        raise ZoningTransitionError("Invalid pipeline progress")
    step = _step(session, run_id, step_key)
    if step.status != ZoningStepState.RUNNING:
        raise ZoningTransitionError("Only a running pipeline step can report progress")
    step.done = done
    step.total = total
    step.summary = _summary(summary)
    session.flush()


def complete_step(
    session: Session,
    run_id: UUID,
    step_key: str,
    *,
    summary: str,
    detail: dict[str, object] | None = None,
    now: datetime | None = None,
) -> None:
    now = now or datetime.now(UTC)
    step = _step(session, run_id, step_key)
    if step.status != ZoningStepState.RUNNING or step.started_at is None:
        raise ZoningTransitionError("Only a running pipeline step can complete")
    step.status = ZoningStepState.COMPLETED
    step.finished_at = now
    step.duration_ms = _duration_ms(step.started_at, now)
    step.summary = _summary(summary)
    step.detail = detail or {}
    session.flush()


def fail_step(
    session: Session,
    run_id: UUID,
    step_key: str,
    *,
    code: str,
    summary: str,
    detail: dict[str, object] | None = None,
    now: datetime | None = None,
) -> None:
    now = now or datetime.now(UTC)
    run = _active_run(session, run_id)
    step = _step(session, run_id, step_key)
    if step.status != ZoningStepState.RUNNING or step.started_at is None:
        raise ZoningTransitionError("Only a running pipeline step can fail")
    step.status = ZoningStepState.FAILED
    step.finished_at = now
    step.duration_ms = _duration_ms(step.started_at, now)
    step.summary = _summary(summary)
    step.detail = detail or {}
    run.status = ZoningRunState.FAILED
    run.error = {"code": code, "message": _summary(summary)}
    run.lease_until = None
    run.completed_at = now
    session.commit()


def complete_run(session: Session, run_id: UUID, *, now: datetime | None = None) -> None:
    now = now or datetime.now(UTC)
    run = _active_run(session, run_id)
    incomplete = session.scalar(
        select(CoastalZoningStep.id)
        .where(
            CoastalZoningStep.run_id == run_id,
            CoastalZoningStep.status.not_in([ZoningStepState.COMPLETED, ZoningStepState.SKIPPED]),
        )
        .limit(1)
    )
    if incomplete is not None:
        raise ZoningTransitionError("The run has incomplete pipeline steps")
    run.status = ZoningRunState.SUCCEEDED
    run.lease_until = None
    run.completed_at = now
    session.commit()


def request_cancellation(
    session: Session, run: CoastalZoningRun, *, now: datetime | None = None
) -> None:
    now = now or datetime.now(UTC)
    if run.status == ZoningRunState.QUEUED:
        run.status = ZoningRunState.CANCELLED
        run.cancellation_requested = True
        run.completed_at = now
    elif run.status == ZoningRunState.RUNNING:
        run.cancellation_requested = True
    elif run.status not in {ZoningRunState.CANCELLED, ZoningRunState.RETIRED}:
        raise ZoningTransitionError("Only a queued or running run can be cancelled")
    session.commit()


def acknowledge_cancellation(
    session: Session, run_id: UUID, *, now: datetime | None = None
) -> None:
    now = now or datetime.now(UTC)
    run = session.get(CoastalZoningRun, run_id)
    if run is None or run.status != ZoningRunState.RUNNING or not run.cancellation_requested:
        raise ZoningTransitionError("The run has no active cancellation request")
    running = session.scalar(
        select(CoastalZoningStep)
        .where(
            CoastalZoningStep.run_id == run_id,
            CoastalZoningStep.status == ZoningStepState.RUNNING,
        )
        .limit(1)
    )
    if running is not None:
        running.status = ZoningStepState.SKIPPED
        running.finished_at = now
        if running.started_at is not None:
            running.duration_ms = _duration_ms(running.started_at, now)
        running.summary = "Cancelled by the requester."
    run.status = ZoningRunState.CANCELLED
    run.lease_until = None
    run.completed_at = now
    session.commit()


def retry_failed_run(session: Session, run: CoastalZoningRun) -> None:
    """Queue a failed run at its failed checkpoint; completed outputs remain immutable."""

    if run.status != ZoningRunState.FAILED:
        raise ZoningTransitionError("Only a failed run can be retried")
    failed = session.scalars(
        select(CoastalZoningStep).where(
            CoastalZoningStep.run_id == run.id,
            CoastalZoningStep.status == ZoningStepState.FAILED,
        )
    ).all()
    if len(failed) != 1:
        raise ZoningTransitionError("The failed checkpoint is not unambiguous")
    checkpoint = failed[0]
    later = session.scalars(
        select(CoastalZoningStep).where(
            CoastalZoningStep.run_id == run.id,
            CoastalZoningStep.sequence >= checkpoint.sequence,
        )
    ).all()
    for step in later:
        step.status = ZoningStepState.QUEUED
        step.done = None
        step.total = None
        step.duration_ms = None
        step.summary = None
        step.detail = {}
        step.started_at = None
        step.finished_at = None
    run.status = ZoningRunState.QUEUED
    run.error = None
    run.cancellation_requested = False
    run.lease_until = None
    run.completed_at = None
    session.commit()


def _active_run(session: Session, run_id: UUID) -> CoastalZoningRun:
    run = session.get(CoastalZoningRun, run_id)
    if run is None or run.status != ZoningRunState.RUNNING:
        raise ZoningTransitionError("The coastal-zoning run is not active")
    return run


def _step(session: Session, run_id: UUID, step_key: str) -> CoastalZoningStep:
    step = session.scalar(
        select(CoastalZoningStep).where(
            CoastalZoningStep.run_id == run_id,
            CoastalZoningStep.step_key == step_key,
        )
    )
    if step is None:
        raise ZoningTransitionError("Unknown pipeline step")
    return step


def _summary(value: str) -> str:
    value = " ".join(value.split())
    if not value or len(value) > 500:
        raise ZoningTransitionError("Pipeline summaries must contain 1 to 500 characters")
    return value


def _duration_ms(started_at: datetime, finished_at: datetime) -> int:
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=UTC)
    if finished_at.tzinfo is None:
        finished_at = finished_at.replace(tzinfo=UTC)
    return max(0, round((finished_at - started_at).total_seconds() * 1000))
