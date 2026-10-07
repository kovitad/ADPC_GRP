"""The local demo relay for bmatraffic.com pictures (ADR-0051): gentle, shared and never stored."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from core.flood_evidence.camera_relay import (
    IDLE_SECONDS,
    MAX_FETCHES_PER_SECOND,
    BmatrafficRelay,
    RelayBusy,
    RelayUnavailable,
    with_relay,
)
from core.flood_evidence.cameras import nearby_cameras, parse_registry

PICTURE = b"\xff\xd8" + b"x" * 20_000
BLANK = b"\xff\xd8" + b"x" * 1_400


class Site:
    """A stand-in for bmatraffic.com. Each session shows the camera whose player page it opened
    last, whatever ``image`` number is asked for, and nothing before it has opened the home page."""

    def __init__(self, pictures=None) -> None:
        self.calls: list[str] = []
        self.home: set[str] = set()
        self.playing: dict[str, str] = {}
        self.pictures = pictures

    def __call__(self, session: str, path: str) -> tuple[int, str, bytes]:
        self.calls.append(path.split("&")[0])
        if path == "/index.aspx":
            self.home.add(session)
            return 200, "text/html", b"<html>"
        if path.startswith("/PlayVideo.aspx?ID="):
            self.playing[session] = path.split("=")[1]
            return 200, "text/html", b"<html>"
        if self.pictures:
            return self.pictures.pop(0)
        if session not in self.home or session not in self.playing:
            return 200, "image/jpeg", BLANK
        return 200, "image/jpeg", picture_of(self.playing[session])


def picture_of(camera: str) -> bytes:
    return PICTURE[:2] + camera.encode() + b"x" * 20_000


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_one_session_then_one_shared_picture_a_second() -> None:
    site, clock = Site(), Clock()
    relay = BmatrafficRelay(fetch=site, clock=clock)
    first = relay.frame("1362")
    assert first.body == picture_of("1362")
    assert site.calls == ["/index.aspx", "/PlayVideo.aspx?ID=1362", "/show.aspx?image=1362"]
    clock.now += 0.5
    assert relay.frame("1362") is first  # every viewer shares it within the second
    clock.now += 0.6
    relay.frame("1362")
    assert site.calls.count("/show.aspx?image=1362") == 2
    assert site.calls.count("/index.aspx") == 1


def test_a_blank_picture_opens_a_new_session_once_then_gives_up() -> None:
    blank = (200, "image/jpeg", BLANK)
    site = Site(pictures=[blank, (200, "image/jpeg", PICTURE)])
    relay = BmatrafficRelay(fetch=site, clock=Clock())
    assert relay.frame("1108").body == PICTURE
    assert site.calls.count("/index.aspx") == 2

    site = Site(pictures=[blank, blank])
    with pytest.raises(RelayUnavailable):
        BmatrafficRelay(fetch=site, clock=Clock()).frame("1108")


@pytest.mark.parametrize("answer", [(200, "text/html", b"<html>" * 5000),
                                    (500, "text/html", b"error"),
                                    (200, "image/jpeg", b"")])
def test_anything_but_a_real_picture_is_unavailable(answer) -> None:
    site = Site(pictures=[answer, answer])
    with pytest.raises(RelayUnavailable):
        BmatrafficRelay(fetch=site, clock=Clock()).frame("1108")


def test_each_camera_has_its_own_session_and_shows_its_own_picture() -> None:
    # bmatraffic.com shows the session's last opened camera: one shared session showed the same
    # picture for every camera (seen by the Product Owner on 3 October 2026).
    site, clock = Site(), Clock()
    relay = BmatrafficRelay(fetch=site, clock=clock)
    assert relay.frame("1362").body == picture_of("1362")
    assert relay.frame("1108").body == picture_of("1108")
    clock.now += 1.0
    assert relay.frame("1362").body == picture_of("1362")
    assert site.calls.count("/index.aspx") == 2  # one session each, opened once


def test_an_idle_camera_loses_its_session_and_picture() -> None:
    site, clock = Site(), Clock()
    relay = BmatrafficRelay(fetch=site, clock=clock)
    relay.frame("1362")
    clock.now += IDLE_SECONDS + 1
    relay.frame("1108")  # tidies away 1362
    clock.now += 0.1
    relay.frame("1362")
    assert site.calls.count("/PlayVideo.aspx?ID=1362") == 2


def test_grp_asks_for_at_most_a_few_pictures_a_second_overall() -> None:
    site, clock = Site(), Clock()
    relay = BmatrafficRelay(fetch=site, clock=clock)
    for camera in range(MAX_FETCHES_PER_SECOND):
        relay.frame(str(1000 + camera))
    with pytest.raises(RelayBusy):
        relay.frame("2000")
    clock.now += 1.0
    relay.frame("2000")


def test_only_numeric_bmatraffic_ids_are_asked_for() -> None:
    site = Site()
    with pytest.raises(ValueError):
        BmatrafficRelay(fetch=site, clock=Clock()).frame("../index.aspx")
    assert site.calls == []


def _camera(provider: str, camera_id: str, live=None, lat=13.8390) -> dict:
    return {
        "camera_id": camera_id, "provider": provider, "provider_camera_id": "1",
        "name": {"th": "x", "en": "x"}, "lat": lat, "lon": 100.5300,
        "heading_deg": None, "fov_deg": None, "access_mode": "embed",
        "viewer_url": "https://example.test/view", "stream_url": None, "snapshot_url": None,
        "status": "unknown", "status_checked_at": None, "ingestion_allowed": False,
        "cv_allowed": False, "source_label": "Test", "live": live,
    }


def test_only_bmatraffic_cameras_get_relayed_and_they_rank_after_hls() -> None:
    relayed = with_relay({"camera_id": "bmatraffic:1362", "provider": "BMA_TRAFFIC"}, "bangkok")
    assert relayed["live"] == {
        "kind": "frames", "url": "/api/v1/pilot/flood/bangkok/cameras/bmatraffic%3A1362/frame.jpg"}
    other = {"camera_id": "bma:1", "provider": "BMA_DDS", "live": None}
    assert with_relay(other, "bangkok") is other

    cameras = parse_registry({"cameras": [
        _camera("BMA_DDS", "mp4", {"kind": "mp4", "url": "https://x/a.mp4"}),
        _camera("BMA_TRAFFIC", "traffic", lat=13.8391),
        _camera("ITIC_LONGDO", "hls", {"kind": "hls", "url": "https://x/a.m3u8"}, lat=13.8392),
    ]})
    road = {"type": "LineString", "coordinates": [[100.53, 13.839], [100.531, 13.839]]}
    now = datetime(2026, 10, 3, tzinfo=UTC)
    found = nearby_cameras(cameras, road, now, 400,
                           decorate=lambda c: with_relay(c, "bangkok"))
    assert [c["camera_id"] for c in found] == ["hls", "traffic", "mp4"]
