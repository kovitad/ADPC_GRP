"""CCTV P0 registry rules (ADR-0039): a camera is a viewer link and a hint, never evidence."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from core.flood_evidence.cameras import (
    CANNOT_CONFIRM,
    OFFICER_CAN_LOOK,
    CameraRegistryError,
    camera_registry,
    corroboration_role,
    frame_capable,
    nearby_cameras,
    parse_camera,
    parse_registry,
)
from core.flood_evidence.config import DATA

NOW = datetime(2026, 10, 3, 3, 0, tzinfo=UTC)
# A short east-west road just north of the camera.
ROAD = {"type": "LineString", "coordinates": [[100.5410, 13.8410], [100.5420, 13.8410]]}


def _real(**changes):
    item = {
        "camera_id": "bma:TEST-1",
        "provider": "BMA_DSD",
        "provider_camera_id": "TEST-1",
        "name": {"en": "Test camera"},
        "lat": 13.8400,
        "lon": 100.5415,
        "heading_deg": 0,
        "fov_deg": 90,
        "access_mode": "external_viewer",
        "viewer_url": "https://example.test/viewer",
        "stream_url": None,
        "snapshot_url": None,
        "status": "online",
        "status_checked_at": (NOW - timedelta(minutes=5)).isoformat(),
        "ingestion_allowed": False,
        "cv_allowed": False,
    }
    item.update(changes)
    return item


def test_shipped_registry_is_placeholders_only_and_never_evidence() -> None:
    cameras = camera_registry("bangkok")
    assert cameras and all(c.placeholder for c in cameras)
    for camera in cameras:
        assert not frame_capable(camera)
        assert camera.viewer_url is None
        role, reasons = corroboration_role(camera, ROAD, NOW)
        assert role == CANNOT_CONFIRM and "placeholder" in reasons
    raw = json.loads((DATA / "flood_pilot_bangkok_cameras.json").read_text(encoding="utf-8"))
    assert "not a real camera" in raw["cameras"][0]["name"]["en"]


@pytest.mark.parametrize(
    "changes",
    [
        {"viewer_url": None},
        {"viewer_url": "http://example.test/viewer"},
        {"cv_allowed": True},
        {"cv_allowed": True, "ingestion_allowed": True},
        {"stream_url": "https://example.test/live.m3u8"},
        {"snapshot_url": "https://example.test/now.jpg"},
        {"access_mode": "rtsp"},
        {"status": "fine"},
        {"lat": 48.85, "lon": 2.35},
        {"provider": "PLACEHOLDER"},
        {"heading_deg": 400},
    ],
)
def test_registry_rules_refuse_unsafe_or_unclear_entries(changes) -> None:
    with pytest.raises(CameraRegistryError):
        parse_camera(_real(**changes))


def test_a_placeholder_can_have_no_links_and_no_ingestion() -> None:
    base = {"provider": "PLACEHOLDER", "placeholder": True, "viewer_url": None}
    with pytest.raises(CameraRegistryError):
        parse_camera(_real(**base, ingestion_allowed=True))
    with pytest.raises(CameraRegistryError):
        parse_camera(_real(**{**base, "viewer_url": "https://example.test/v"}))
    assert parse_camera(_real(**base)).placeholder


def test_repeated_camera_ids_are_refused() -> None:
    with pytest.raises(CameraRegistryError):
        parse_registry({"cameras": [_real(), _real()]})


def test_viewer_only_camera_never_reaches_frame_code() -> None:
    # Tweak scenario 5: even a mistaken ingestion flag cannot make a viewer a frame source.
    camera = parse_camera(_real(ingestion_allowed=True))
    assert not frame_capable(camera)
    snapshot = parse_camera(_real(access_mode="snapshot", snapshot_url="https://example.test/s.jpg",
                                  ingestion_allowed=True))
    assert frame_capable(snapshot)


def test_a_healthy_camera_facing_the_road_only_lets_an_officer_look() -> None:
    role, reasons = corroboration_role(parse_camera(_real()), ROAD, NOW)
    assert (role, reasons) == (OFFICER_CAN_LOOK, [])


def test_a_camera_facing_away_cannot_confirm() -> None:
    # Tweak scenario 4: close by, online, but pointed south, away from the road.
    role, reasons = corroboration_role(parse_camera(_real(heading_deg=180, fov_deg=60)), ROAD, NOW)
    assert role == CANNOT_CONFIRM and reasons == ["faces_away"]


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"status": "offline"}, "status_offline"),
        ({"status_checked_at": (NOW - timedelta(hours=2)).isoformat()}, "health_not_recent"),
        ({"status_checked_at": None}, "health_not_recent"),
        ({"heading_deg": None}, "view_direction_unknown"),
        ({"access_mode": "metadata_only", "viewer_url": None}, "no_viewer"),
    ],
)
def test_unhealthy_or_unclear_cameras_cannot_confirm(changes, reason) -> None:
    role, reasons = corroboration_role(parse_camera(_real(**changes)), ROAD, NOW)
    assert role == CANNOT_CONFIRM and reason in reasons


def test_nearby_cameras_are_ranked_and_bounded() -> None:
    cameras = parse_registry(
        {
            "cameras": [
                _real(camera_id="far", lat=13.8500),
                _real(camera_id="offline", status="offline", lat=13.8409),
                _real(camera_id="good"),
            ]
        }
    )
    found = nearby_cameras(cameras, ROAD, NOW, radius_m=400)
    assert [c["camera_id"] for c in found] == ["good", "offline"]
    assert found[0]["distance_m"] < 150
    assert "stream_url" not in found[0] and "snapshot_url" not in found[0]
