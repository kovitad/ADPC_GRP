import logging
import signal
from threading import Event

from sqlalchemy.exc import SQLAlchemyError

from core.ai_allowance import release_stale_reservations
from core.db import session_scope

logger = logging.getLogger("grp.worker")
stop_event = Event()


def _request_stop(_signum: int, _frame: object) -> None:
    stop_event.set()


def run() -> None:
    """Run the worker shell until the PostgreSQL job loop is implemented in Increment 1."""

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    logger.warning("Worker started; assessment job claiming is not implemented yet (Increment 1)")
    while not stop_event.wait(60):
        release_reservations_once()
        logger.info("Worker heartbeat")


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
