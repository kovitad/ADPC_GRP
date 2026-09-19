import logging
import signal
import time
from pathlib import Path
from threading import Event

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from api.settings import get_settings
from core.ai_allowance import release_stale_reservations
from core.assessment_jobs import claim_next_job, process_job
from core.db import get_engine, session_scope
from core.inspection_jobs import claim_next_inspection, process_inspection
from core.storage import LocalStorage

logger = logging.getLogger("grp.worker")
stop_event = Event()
POLL_SECONDS = 3
HOUSEKEEPING_SECONDS = 60


def _request_stop(_signum: int, _frame: object) -> None:
    stop_event.set()


def run() -> None:
    """Claim and run assessment jobs; release stale AI reservations every minute."""

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    settings = get_settings()
    storage = LocalStorage(settings.storage_root)
    logger.info("Worker started (lease %d min)", settings.job_lease_minutes)
    last_housekeeping = 0.0
    while not stop_event.is_set():
        if time.monotonic() - last_housekeeping >= HOUSEKEEPING_SECONDS:
            release_reservations_once()
            last_housekeeping = time.monotonic()
            logger.info("Worker heartbeat")
        worked = run_one_job(storage, settings.job_lease_minutes)
        # Assessments are a planner waiting; inspections are an Admin looking. Planners win.
        if not worked:
            worked = run_one_inspection(settings.data_in_root, settings.job_lease_minutes, storage)
        if not worked:
            stop_event.wait(POLL_SECONDS)


def run_one_job(storage: LocalStorage, lease_minutes: int) -> bool:
    """Claim and process at most one job. Returns True if a job was handled."""

    try:
        with Session(get_engine()) as session:
            assessment_id = claim_next_job(session, lease_minutes=lease_minutes)
            if assessment_id is None:
                return False
            logger.info("Claimed assessment %s", assessment_id)
            state = process_job(session, storage, assessment_id)
            logger.info("Assessment %s finished: %s", assessment_id, state)
            return True
    except SQLAlchemyError:
        logger.exception("Job loop database error; will retry")
        return False


def run_one_inspection(root: Path, lease_minutes: int, storage: LocalStorage | None = None) -> bool:
    """Claim and run at most one data inspection (ADR-0006). Returns True if one was handled."""

    try:
        with Session(get_engine()) as session:
            inspection_id = claim_next_inspection(session, lease_minutes=lease_minutes)
            if inspection_id is None:
                return False
            logger.info("Claimed inspection %s", inspection_id)
            state = process_inspection(session, root, inspection_id, storage)
            logger.info("Inspection %s finished: %s", inspection_id, state)
            return True
    except SQLAlchemyError:
        logger.exception("Inspection loop database error; will retry")
        return False


def release_reservations_once() -> int:
    """Section 10.4: release AI reservations older than 10 minutes, every minute."""

    try:
        with session_scope() as session:
            released = release_stale_reservations(session)
    except SQLAlchemyError:
        logger.exception("Could not release stale AI reservations")
        return 0
    if released:
        logger.info("Released %d stale AI reservations", released)
    return released


if __name__ == "__main__":
    run()
