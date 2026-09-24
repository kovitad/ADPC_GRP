"""Operational commands for a repeatable Thailand Hub data install."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session

from api.settings import get_settings
from core.baseline_activation import activate_mvp1_baseline, activate_supporting_layers
from core.data_import_jobs import requeue_failed_import
from core.db import get_engine
from core.models import AssessmentState
from core.thailand_bootstrap import (
    TERMINAL_STATES,
    ThailandBootstrapError,
    bootstrap_library_status,
    discover_supported_sources,
    import_result,
    prepare_source,
    queue_prepared_source,
    require_bootstrap_context,
)


def _wait_for_import(import_id: UUID, *, timeout_seconds: int, poll_seconds: float) -> UUID:
    deadline = time.monotonic() + timeout_seconds
    last_progress: tuple[str, int] | None = None
    while time.monotonic() < deadline:
        with Session(get_engine()) as session:
            job = import_result(session, import_id)
            marker = (job.state, job.progress)
            if marker != last_progress:
                print(f"  {job.category}: {job.state} ({job.progress}%)", flush=True)
                last_progress = marker
            if job.state in TERMINAL_STATES:
                if job.state != AssessmentState.SUCCEEDED or job.dataset_version_id is None:
                    message = (job.report or {}).get("message", "Import did not succeed")
                    raise ThailandBootstrapError(
                        f"{job.category} stopped with {job.error_code or job.state}: {message}"
                    )
                return job.dataset_version_id
        time.sleep(poll_seconds)
    raise ThailandBootstrapError(
        f"Timed out waiting for import {import_id}. Check the worker logs and rerun safely."
    )


def install_thailand(
    *,
    actor_email: str,
    hub_code: str,
    source_root: Path,
    timeout_seconds: int,
    poll_seconds: float,
) -> dict[str, object]:
    """Queue, wait for and activate the supported baseline in dependency order."""

    sources = discover_supported_sources(source_root)
    print(f"Preflight found {len(sources)} supported Thailand source collections.")
    with Session(get_engine()) as session:
        actor = require_bootstrap_context(session, actor_email=actor_email, hub_code=hub_code)
        actor_id = actor.id

    version_ids: dict[str, UUID] = {}
    for source in sources:
        print(f"Checking {source.category} source bytes…", flush=True)
        prepared = prepare_source(source_root, source)
        print(
            f"  {len(source.files)} file(s), {prepared.total_bytes:,} bytes, "
            f"source {prepared.fingerprint[:12]}",
            flush=True,
        )
        with Session(get_engine()) as session:
            queued = queue_prepared_source(session, actor_user_id=actor_id, prepared=prepared)
        if queued.reused:
            print(f"  Reusing import {queued.import_id} ({queued.state}).", flush=True)
            if queued.state in {AssessmentState.FAILED, AssessmentState.CANCELLED}:
                with Session(get_engine()) as session:
                    if not requeue_failed_import(session, queued.import_id):
                        raise ThailandBootstrapError(
                            f"Import {queued.import_id} cannot be resumed safely"
                        )
                print("  Previous unpublished attempt requeued safely.", flush=True)
        else:
            print(f"  Queued import {queued.import_id}.", flush=True)
        version_ids[source.category] = _wait_for_import(
            queued.import_id,
            timeout_seconds=timeout_seconds,
            poll_seconds=poll_seconds,
        )

    with Session(get_engine()) as session:
        payload = activate_mvp1_baseline(
            session,
            actor_user_id=actor_id,
            actor_email=actor_email.strip().lower(),
            boundary_version_id=version_ids["boundary"],
            centers_version_id=version_ids["evacuation_centers"],
            hazard_version_id=version_ids["hazard"],
        )
        payload["supporting_layers"] = activate_supporting_layers(
            session,
            actor_user_id=actor_id,
            version_ids=version_ids,
        )
        session.commit()
        payload["hub_code"] = hub_code.strip().lower()
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Install the versioned Thailand Hub baseline")
    commands = parser.add_subparsers(dest="command", required=True)
    install = commands.add_parser("install-thailand")
    install.add_argument("--actor-email", required=True)
    install.add_argument("--hub-code", default="adpc")
    install.add_argument("--source-root", type=Path, default=None)
    install.add_argument("--timeout-seconds", type=int, default=1800)
    install.add_argument("--poll-seconds", type=float, default=1.5)
    status = commands.add_parser("status")
    status.add_argument("--source-root", type=Path, default=None)
    arguments = parser.parse_args()
    source_root = (arguments.source_root or get_settings().data_in_root).resolve()
    try:
        if arguments.command == "status":
            with Session(get_engine()) as session:
                print(json.dumps(bootstrap_library_status(session, source_root), indent=2))
            return
        payload = install_thailand(
            actor_email=arguments.actor_email,
            hub_code=arguments.hub_code,
            source_root=source_root,
            timeout_seconds=arguments.timeout_seconds,
            poll_seconds=arguments.poll_seconds,
        )
    except (OSError, ThailandBootstrapError, ValueError) as error:
        print(f"Thailand bootstrap stopped: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print("Thailand baseline is active:")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
