"""Live reported flooding for one Planner area (ADR-0056, step 2 and W7b).

Read-only. Incidents carry their district codes from the worker (step 1), and facility exposure
is stored by the worker, so roads and facilities need no spatial work here. Cameras near the
district's incident roads are matched in the request, as the pilot's incident page already does
(at most about 20 incidents times 1,413 cameras).

A sub-district shows its parent district and says so. Officer checks and officer-confirmed access
are not included (decision D2 is open). Nothing here touches an assessment.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from core.flood_evidence.areas import COVERAGE_NAME, all_areas, in_pilot
from core.flood_evidence.camera_relay import PROVIDER as RELAY_PROVIDER
from core.flood_evidence.camera_relay import RELAYED_PROVIDERS, frame_url
from core.flood_evidence.cameras import camera_registry, nearby_cameras
from core.flood_evidence.config import pilot_config
from core.flood_evidence.exposure import latest_exposure
from core.flood_evidence.incident_store import list_incidents
from core.flood_evidence.situation import current_roads

PILOT_ID = "bangkok"
LAYER_TITLE = {"en": "Reported flooding on roads (live, not a flood map)",
               "th": "ถนนที่มีรายงานน้ำท่วม (ข้อมูลสด ไม่ใช่แผนที่น้ำท่วม)"}
CREDIT = "Floodboard (floodboard.org), CC BY 4.0"
NOTE = ("Roads with flooding reported by BMA, Traffy Fondue and the public, grouped by GRP. "
        "Estimates from reports, not a flood extent and not verified on the ground. "
        "Not part of any assessment.")
INCIDENT_FIELDS = ("incident_id", "status", "confidence", "reasons", "source_families",
                   "max_depth_cm", "newest_evidence_at", "freshness", "center",
                   "district_codes", "closed_roads")
CAMERA_RADIUS_M = 400
MAX_CAMERAS = 40
FACILITY_CREDITS = {"evacuation_centre": "DDPM (GRP data library)"}


def _unavailable(reason: str, note: str) -> dict[str, Any]:
    return {"available": False, "reason": reason, "note": note, "title": LAYER_TITLE}


def live_layer(session: Session, hub_code: str, admin_code: str, admin_level: str,
               now: datetime | None = None, relay: bool = False) -> dict[str, Any]:
    """The incidents and their roads in the area's district, from the latest stored run."""

    config = pilot_config(PILOT_ID)
    code = str(admin_code or "")
    if config is None or not in_pilot(config, code):
        return _unavailable("outside_coverage",
                            f"Live reported flooding covers {COVERAGE_NAME['en']} only.")
    if hub_code.strip().lower() not in config.hubs:
        return _unavailable("hub_not_enabled",
                            "Live reported flooding is not enabled for this Hub.")
    district = code[:4]
    names = {a["admin_code"]: (a["name"], a.get("name_th")) for a in all_areas(config.base_id)}
    if district not in names or district not in (config.demo_corridor.get("areas") or []):
        return _unavailable("outside_coverage",
                            "Live reported flooding does not cover this district.")
    now = now or datetime.now(UTC)
    listed = list_incidents(session, config, now)
    placed = [i for i in listed["incidents"] if i.get("district_codes") is not None]
    here = [i for i in placed if district in i["district_codes"]]
    incidents = [{**{k: i.get(k) for k in INCIDENT_FIELDS},
                  "road_count": len(i.get("road_keys") or []),
                  "report_count": len(i.get("report_keys") or [])} for i in here]
    by_road = {key: i for i in here for key in i.get("road_keys") or []}
    roads = current_roads(session, config, now, include_all=True)
    features = []
    for feature in roads["features"]:
        p = feature["properties"]
        incident = by_road.get(p["id"])
        if incident is None:
            continue
        features.append({"type": "Feature", "geometry": feature["geometry"], "properties": {
            "id": p["id"], "name": p.get("name"), "name_en": p.get("name_en"),
            "depth_cm": p.get("depth_cm"), "closed_all": p.get("closed_all"),
            "freshness": p.get("freshness"), "reported_at": p.get("reported_at"),
            "incident_id": incident["incident_id"], "confidence": incident["confidence"],
            "status": incident["status"],
        }})
    facilities = _facilities(session, config, now, district, here)
    cameras = _cameras(config, now, here, features, relay)
    gaps = []
    unplaced = len(listed["incidents"]) - len(placed)
    if unplaced:
        gaps.append(f"{unplaced} other open incident(s) were last updated before districts were "
                    "recorded, so they cannot be placed; they get one if flooding is reported "
                    "there again, or close within two hours.")
    name_en, name_th = names[district]
    return {
        "available": True, "title": LAYER_TITLE, "note": NOTE, "credit": CREDIT,
        "district_code": district, "district_name": name_en, "district_name_th": name_th,
        "rolled_up_from": code if admin_level == "subdistrict" else None,
        "snapshot_retrieved_at": roads.get("snapshot_retrieved_at"),
        "last_processed_at": listed.get("last_processed_at"),
        "rule_version": listed.get("rule_version"),
        "incidents": incidents,
        "roads": {"type": "FeatureCollection", "features": features},
        "facilities": facilities,
        "cameras": cameras,
        "gaps": gaps,
    }


