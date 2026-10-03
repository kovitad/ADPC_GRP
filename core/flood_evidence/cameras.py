"""Provider-neutral CCTV registry for flood pilots: CCTV P0 (ADR-0039).

P0 shows where cameras are, their health and access mode, and opens the provider's own viewer.
GRP fetches no frame and no stream. A camera is never evidence on its own:

- the nearest camera is a discovery hint, not proof that it can see the road (tweak scenario 4);
- a viewer-only, metadata-only, unavailable or placeholder camera can never reach frame or CV code
  (tweak scenario 5);
- an offline camera, or one whose health was not checked recently, confirms nothing, and an
  unavailable camera never means the road is dry.

At most, ``corroboration_role`` says an officer can look through the official viewer. The
officer's own judgement is recorded later (slice 5) as a human observation.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

from core.flood_evidence.config import DATA

ACCESS_MODES = frozenset(
    {"external_viewer", "embed", "snapshot", "hls", "mjpeg", "webrtc", "metadata_only",
     "unavailable"}
)
FRAME_MODES = frozenset({"snapshot", "hls", "mjpeg", "webrtc"})
VIEWER_MODES = frozenset({"external_viewer", "embed"})
LIVE_KINDS = frozenset({"hls", "mp4"})
STATUSES = frozenset({"online", "offline", "unknown"})
PLACEHOLDER = "PLACEHOLDER"
HEALTH_FRESH = timedelta(minutes=30)
REGION = (99.0, 12.5, 102.0, 15.5)

OFFICER_CAN_LOOK = "officer_can_look"
CANNOT_CONFIRM = "cannot_confirm"


class CameraRegistryError(ValueError):
    """The registry file breaks a rule. The whole file is refused (fail closed)."""


@dataclass(frozen=True)
class Camera:
    camera_id: str
    provider: str
    provider_camera_id: str
    name: dict[str, str]
    lat: float
    lon: float
    heading_deg: float | None
    fov_deg: float | None
    access_mode: str
    viewer_url: str | None
    stream_url: str | None
    snapshot_url: str | None
    status: str
    status_checked_at: datetime | None
    related_sensor_ids: tuple[str, ...]
    rights: str
    retention_policy: str
    ingestion_allowed: bool
    cv_allowed: bool
    placeholder: bool
    # A live view the provider publishes for viewers' browsers (ADR-0047): HLS or MP4. The
    # officer's browser plays it; GRP never fetches, relays, records or analyses it.
    live_kind: str | None = None
    live_url: str | None = None
    source_label: str = ""

    def public(self) -> dict[str, Any]:
        """What operators see. Ingestion endpoints never go to the browser; a published live
        view does, because only the officer's browser plays it."""

        return {
            "camera_id": self.camera_id,
            "provider": self.provider,
            "provider_camera_id": self.provider_camera_id,
            "name": self.name,
            "lat": self.lat,
            "lon": self.lon,
            "heading_deg": self.heading_deg,
            "fov_deg": self.fov_deg,
            "access_mode": self.access_mode,
            "viewer_url": self.viewer_url,
            "status": self.status,
            "status_checked_at": self.status_checked_at.isoformat()
            if self.status_checked_at else None,
            "related_sensor_ids": list(self.related_sensor_ids),
            "rights": self.rights,
            "placeholder": self.placeholder,
            "live": {"kind": self.live_kind, "url": self.live_url} if self.live_url else None,
            "source_label": self.source_label,
        }


def _https(url: Any, field: str) -> str | None:
    if url is None:
        return None
    if not isinstance(url, str) or not url.startswith("https://"):
        raise CameraRegistryError(f"{field} must be an https:// URL")
    return url


def _angle(value: Any, field: str, upper: float) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= upper:
        raise CameraRegistryError(f"{field} must be between 0 and {upper}")
    return float(value)


