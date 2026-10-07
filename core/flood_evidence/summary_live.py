"""The live section of the Planner's district summary (ADR-0056, summary amendment).

It uses the same facts as the Planner's live answers (``planner_answer.live_facts``), so the
document, the map and the chat agree. It adds pictures from the BMA traffic cameras nearest the
top incidents. The Product Owner reported on 4 October 2026 that BMA confirmed these pictures are
public data that anyone may use. Each picture is credited with its camera and time.

Pictures go into the document only; GRP keeps no copy. Nothing here touches an assessment.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from core.flood_evidence.camera_relay import PROVIDER as BMATRAFFIC
from core.flood_evidence.cameras import camera_registry, nearby_cameras
from core.flood_evidence.config import pilot_config
from core.flood_evidence.incident_store import list_incidents
from core.flood_evidence.planner_answer import BANGKOK, NO_WARNINGS, live_facts
from core.flood_evidence.situation import current_roads
from core.flood_evidence.snapshot_relay import PROVIDERS as SNAPSHOT_PROVIDERS

CAMERA_RADIUS_M = 400
MAX_PICTURES = 4
STALE_MINUTES = 120
CREDIT = "Floodboard (floodboard.org), CC BY 4.0; facilities © OpenStreetMap contributors and DDPM"
CAMERA_CREDIT = "BMA traffic camera (bmatraffic.com)"

# Fetches one allow-listed camera picture: camera record -> (JPEG bytes, retrieved_at).
# Tests replace it; production dispatches only to the two bounded relay implementations.
FrameGetter = Callable[[dict[str, Any]], tuple[bytes, datetime]]


def _can_fetch(camera: dict[str, Any]) -> bool:
    return (
        camera.get("provider") == BMATRAFFIC
        and str(camera.get("provider_camera_id") or "").isdigit()
    ) or (
        camera.get("provider") in SNAPSHOT_PROVIDERS and bool(camera.get("_snapshot_url"))
    )


def _relay_frame(camera: dict[str, Any]) -> tuple[bytes, datetime]:
    if camera.get("provider") in SNAPSHOT_PROVIDERS:
        from core.flood_evidence.snapshot_relay import shared_snapshot_relay

        frame = shared_snapshot_relay().frame(camera["camera_id"], camera["_snapshot_url"])
    else:
        from core.flood_evidence.camera_relay import shared_relay

        frame = shared_relay().frame(str(camera["provider_camera_id"]))
    return frame.body, frame.retrieved_at


def _clock(value: datetime | None) -> str | None:
    return value.astimezone(BANGKOK).strftime("%d %b %Y %H:%M") if value else None


def _camera_name(camera: dict[str, Any]) -> Any:
    """The registry name, or the camera's number when the name is blank or only punctuation."""

    name = camera.get("name")
    texts = name.values() if isinstance(name, dict) else [name]
    if any(re.search(r"\w", str(text or "")) for text in texts):
        return name
    return f"Camera {camera.get('provider_camera_id') or camera['camera_id']}"


def _cameras(session: Session, live: dict[str, Any], now: datetime,
             get_frame: FrameGetter, include_pictures: bool) -> list[dict[str, Any]]:
    """The camera nearest each listed incident, with a picture for up to MAX_PICTURES of them."""

    config = pilot_config("bangkok")
    incident_ids = [live["labels"].get(f["id"]) for f in live["facts"] if f["kind"] == "incident"]
    by_id = {i["incident_id"]: i for i in list_incidents(session, config, now)["incidents"]}
    roads = {f["properties"]["id"]: f["geometry"]
             for f in current_roads(session, config, now, include_all=True)["features"]}
    registry = camera_registry(config.base_id)
    snapshot_urls = {camera.camera_id: camera.snapshot_url for camera in registry}
    out, used, pictures = [], set(), 0
    for label, incident_id in zip(
        [f["id"] for f in live["facts"] if f["kind"] == "incident"], incident_ids, strict=True
    ):
        incident = by_id.get(incident_id)
        if incident is None:
            continue
        lines = [line for key in incident.get("road_keys") or [] if key in roads
                 for line in (roads[key]["coordinates"] if roads[key]["type"] == "MultiLineString"
                              else [roads[key]["coordinates"]])]
        if not lines:
            continue
        footprint = {"type": "MultiLineString", "coordinates": lines}
        near = [
            {**camera, "_snapshot_url": snapshot_urls.get(
                camera["camera_id"], camera.get("_snapshot_url")
            )}
            for camera in nearby_cameras(registry, footprint, now, CAMERA_RADIUS_M)
            if not camera.get("placeholder") and camera["camera_id"] not in used
        ]
        if not near:
            continue
        # Prefer a camera whose picture GRP can fetch; otherwise list the nearest one.
        camera = next((c for c in near if _can_fetch(c)), near[0])
        used.add(camera["camera_id"])
        item = {"incident": label, "name": _camera_name(camera),
                "distance_m": camera["distance_m"],
                "source": camera.get("source_label") or camera["provider"],
                "viewer_url": camera.get("viewer_url"), "picture": None, "picture_at": None,
                "picture_note": None}
        if include_pictures and _can_fetch(camera) and pictures < MAX_PICTURES:
            try:
                body, at = get_frame(camera)
                credit = (CAMERA_CREDIT if camera["provider"] == BMATRAFFIC
                          else camera.get("source_label") or camera["provider"])
                item.update(picture=body, picture_at=_clock(at), credit=credit)
                pictures += 1
            except Exception:  # a camera that does not answer is listed without a picture
                item["picture_note"] = "camera did not answer"
        out.append(item)
    return out


def live_section(session: Session, hub_code: str, admin_code: str, admin_level: str,
                 now: datetime | None = None,
                 get_frame: FrameGetter | None = None,
                 include_camera_pictures: bool = True) -> dict[str, Any]:
    """Everything the summary's live section shows, or why it cannot be shown."""

    now = now or datetime.now(UTC)
    live = live_facts(session, hub_code, admin_code, admin_level, now)
    if not live["available"]:
        return {"available": False, "reason": live["reason"], "no_warnings": NO_WARNINGS}
    facts = live["facts"]
    by_id = {f["id"]: f for f in facts}
    situation, changes = by_id["S"], by_id["C"]
    limits = by_id.get("L") or {}
    snapshot = current_roads(session, pilot_config("bangkok"), now)["snapshot_retrieved_at"]
    snapshot_at = datetime.fromisoformat(snapshot) if snapshot else None
    age = round((now - snapshot_at).total_seconds() / 60) if snapshot_at else None
    return {
        "available": True,
        "district_name": live["district_name"],
        "district_name_th": live["district_name_th"],
        "rolled_up_from": live["rolled_up_from"],
        "as_of": _clock(snapshot_at) or _clock(now),
        "age_minutes": age,
        "stale": age is not None and age > STALE_MINUTES,
        "situation": situation,
        "changes": changes,
        "incidents": [f for f in facts if f["kind"] == "incident"],
        "incidents_not_listed": limits.get("incidents_not_listed", 0),
        "facilities": [f for f in facts if f["kind"] == "facility"],
        "rain": by_id.get("W"),
        "cameras": _cameras(
            session, live, now, get_frame or _relay_frame, include_camera_pictures
        ),
        "credit": CREDIT,
        "no_warnings": NO_WARNINGS,
    }
