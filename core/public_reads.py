"""When a public feed was last read from outside, so Share data can say "Global Risk is reading
it" (ADR-0052, ADR-0061).

Kept in the API process's memory only: one time and a count per feed, no addresses. It resets
when the API restarts, which the page says.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime

_lock = threading.Lock()
# Counts start when the API process starts.
STARTED = datetime.now(UTC).isoformat().replace("+00:00", "Z")
_reads: dict[str, dict[str, object]] = {}


def record(key: str, now: datetime | None = None) -> None:
    with _lock:
        entry = _reads.setdefault(key, {"count": 0, "last": None})
        entry["count"] = int(entry["count"]) + 1
        entry["last"] = (now or datetime.now(UTC)).isoformat().replace("+00:00", "Z")


def snapshot() -> dict[str, dict[str, object]]:
    with _lock:
        return {key: dict(value) for key, value in _reads.items()}


def reset() -> None:
    with _lock:
        _reads.clear()