def parse_camera(item: dict[str, Any]) -> Camera:
    try:
        lat, lon = float(item["lat"]), float(item["lon"])
        access_mode = item["access_mode"]
        status = item["status"]
        name = item["name"]
        placeholder = bool(item.get("placeholder", False))
        ingestion_allowed = item["ingestion_allowed"] is True
        cv_allowed = item["cv_allowed"] is True
    except (KeyError, TypeError, ValueError) as error:
        raise CameraRegistryError("A camera is missing a required field") from error
    west, south, east, north = REGION
    if not (west <= lon <= east and south <= lat <= north):
        raise CameraRegistryError("A camera is outside the pilot region")
    if access_mode not in ACCESS_MODES:
        raise CameraRegistryError(f"Unknown access mode {access_mode!r}")
    if status not in STATUSES:
        raise CameraRegistryError(f"Unknown camera status {status!r}")
    if not isinstance(name, dict) or not name.get("en"):
        raise CameraRegistryError("A camera needs an English name")
    viewer = _https(item.get("viewer_url"), "viewer_url")
    stream = _https(item.get("stream_url"), "stream_url")
    snapshot = _https(item.get("snapshot_url"), "snapshot_url")
    if stream and access_mode not in {"hls", "mjpeg", "webrtc"}:
        raise CameraRegistryError("stream_url needs a stream access mode")
    if snapshot and access_mode != "snapshot":
        raise CameraRegistryError("snapshot_url needs the snapshot access mode")
    if access_mode == "embed" and not viewer:
        raise CameraRegistryError("An embed camera needs its viewer URL")
    if cv_allowed and not (ingestion_allowed and access_mode in FRAME_MODES):
        raise CameraRegistryError("CV is only allowed on an authorised frame source")
    if placeholder:
        if item.get("provider") != PLACEHOLDER or viewer or stream or snapshot:
            raise CameraRegistryError("A placeholder has no provider and no links")
        if ingestion_allowed or cv_allowed:
            raise CameraRegistryError("A placeholder can never be ingested")
    elif item.get("provider") == PLACEHOLDER:
        raise CameraRegistryError("Only placeholders use the PLACEHOLDER provider")
    elif access_mode == "external_viewer" and not viewer:
        raise CameraRegistryError("An external-viewer camera needs its viewer URL")
    live = item.get("live")
    live_kind = live_url = None
    if live:
        if not isinstance(live, dict) or live.get("kind") not in LIVE_KINDS:
            raise CameraRegistryError(f"A live view must be one of {sorted(LIVE_KINDS)}")
        if placeholder:
            raise CameraRegistryError("A placeholder has no live view")
        live_kind, live_url = live["kind"], _https(live.get("url"), "live.url")
        if not live_url:
            raise CameraRegistryError("A live view needs its URL")
    checked = item.get("status_checked_at")
    try:
        checked_at = datetime.fromisoformat(checked).astimezone(UTC) if checked else None
    except ValueError as error:
        raise CameraRegistryError("status_checked_at is not an ISO time") from error
    return Camera(
        camera_id=str(item["camera_id"]),
        provider=str(item["provider"]),
        provider_camera_id=str(item["provider_camera_id"]),
        name={k: str(v) for k, v in name.items()},
        lat=lat,
        lon=lon,
        heading_deg=_angle(item.get("heading_deg"), "heading_deg", 360),
        fov_deg=_angle(item.get("fov_deg"), "fov_deg", 360),
        access_mode=access_mode,
        viewer_url=viewer,
        stream_url=stream,
        snapshot_url=snapshot,
        status=status,
        status_checked_at=checked_at,
        related_sensor_ids=tuple(str(s) for s in item.get("related_sensor_ids") or ()),
        rights=str(item.get("rights") or ""),
        retention_policy=str(item.get("retention_policy") or ""),
        ingestion_allowed=ingestion_allowed,
        cv_allowed=cv_allowed,
        placeholder=placeholder,
        live_kind=live_kind,
        live_url=live_url,
        source_label=str(item.get("source_label") or item.get("provider") or ""),
    )


