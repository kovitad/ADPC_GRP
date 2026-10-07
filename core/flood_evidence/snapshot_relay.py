"""Relay plain camera snapshots (Pak Kret municipality) into GRP pages (ADR-0057).

Pak Kret's cameras serve a JPEG at a fixed address with no login or session, so the relay is
simpler than bmatraffic's (ADR-0051). Its limits are the same:

- it runs only when the local camera relay is switched on (``BMATRAFFIC_RELAY_ENABLED``);
- only registry cameras of a snapshot provider are fetched, at the address in the registry, never
  an address from a request;
- on demand, at most once a second per camera (shared by every viewer), and at most
  ``MAX_FETCHES_PER_SECOND`` overall;
- pictures stay in memory for a second and are never written anywhere.

Until the municipality replies, these pictures are shown on screen only and are not put in
downloaded reports (Product Owner, 4 October 2026).
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime

import httpx

from core.flood_evidence.camera_relay import Frame, RelayBusy, RelayUnavailable

PROVIDERS = frozenset({"PAKKRET_CCTV"})
USER_AGENT = "GRP-flood-pilot/0.1 (ADPC SERVIR pilot; camera relay)"
TIMEOUT_SECONDS = 8.0
FRAME_SECONDS = 1.0
MAX_FETCHES_PER_SECOND = 8
MAX_BYTES = 512 * 1024
MIN_PICTURE_BYTES = 2048
JPEG = b"\xff\xd8"

# (snapshot URL) -> (status, content type, body)
Fetch = Callable[[str], tuple[int, str, bytes]]


def with_stamp(url: str, stamp: int) -> str:
    """The snapshot address with a cache-busting time added. Appended rather than passed as
    ``params``, because httpx would replace the address's own query (and drop ``name=``)."""

    return f"{url}{'&' if '?' in url else '?'}t={stamp}"


class SnapshotRelay:
    """A one-second shared cache per camera and an overall budget; tests replace ``fetch``."""

    def __init__(self, fetch: Fetch | None = None, clock: Callable[[], float] = time.monotonic):
        self._fetch_override = fetch
        self._clock = clock
        self._lock = threading.Lock()
        self._held: dict[str, Frame] = {}
        self._recent: deque[float] = deque()
        self._client: httpx.Client | None = None

    def _fetch(self, url: str) -> tuple[int, str, bytes]:
        if self._fetch_override is not None:
            return self._fetch_override(url)
        if self._client is None:
            self._client = httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False,
                                        headers={"User-Agent": USER_AGENT})
        stamp = int(time.time() * 1000)
        try:
            response = self._client.get(with_stamp(url, stamp))
        except httpx.HTTPError as error:
            raise RelayUnavailable(type(error).__name__) from None
        return response.status_code, response.headers.get("content-type", ""), response.content

    def frame(self, camera_id: str, url: str) -> Frame:
        now = self._clock()
        with self._lock:
            held = self._held.get(camera_id)
            if held is not None and now - held.fetched_at < FRAME_SECONDS:
                return held
            while self._recent and now - self._recent[0] >= 1.0:
                self._recent.popleft()
            if len(self._recent) >= MAX_FETCHES_PER_SECOND:
                raise RelayBusy()
            self._recent.append(now)
        status, content_type, body = self._fetch(url)
        if status != 200:
            raise RelayUnavailable(f"HTTP {status}")
        if len(body) > MAX_BYTES:
            raise RelayUnavailable("Picture too large")
        if not content_type.startswith("image/") or not body.startswith(JPEG) \
                or len(body) < MIN_PICTURE_BYTES:
            raise RelayUnavailable("No picture")
        frame = Frame(body=body, fetched_at=now, retrieved_at=datetime.now(UTC))
        with self._lock:
            self._held[camera_id] = frame
            # Keep memory small: drop pictures nobody asked for in the last minute.
            for key in [k for k, f in self._held.items() if now - f.fetched_at > 60]:
                del self._held[key]
        return frame


_relay: SnapshotRelay | None = None
_relay_lock = threading.Lock()


def shared_snapshot_relay() -> SnapshotRelay:
    global _relay
    with _relay_lock:
        if _relay is None:
            _relay = SnapshotRelay()
        return _relay
