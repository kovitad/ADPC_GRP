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
from core.boundary_import import (
    PLATFORM_BOUNDARY_DATASET_ID,
    BoundaryImportError,
    process_boundary_import,
)
from core.data_import_jobs import ImportClaim, claim_next_import, fail_import, version_id_for_import
from core.data_library_models import DataImportJob
from core.db import get_engine, session_scope
from core.hazard_import import (
    PLATFORM_HAZARD_DATASET_ID,
    HazardImportError,
    process_hazard_import,
)
from core.import_staging import cleanup_import_staging
from core.inspection_jobs import claim_next_inspection, process_inspection
from core.shelter_import import (
    PLATFORM_SHELTER_DATASET_ID,
    ShelterImportError,
    process_shelter_import,
)
from core.storage import LocalStorage
from core.thailand_full_import import (
    ThailandFullImportError,
    process_hierarchy_import,
    process_point_import,
    process_vulnerability_import,
)

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
        # A Planner waiting on an assessment wins. Imports run before optional source previews.
        if not worked:
            worked = run_one_import(
                storage,
                settings.data_in_root,
                settings.job_lease_minutes,
            )
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


def run_one_import(storage: LocalStorage, root: Path, lease_minutes: int) -> bool:
    """Claim and run at most one fenced data-library import."""

    try:
        with Session(get_engine()) as session:
            return _run_one_import_session(session, storage, root, lease_minutes)
    except SQLAlchemyError:
        logger.exception("Data-import loop database error; will retry")
        return False


def _run_one_import_session(
    session: Session, storage: LocalStorage, root: Path, lease_minutes: int
) -> bool:
    claim = claim_next_import(session, lease_minutes=lease_minutes)
    if claim is None:
        return False
    logger.info("Claimed data import %s attempt %d", claim.import_id, claim.attempt)
    try:
        job = session.get(DataImportJob, claim.import_id)
        if job is None:
            raise BoundaryImportError("This import job no longer exists")
        if job.category == "boundary":
            if job.source_ref == "administrative_boundary":
                version_id = process_hierarchy_import(
                    session, storage, root, claim, lease_minutes=lease_minutes
                )
            else:
                version_id = process_boundary_import(
                    session,
                    storage,
                    root,
                    claim,
                    lease_minutes=lease_minutes,
                )
        elif job.category == "evacuation_centers":
            shelter_root = storage.root if job.source_mode == "browser_upload" else root
            version_id = process_shelter_import(
                session,
                storage,
                shelter_root,
                claim,
                lease_minutes=lease_minutes,
            )
        elif job.category == "hazard":
            version_id = process_hazard_import(
                session,
                storage,
                root,
                claim,
                lease_minutes=lease_minutes,
            )
        elif job.category in {
            "volunteer_centers",
            "early_warning_resources",
            "village_locations",
        }:
            version_id = process_point_import(
                session, storage, root, claim, lease_minutes=lease_minutes
            )
        elif job.category.startswith("vulnerability_"):
            version_id = process_vulnerability_import(
                session, storage, root, claim, lease_minutes=lease_minutes
            )
        else:
            raise BoundaryImportError("This import category is not enabled yet")
        if version_id is None:
            logger.warning("Data import %s lost its lease", claim.import_id)
        else:
            logger.info("Data import %s published version %s", claim.import_id, version_id)
            _cleanup_browser_source(storage, job)
    except (
        BoundaryImportError,
        ShelterImportError,
        HazardImportError,
        ThailandFullImportError,
    ) as error:
        logger.warning("Data import %s failed validation: %s", claim.import_id, error)
        failed = fail_import(
            session,
            claim,
            error_code="IMPORT_VALIDATION_FAILED",
            report={"message": str(error)},
        )
        if failed:
            _cleanup_failed_import(session, storage, claim)
    except Exception:  # noqa: BLE001 - one malformed import must not stop the worker
        logger.exception("Data import %s failed", claim.import_id)
        failed = fail_import(
            session,
            claim,
            error_code="IMPORT_PROCESSING_FAILED",
            report={"message": "The import could not be completed. Use the support reference."},
        )
        if failed:
            _cleanup_failed_import(session, storage, claim)
    return True


def _cleanup_failed_import(session: Session, storage: LocalStorage, claim: ImportClaim) -> None:
    """Remove unreferenced bytes after a handled failure; never remove a published version."""

    try:
        cleanup_import_staging(storage, claim)
        session.expire_all()
        job = session.get(DataImportJob, claim.import_id)
        if job is not None and job.dataset_version_id is None:
            dataset_ids = {
                "boundary": PLATFORM_BOUNDARY_DATASET_ID,
                "evacuation_centers": PLATFORM_SHELTER_DATASET_ID,
                "hazard": PLATFORM_HAZARD_DATASET_ID,
            }
            dataset_id = dataset_ids.get(job.category)
            if dataset_id is not None:
                version_id = version_id_for_import(claim.import_id)
                storage.delete_prefix(f"datasets/{dataset_id}/{version_id}")
            _cleanup_browser_source(storage, job)
    except Exception:  # noqa: BLE001 - cleanup is retried by later housekeeping
        logger.exception("Could not clean failed data import %s", claim.import_id)


def _cleanup_browser_source(storage: LocalStorage, job: DataImportJob) -> None:
    """Remove only the generated quarantine subtree after bytes are promoted or refused."""

    if job.source_mode != "browser_upload":
        return
    expected = f"quarantine/browser-uploads/{job.id}/source/"
    if not job.source_ref.startswith(expected):
        logger.error("Refusing unexpected browser-upload cleanup path for %s", job.id)
        return
    storage.delete_prefix(f"quarantine/browser-uploads/{job.id}")


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
