"""Bring a fresh local database up to a usable Thailand baseline in one command.

After a reset the stack has an empty data library: no districts, no evacuation centres, no
flood layer, so Planning has nothing to offer. Doing that by hand is three Data Library
imports, a wait on the worker for each, and a baseline activation on the Platform page.

    python -m grpcli.baseline load --actor-email you@example.org

Each step is the same code the API calls, so this is a shortcut through the user interface,
not a second way of importing. It is idempotent: a category already imported is left alone.
Local development only — it needs the delivered source files under the data-in mount.
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from typing import Never
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.errors import new_support_ref
from core.baseline_activation import BaselineActivationError, activate_mvp1_baseline
from core.boundary_import import BOUNDARY_SOURCE_REF
from core.data_import_jobs import request_import
from core.data_library_models import DataImportJob
from core.db import session_scope
from core.hazard_import import HAZARD_SOURCE_REF
from core.models import AssessmentState
from core.shelter_import import SHELTER_SOURCE_REF
from grpcli.admin import require_platform_admin

# Districts must exist before centres can be assigned to them by geometry.
STEPS: tuple[tuple[str, str], ...] = (
    ("boundary", BOUNDARY_SOURCE_REF),
    ("evacuation_centers", SHELTER_SOURCE_REF),
    ("hazard", HAZARD_SOURCE_REF),
)
POLL_SECONDS = 3
DEFAULT_TIMEOUT_SECONDS = 1800


def fail(message: str) -> Never:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(2)


@dataclass(frozen=True)
class StepResult:
    category: str
    import_id: UUID
    state: str
    report: dict


def _already_done(session: Session, category: str) -> UUID | None:
    """A succeeded import of this category means the work is done; reuse it."""

    return session.scalar(
        select(DataImportJob.id)
        .where(
            DataImportJob.category == category,
            DataImportJob.state == AssessmentState.SUCCEEDED,
        )
        .order_by(DataImportJob.created_at.desc())
        .limit(1)
    )


def _in_flight(session: Session, category: str) -> UUID | None:
    return session.scalar(
        select(DataImportJob.id)
        .where(
            DataImportJob.category == category,
            DataImportJob.state.in_([AssessmentState.QUEUED, AssessmentState.RUNNING]),
        )
        .order_by(DataImportJob.created_at.desc())
        .limit(1)
    )


def _queue(actor_user_id: UUID, category: str, source_ref: str) -> UUID:
    with session_scope() as session:
        existing = _already_done(session, category) or _in_flight(session, category)
        if existing is not None:
            return existing
        result = request_import(
            session,
            hub_id=None,
            requested_by=actor_user_id,
            idempotency_key=f"baseline-{category}-{uuid4()}",
            category=category,
            source_ref=source_ref,
            support_ref=new_support_ref(),
        )
        session.commit()
        return result.import_id


def _await_job(import_id: UUID, timeout_seconds: int) -> StepResult:
    """Wait for the worker. The worker owns all GIS; this only watches the row it writes."""

    deadline = time.monotonic() + timeout_seconds
    last = ""
    while True:
        with session_scope() as session:
            job = session.get(DataImportJob, import_id)
            if job is None:
                fail(f"import {import_id} disappeared")
            state, category, report = job.state, job.category, dict(job.report or {})
        if state in {AssessmentState.SUCCEEDED, AssessmentState.FAILED}:
            print()
            return StepResult(category, import_id, str(state), report)
        if state != last:
            print(f"  {category}: {state}", end="", flush=True)
            last = state
        else:
            print(".", end="", flush=True)
        if time.monotonic() > deadline:
            print()
            fail(f"{category} import did not finish within {timeout_seconds}s (state {state})")
        time.sleep(POLL_SECONDS)


def _describe(result: StepResult) -> None:
    report = result.report
    print(f"  {result.category}: {result.state}")
    for key in (
        "feature_count",
        "district_count",
        "outside_boundary_count",
        "district_name_mismatch_count",
        "capacity_missing_count",
    ):
        if report.get(key) is not None:
            print(f"    {key.replace('_', ' ')}: {report[key]}")
    labels = report.get("labels")
    if isinstance(labels, dict):
        print(
            "    labels: "
            + ", ".join(f"{name.replace('_', ' ')} {value}" for name, value in labels.items())
        )


def load(actor_email: str, timeout_seconds: int) -> None:
    with session_scope() as session:
        actor = require_platform_admin(session, actor_email)
        actor_user_id, actor_address = actor.id, actor.email

    print("Loading the Thailand baseline. The worker does the GIS; this waits on it.")
    results = []
    for category, source_ref in STEPS:
        import_id = _queue(actor_user_id, category, source_ref)
        result = _await_job(import_id, timeout_seconds)
        if result.state == AssessmentState.FAILED:
            _describe(result)
            fail(f"{category} import failed; nothing was activated")
        results.append(result)

    for result in results:
        _describe(result)

    with session_scope() as session:
        try:
            summary = activate_mvp1_baseline(
                session, actor_user_id=actor_user_id, actor_email=actor_address
            )
        except BaselineActivationError as error:
            fail(str(error))
        session.commit()
    print("\nActivated. Supported districts and the current versions are set:")
    for key, value in summary.items():
        print(f"  {key}: {value}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GRP local baseline loader")
    commands = parser.add_subparsers(dest="command", required=True)
    step = commands.add_parser("load", help="import the baseline and activate it")
    step.add_argument("--actor-email", required=True)
    step.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    return parser


def main() -> None:
    arguments = build_parser().parse_args()
    try:
        load(arguments.actor_email, arguments.timeout_seconds)
    except ValueError as error:
        fail(str(error))


if __name__ == "__main__":
    main()