def _facilities(session: Session, config: Any, now: datetime, district: str,
                incidents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Facilities in the district with flooding reported nearby, from the stored exposure."""

    incident_of = {key: i["incident_id"] for i in incidents for key in i.get("road_keys") or []}
    out = []
    for asset in latest_exposure(session, config, now)["assets"]:
        if asset.get("district_code") != district:
            continue
        if asset.get("exposure_state") != "potentially_exposed":
            continue
        reasons = [r for r in asset.get("reasons") or [] if not r.startswith("officer")]
        frontage = next((r for r in reasons if r.startswith("frontage_road")), None)
        access = asset.get("access_state")
        if access == "access_disrupted_confirmed":
            # Only an officer sets this (D2 open): show what GRP computed instead.
            access = "access_under_review" if frontage else "access_unknown"
        out.append({
            "asset_id": asset["asset_id"], "asset_type": asset["asset_type"],
            "name": asset.get("name") or asset.get("name_en") or "",
            "name_en": asset.get("name_en") or "",
            "lat": asset["lat"], "lon": asset["lon"],
            "nearest_distance_m": asset.get("nearest_distance_m"),
            "access_state": access, "frontage": frontage,
            "incident_ids": sorted({incident_of[k] for k in asset.get("road_keys") or []
                                    if k in incident_of}),
            "source": FACILITY_CREDITS.get(asset["asset_type"], asset.get("source") or ""),
        })
    out.sort(key=lambda f: (f["asset_type"] != "evacuation_centre",
                            f["nearest_distance_m"] if f["nearest_distance_m"] is not None
                            else 10**6))
    return out


def _cameras(config: Any, now: datetime, incidents: list[dict[str, Any]],
             roads: list[dict[str, Any]], relay: bool) -> list[dict[str, Any]]:
    """Cameras within CAMERA_RADIUS_M of the district's incident roads, pictures first."""

    lines_of: dict[str, list] = {}
    for feature in roads:
        geometry = feature["geometry"]
        lines = (geometry["coordinates"] if geometry["type"] == "MultiLineString"
                 else [geometry["coordinates"]])
        lines_of.setdefault(feature["properties"]["incident_id"], []).extend(lines)
    registry = camera_registry(config.base_id)
    found: dict[str, dict[str, Any]] = {}
    for incident in incidents:
        lines = lines_of.get(incident["incident_id"])
        if not lines:
            continue
        footprint = {"type": "MultiLineString", "coordinates": lines}
        for camera in nearby_cameras(registry, footprint, now, CAMERA_RADIUS_M):
            if camera.get("placeholder"):
                continue
            item = found.get(camera["camera_id"])
            if item is None:
                can_picture = relay and camera["provider"] in RELAYED_PROVIDERS and (
                    camera["provider"] != RELAY_PROVIDER
                    or str(camera.get("provider_camera_id") or "").isdigit())
                item = found[camera["camera_id"]] = {
                    "camera_id": camera["camera_id"], "name": camera.get("name"),
                    "provider": camera["provider"],
                    "source": camera.get("source_label") or camera["provider"],
                    "lat": camera["lat"], "lon": camera["lon"], "status": camera.get("status"),
                    "viewer_url": camera.get("viewer_url"),
                    "picture_url": frame_url(config.base_id, camera["camera_id"])
                    if can_picture else None,
                    "distance_m": camera["distance_m"], "incident_ids": [],
                }
            item["distance_m"] = min(item["distance_m"], camera["distance_m"])
            if incident["incident_id"] not in item["incident_ids"]:
                item["incident_ids"].append(incident["incident_id"])
    ordered = sorted(found.values(), key=lambda c: (c["picture_url"] is None, c["distance_m"]))
    return ordered[:MAX_CAMERAS]
