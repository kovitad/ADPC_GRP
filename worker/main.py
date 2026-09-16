import logging
import signal
from threading import Event

logger = logging.getLogger("grp.worker")
stop_event = Event()


def _request_stop(_signum: int, _frame: object) -> None:
    stop_event.set()


def run() -> None:
    """Run the worker shell until the PostgreSQL job loop is implemented in Increment 1."""

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    logger.warning("Worker foundation started; assessment job claiming is not implemented yet")
    while not stop_event.wait(60):
        logger.info("Worker foundation heartbeat")


if __name__ == "__main__":
    run()
