"""Relay bmatraffic.com camera pictures into the flood page, for the local demo only (ADR-0051).

bmatraffic.com plays a camera by loading ``show.aspx?image=<id>`` about once a second. It sends a
real picture only to a session that has opened its home page and a player page; any other request
gets a blank picture of about 1.4 KB. A browser never sends that session cookie from inside
another site, so the picture cannot show in GRP's page directly. With the Product Owner's approval
for the local demo (3 October 2026), GRP opens one such session as an ordinary visitor and passes
the pictures to signed-in officers.

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
from dataclasses import dataclass
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
KEEP_SECONDS = 30.0
MAX_FETCHES_PER_SECOND = 8
MAX_BYTES = 512 * 1024
# The blank picture sent without a session is about 1.4 KB; real frames are about 20 KB.
MIN_PICTURE_BYTES = 4096
JPEG = b"\xff\xd8"

Fetch = Callable[[str], tuple[int, str, bytes]]


class RelayUnavailable(RuntimeError):
    """bmatraffic.com did not give a picture."""


class RelayBusy(RuntimeError):
    """GRP has already asked bmatraffic.com for as many pictures as it allows this second."""


@dataclass(frozen=True)
class Frame:
    body: bytes
    fetched_at: float
    retrieved_at: datetime


class BmatrafficRelay:
    """One shared visitor session and a short in-memory cache. ``fetch`` is replaced in tests."""

    def __init__(self, fetch: Fetch | None = None, clock: Callable[[], float] = time.monotonic):
        self._fetch_override = fetch
        self._client: httpx.Client | None = None
        self._clock = clock
        self._lock = threading.Lock()
        self._primed_at: float | None = None
        self._frames: dict[str, Frame] = {}
        self._recent: deque[float] = deque()

    def _fetch(self, path: str) -> tuple[int, str, bytes]:
        if self._fetch_override is not None:
            return self._fetch_override(path)
        if self._client is None:
            self._client = httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False,
                                        headers={"User-Agent": USER_AGENT})
        try:
            response = self._client.get(BASE + path)
        except httpx.HTTPError as error:
            raise RelayUnavailable(type(error).__name__) from None
        return response.status_code, response.headers.get("content-type", ""), response.content

    def _open_session(self, camera_id: str) -> None:
        """Visit the home page and one player page, as a person would before watching."""

        if self._client is not None:
            self._client.cookies.clear()
        for path in ("/index.aspx", f"/PlayVideo.aspx?ID={camera_id}"):
            status, _, _ = self._fetch(path)
            if status != 200:
                raise RelayUnavailable(f"HTTP {status}")
        self._primed_at = self._clock()

    def _picture(self, camera_id: str) -> bytes | None:
        """A real JPEG frame, or None for the blank picture a lapsed session gets."""

        stamp = int(time.time() * 1000)
        status, content_type, body = self._fetch(f"/show.aspx?image={camera_id}&&time={stamp}")
        if status != 200:
            raise RelayUnavailable(f"HTTP {status}")
        if len(body) > MAX_BYTES:
            raise RelayUnavailable("Picture too large")
        if not content_type.startswith("image/jpeg") or not body.startswith(JPEG):
            return None
        return body if len(body) >= MIN_PICTURE_BYTES else None

    def _spend(self, now: float) -> None:
        while self._recent and now - self._recent[0] >= 1.0:
            self._recent.popleft()
        if len(self._recent) >= MAX_FETCHES_PER_SECOND:
            raise RelayBusy()
        self._recent.append(now)

    def frame(self, camera_id: str) -> Frame:
        if not camera_id.isdigit():
            raise ValueError("bmatraffic camera IDs are numbers")
        with self._lock:
            now = self._clock()
            held = self._frames.get(camera_id)
            if held is not None and now - held.fetched_at < FRAME_SECONDS:
                return held
            self._spend(now)
            if self._primed_at is None or now - self._primed_at > SESSION_SECONDS:
                self._open_session(camera_id)
            body = self._picture(camera_id)
            if body is None:
                # The session has lapsed: open a new one once, then give up.
                self._open_session(camera_id)
                body = self._picture(camera_id)
            if body is None:
                raise RelayUnavailable("No picture")
            frame = Frame(body=body, fetched_at=now, retrieved_at=datetime.now(UTC))
            self._frames = {k: v for k, v in self._frames.items()
                            if now - v.fetched_at < KEEP_SECONDS}
            self._frames[camera_id] = frame
            return frame


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
