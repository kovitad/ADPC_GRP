"""Run a SIG evidence lookup as a background task in this process, so a slow gather finishes.

A district lookup on the shared SERVIR service has been measured at over 60 seconds, while a
web request cannot usefully wait that long. AD-03 sends GIS to the worker, and this is not GIS:
it is a network call to SIG, authorized by a token that lives only in this process's memory
(ADR-0002). A worker cannot see that token, so the task runs here and the browser polls it with
the same job tracker that watches an assessment (ADR-0025).

In-process, like the token store and the answer cache: a restart loses running lookups, and a
second API instance cannot see the first one's. Dev only, as the whole planner chat is.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Any
from uuid import uuid4

MAX_JOBS = 200
# A lookup holds a database connection for its whole run, and a run is minutes. The default
# SQLAlchemy pool is 5 with 10 overflow, so a handful of concurrent lookups would starve every
# other request. Queue beyond this rather than take a connection we cannot give back.
MAX_CONCURRENT = 3
# A finished lookup stays readable long enough for a person to come back to the tab.
KEEP_FINISHED = timedelta(minutes=30)
# A lookup that never finishes must not hold a slot for ever.
GIVE_UP_AFTER = timedelta(minutes=10)

QUEUED = "queued"
RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"


@dataclass
class SigLookup:
    """One person's lookup. `answer` is the same payload the chat route returns."""

    id: str
    session_id: str
    state: str = QUEUED
    label: str = ""
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    answer: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None

    @property
    def finished(self) -> bool:
        return self.state in {SUCCEEDED, FAILED}

    def expires_at(self) -> datetime:
        if self.finished and self.finished_at is not None:
            return self.finished_at + KEEP_FINISHED
        return self.started_at + GIVE_UP_AFTER

    def view(self) -> dict[str, Any]:
        """What the browser polls. The answer rides along once there is one."""

        elapsed = ((self.finished_at or datetime.now(UTC)) - self.started_at).total_seconds()
        payload: dict[str, Any] = {
            "job_id": self.id,
            "state": self.state,
            "elapsed_seconds": round(elapsed, 1),
        }
        if self.label:
            payload["label"] = self.label
        if self.state == SUCCEEDED:
            payload["answer"] = self.answer
        if self.state == FAILED:
            payload["error_code"] = self.error_code
            payload["error"] = self.error_message
        return payload


class SigLookupStore:
    """Lookups in progress, readable only by the session that started them."""

    def __init__(self) -> None:
        self._jobs: dict[str, SigLookup] = {}
        self._lock = Lock()

    def start(self, session_id: str, label: str = "") -> SigLookup:
        job = SigLookup(id=str(uuid4()), session_id=session_id, label=label)
        with self._lock:
            self._sweep()
            if len(self._jobs) >= MAX_JOBS:
                # Drop whatever is closest to expiry; that person simply asks again.
                oldest = min(self._jobs, key=lambda key: self._jobs[key].expires_at())
                del self._jobs[oldest]
            self._jobs[job.id] = job
        return job

    def mark_running(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None and job.state == QUEUED:
                job.state = RUNNING

    def succeed(self, job_id: str, answer: dict[str, Any]) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.state, job.answer = SUCCEEDED, answer
                job.finished_at = datetime.now(UTC)

    def fail(self, job_id: str, code: str, message: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.state, job.error_code, job.error_message = FAILED, code, message
                job.finished_at = datetime.now(UTC)

    def get(self, job_id: str, session_id: str) -> SigLookup | None:
        """Another session's job is not found rather than refused: it is not theirs to know of."""

        with self._lock:
            self._sweep()
            job = self._jobs.get(job_id)
            if job is None or job.session_id != session_id:
                return None
            return job

    def forget_session(self, session_id: str) -> None:
        with self._lock:
            for key in [k for k, v in self._jobs.items() if v.session_id == session_id]:
                del self._jobs[key]

    def _sweep(self) -> None:
        now = datetime.now(UTC)
        for key in [k for k, v in self._jobs.items() if v.expires_at() <= now]:
            del self._jobs[key]


sig_lookups = SigLookupStore()


@contextmanager
def app_session() -> Iterator[Any]:
    """A database session from the app's own provider, so a task uses the app's database.

    A background task has no request, so it cannot take the session dependency. Resolving the
    provider through the app picks up whatever the app is configured with, including the
    override a test installs — one code path, not one for the app and another for tests.
    """

    from api.dependencies import database_session
    from api.main import app

    provider = app.dependency_overrides.get(database_session, database_session)
    generator = provider()
    session = next(generator)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        generator.close()


_semaphore: asyncio.Semaphore | None = None


def _slots() -> Any:
    """One semaphore per event loop, created on the loop that will wait on it."""

    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    return _semaphore


def run_in_background(job_id: str, work: Any) -> None:
    """Start `work` (a coroutine) and record its outcome on the job, whatever happens."""

    async def guarded() -> None:
        try:
            # The job stays queued until a slot frees, so its state is the truth about it.
            async with _slots():
                sig_lookups.mark_running(job_id)
                answer = await asyncio.wait_for(work, GIVE_UP_AFTER.total_seconds())
        except TimeoutError:
            sig_lookups.fail(
                job_id,
                "LOOKUP_TIMED_OUT",
                "Global Risk did not answer in time. The connection was released; please ask "
                "again.",
            )
        except asyncio.CancelledError:
            sig_lookups.fail(job_id, "CANCELLED", "The lookup was cancelled.")
            raise
        except Exception as error:  # noqa: BLE001 - a job records every failure as its state
            code = getattr(error, "code", None) or type(error).__name__
            message = (
                getattr(error, "message", None) or "The Global Risk lookup could not be completed."
            )
            sig_lookups.fail(job_id, str(code), str(message))
        else:
            sig_lookups.succeed(job_id, answer)

    task = asyncio.create_task(guarded())
    # Hold a reference or the event loop may garbage-collect the task mid-flight.
    _running.add(task)
    task.add_done_callback(_running.discard)


_running: set[asyncio.Task[None]] = set()
