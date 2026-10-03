"""Relay bmatraffic.com camera pictures into the flood page, for the local demo only (ADR-0051).

bmatraffic.com plays a camera by loading ``show.aspx?image=<id>`` about once a second. It sends a
real picture only to a session that has opened its home page and a player page; any other request
gets a blank picture of about 1.4 KB. The picture is always that of the camera whose player page
the session opened last; the ``image`` number is ignored. So each camera needs its own session.
A browser never sends that session cookie from inside another site, so the picture cannot show
in GRP's page directly. With the Product Owner's approval
for the local demo (3 October 2026), GRP opens one such session per watched camera, as an
ordinary visitor would, and passes the pictures to signed-in officers.

Limits, so GRP stays a light and honest visitor:

- off unless ``BMATRAFFIC_RELAY_ENABLED`` is set (the Docker Desktop stack only);
- only registry cameras whose provider is BMA_TRAFFIC; anything else is refused;
- on demand: a picture is fetched only when someone asks, at most once a second per camera and
  shared by every viewer, and at most ``MAX_FETCHES_PER_SECOND`` overall;
- pictures stay in memory for a few seconds and are never written anywhere;
- requests name GRP in the User-Agent, and the page stops asking after 10 minutes unless the
  officer chooses to continue.

BMA has not yet given permission for wider use; that is a Gate B question in the BMA request.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx

BASE = "http://www.bmatraffic.com"
PROVIDER = "BMA_TRAFFIC"
USER_AGENT = "GRP-flood-pilot/0.1 (ADPC SERVIR pilot; local demo relay)"
TIMEOUT_SECONDS = 8.0
FRAME_SECONDS = 1.0
SESSION_SECONDS = 15 * 60
# A camera nobody has asked for in this long loses its session and picture (memory only).
IDLE_SECONDS = 30.0
MAX_SESSIONS = 16
MAX_FETCHES_PER_SECOND = 8
MAX_BYTES = 512 * 1024
# The blank picture sent without a session is about 1.4 KB; real frames are about 20 KB.
MIN_PICTURE_BYTES = 4096
JPEG = b"\xff\xd8"

# (camera ID whose session makes the call, path) -> (status, content type, body)
Fetch = Callable[[str, str], tuple[int, str, bytes]]


class RelayUnavailable(RuntimeError):
    """bmatraffic.com did not give a picture."""


class RelayBusy(RuntimeError):
    """GRP has already asked bmatraffic.com for as many pictures as it allows this second."""


@dataclass(frozen=True)
class Frame:
    body: bytes
    fetched_at: float
    retrieved_at: datetime


@dataclass
class _Visit:
    """One camera's own visitor session and its latest picture."""

    lock: threading.Lock = field(default_factory=threading.Lock)
    client: httpx.Client | None = None
    opened_at: float | None = None
    used_at: float = 0.0
    frame: Frame | None = None

    def close(self) -> None:
        if self.client is not None:
            self.client.close()
            self.client = None


class BmatrafficRelay:
    """A session per watched camera and a short in-memory cache. ``fetch`` is replaced in tests."""

    def __init__(self, fetch: Fetch | None = None, clock: Callable[[], float] = time.monotonic):
        self._fetch_override = fetch
        self._clock = clock
        self._lock = threading.Lock()  # guards the visits and the overall budget
        self._visits: dict[str, _Visit] = {}
        self._recent: deque[float] = deque()

    def _fetch(self, visit: _Visit, camera_id: str, path: str) -> tuple[int, str, bytes]:
        if self._fetch_override is not None:
            return self._fetch_override(camera_id, path)
        if visit.client is None:
            visit.client = httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False,
                                        headers={"User-Agent": USER_AGENT})
        try:
            response = visit.client.get(BASE + path)
        except httpx.HTTPError as error:
            raise RelayUnavailable(type(error).__name__) from None
        return response.status_code, response.headers.get("content-type", ""), response.content

    def _open_session(self, visit: _Visit, camera_id: str) -> None:
        """Visit the home page and this camera's player page, as a person would."""

        visit.close()
        for path in ("/index.aspx", f"/PlayVideo.aspx?ID={camera_id}"):
            status, _, _ = self._fetch(visit, camera_id, path)
            if status != 200:
                raise RelayUnavailable(f"HTTP {status}")
        visit.opened_at = self._clock()

    def _picture(self, visit: _Visit, camera_id: str) -> bytes | None:
        """A real JPEG frame, or None for the blank picture a lapsed session gets."""

        stamp = int(time.time() * 1000)
        status, content_type, body = self._fetch(
            visit, camera_id, f"/show.aspx?image={camera_id}&&time={stamp}")
        if status != 200:
            raise RelayUnavailable(f"HTTP {status}")
        if len(body) > MAX_BYTES:
            raise RelayUnavailable("Picture too large")
        if not content_type.startswith("image/jpeg") or not body.startswith(JPEG):
            return None
        return body if len(body) >= MIN_PICTURE_BYTES else None

    def _visit(self, camera_id: str, now: float) -> _Visit:
        with self._lock:
            for key, old in list(self._visits.items()):
                if now - old.used_at > IDLE_SECONDS and not old.lock.locked():
                    old.close()
                    del self._visits[key]
            visit = self._visits.get(camera_id)
            if visit is None:
                idle = sorted((v.used_at, k) for k, v in self._visits.items()
                              if not v.lock.locked())
                while len(self._visits) >= MAX_SESSIONS and idle:
                    _, key = idle.pop(0)
                    self._visits.pop(key).close()
                if len(self._visits) >= MAX_SESSIONS:
                    raise RelayBusy()
                visit = self._visits[camera_id] = _Visit()
            visit.used_at = now
            return visit

    def _spend(self, now: float) -> None:
        with self._lock:
            while self._recent and now - self._recent[0] >= 1.0:
                self._recent.popleft()
            if len(self._recent) >= MAX_FETCHES_PER_SECOND:
                raise RelayBusy()
            self._recent.append(now)

    def frame(self, camera_id: str) -> Frame:
        if not camera_id.isdigit():
            raise ValueError("bmatraffic camera IDs are numbers")
        visit = self._visit(camera_id, self._clock())
        with visit.lock:
            now = self._clock()
            held = visit.frame
            if held is not None and now - held.fetched_at < FRAME_SECONDS:
                return held
            self._spend(now)
            if visit.opened_at is None or now - visit.opened_at > SESSION_SECONDS:
                self._open_session(visit, camera_id)
            body = self._picture(visit, camera_id)
            if body is None:
                # The session has lapsed: open a new one once, then give up.
                self._open_session(visit, camera_id)
                body = self._picture(visit, camera_id)
            if body is None:
                raise RelayUnavailable("No picture")
            visit.frame = Frame(body=body, fetched_at=now, retrieved_at=datetime.now(UTC))
            return visit.frame


_relay: BmatrafficRelay | None = None
_relay_lock = threading.Lock()


def shared_relay() -> BmatrafficRelay:
    global _relay
    with _relay_lock:
        if _relay is None:
            _relay = BmatrafficRelay()
        return _relay


def frame_url(pilot_id: str, camera_id: str) -> str:
    return f"/api/v1/pilot/flood/{pilot_id}/cameras/{quote(camera_id, safe='')}/frame.jpg"


def with_relay(camera: dict[str, Any], pilot_id: str) -> dict[str, Any]:
    """Give a bmatraffic camera an in-page live view through the relay."""

    if camera.get("provider") != PROVIDER or camera.get("placeholder"):
        return camera
    return {**camera, "live": {"kind": "frames", "url": frame_url(pilot_id, camera["camera_id"])}}
