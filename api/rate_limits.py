from __future__ import annotations

import threading
import time
from collections import deque

from api.errors import GrpError


class SlidingWindowLimiter:
    """Per-key sliding-window request counter held in process memory.

    Adequate for the single grp-api process of MVP 1 (Section 6.2). Move the counters to
    PostgreSQL or a shared store before running more than one API worker.
    """

    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._hits: dict[tuple[str, str], deque[float]] = {}

    def check(self, bucket: str, key: str, limit: int, window_seconds: float) -> None:
        now = self._clock()
        with self._lock:
            hits = self._hits.setdefault((bucket, key), deque())
            while hits and hits[0] <= now - window_seconds:
                hits.popleft()
            if len(hits) >= limit:
                # Seconds until the oldest counted request leaves the window.
                raise rate_limited(max(1, int(hits[0] + window_seconds - now) + 1))
            hits.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


def rate_limited(retry_after: int = 5) -> GrpError:
    return GrpError(
        429,
        "RATE_LIMITED",
        "Too many requests. Please wait a moment.",
        headers={"Retry-After": str(retry_after)},
    )


limiter = SlidingWindowLimiter()
