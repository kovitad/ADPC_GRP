"""Nonthaburi in the live flood pilot, and the Pak Kret snapshot relay (ADR-0057)."""

from __future__ import annotations

import pytest

from core.flood_evidence.areas import in_pilot, pilot_areas
from core.flood_evidence.camera_relay import RelayBusy, RelayUnavailable
from core.flood_evidence.config import pilot_config
from core.flood_evidence.planner_answer import in_live_area
from core.flood_evidence.snapshot_relay import MAX_FETCHES_PER_SECOND, SnapshotRelay

CONFIG = pilot_config("bangkok")
JPEG = b"\xff\xd8" + b"0" * 4000


def test_nonthaburi_districts_and_sub_districts_are_in_the_pilot() -> None:
    assert in_pilot(CONFIG, "1204") and in_pilot(CONFIG, "120401")
    assert in_live_area("1206") and in_live_area("1030")
    assert not in_pilot(CONFIG, "1301") and not in_live_area("3303")
    names = {a["admin_code"]: a["name"] for a in pilot_areas(CONFIG)}
    assert names["1201"] == "Mueang Nonthaburi" and names["1206"] == "Pak Kret"


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_a_snapshot_is_shared_for_a_second_then_fetched_again() -> None:
    calls = []
    clock = Clock()

    def fetch(url):
        calls.append(url)
        return 200, "image/jpg", JPEG

    relay = SnapshotRelay(fetch=fetch, clock=clock)
    first = relay.frame("pakkret:CAMPK001", "https://example.test/a.jpg")
    assert relay.frame("pakkret:CAMPK001", "https://example.test/a.jpg") is first
    clock.now += 1.5
    relay.frame("pakkret:CAMPK001", "https://example.test/a.jpg")
    assert len(calls) == 2


def test_the_overall_budget_and_bad_pictures_are_refused() -> None:
    clock = Clock()
    relay = SnapshotRelay(fetch=lambda _url: (200, "image/jpeg", JPEG), clock=clock)
    for n in range(MAX_FETCHES_PER_SECOND):
        relay.frame(f"cam{n}", "https://example.test/x.jpg")
    with pytest.raises(RelayBusy):
        relay.frame("one-more", "https://example.test/x.jpg")
    clock.now += 2
    blank = SnapshotRelay(fetch=lambda _url: (200, "text/html", b"<html>"), clock=clock)
    with pytest.raises(RelayUnavailable):
        blank.frame("cam", "https://example.test/x.jpg")
    failing = SnapshotRelay(fetch=lambda _url: (404, "text/html", b""), clock=clock)
    with pytest.raises(RelayUnavailable):
        failing.frame("cam", "https://example.test/x.jpg")


def test_the_cache_buster_keeps_the_cameras_own_query() -> None:
    from core.flood_evidence.snapshot_relay import with_stamp

    url = "https://www.thaiclouderp.com/src/img.php?name=CAMPK003_thumb.jpg"
    assert with_stamp(url, 7) == url + "&t=7"
    assert with_stamp("https://example.test/a.jpg", 7) == "https://example.test/a.jpg?t=7"