def parse_registry(raw: dict[str, Any]) -> tuple[Camera, ...]:
    """Every camera, after merging the file's shared ``defaults``; each is checked in full."""

    defaults = raw.get("defaults") or {}
    cameras = tuple(parse_camera({**defaults, **item}) for item in raw.get("cameras", []))
    ids = [c.camera_id for c in cameras]
    if len(ids) != len(set(ids)):
        raise CameraRegistryError("Camera IDs repeat")
    return cameras


@lru_cache
def camera_registry(pilot_id: str) -> tuple[Camera, ...]:
    """Every source's file (``flood_pilot_<id>_cameras*.json``), combined. IDs never repeat."""

    cameras: list[Camera] = []
    for path in sorted(DATA.glob(f"flood_pilot_{pilot_id}_cameras*.json")):
        cameras.extend(parse_registry(json.loads(path.read_text(encoding="utf-8"))))
    ids = [c.camera_id for c in cameras]
    if len(ids) != len(set(ids)):
        raise CameraRegistryError("Camera IDs repeat across sources")
    return tuple(cameras)


def frame_capable(camera: Camera) -> bool:
    """Only an authorised, non-placeholder frame source may ever be sampled. Not used in P0."""

    return camera.ingestion_allowed and camera.access_mode in FRAME_MODES and not camera.placeholder


def _metres(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    rad = math.pi / 180
    x = (lon2 - lon1) * rad * math.cos((lat1 + lat2) / 2 * rad)
    y = (lat2 - lat1) * rad
    return math.hypot(x, y) * 6_371_000


def _bearing(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    rad = math.pi / 180
    x = (lon2 - lon1) * math.cos((lat1 + lat2) / 2 * rad)
    y = lat2 - lat1
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def _points(geometry: dict[str, Any]) -> list[tuple[float, float]]:
    kind, coords = geometry["type"], geometry["coordinates"]
    if kind == "Point":
        return [(coords[0], coords[1])]
    lines = coords if kind == "MultiLineString" else [coords]
    return [(p[0], p[1]) for line in lines for p in line]


def corroboration_role(
    camera: Camera, geometry: dict[str, Any], as_of: datetime
) -> tuple[str, list[str]]:
    """Whether an officer can usefully look through this camera, with every reason it cannot.

    P0 never returns a confirmation: the best case is ``officer_can_look``.
    """

    reasons: list[str] = []
    if camera.placeholder:
        reasons.append("placeholder")
    if camera.status != "online":
        reasons.append(f"status_{camera.status}")
    if camera.status_checked_at is None or as_of - camera.status_checked_at > HEALTH_FRESH:
        reasons.append("health_not_recent")
    if camera.access_mode not in VIEWER_MODES or not camera.viewer_url:
        reasons.append("no_viewer")
    if camera.heading_deg is None or camera.fov_deg is None:
        reasons.append("view_direction_unknown")
    else:
        half = camera.fov_deg / 2
        sees = any(
            abs((_bearing(camera.lon, camera.lat, lon, lat) - camera.heading_deg + 180) % 360 - 180)
            <= half
            for lon, lat in _points(geometry)
        )
        if not sees:
            reasons.append("faces_away")
    return (CANNOT_CONFIRM if reasons else OFFICER_CAN_LOOK), reasons


def nearby_cameras(
    cameras: tuple[Camera, ...],
    geometry: dict[str, Any],
    as_of: datetime,
    radius_m: float,
) -> list[dict[str, Any]]:
    """Cameras within ``radius_m`` of any point of the geometry, nearest and healthiest first."""

    points = _points(geometry)
    found = []
    for camera in cameras:
        distance = min(_metres(camera.lon, camera.lat, lon, lat) for lon, lat in points)
        if distance > radius_m:
            continue
        role, reasons = corroboration_role(camera, geometry, as_of)
        found.append(
            {
                **camera.public(),
                "distance_m": round(distance),
                "role": role,
                "reasons": reasons,
            }
        )
    found.sort(key=lambda c: (c["role"] != OFFICER_CAN_LOOK, c["status"] != "online",
                              c["distance_m"]))
    return found
