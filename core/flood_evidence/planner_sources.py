"""The Planner's "Live layer": every live source for the whole pilot area (ADR-0058).

One function per map switch, each returning only what a planner needs. The Planner gets its own
trimmed copy rather than the pilot's routes, because those carry officer checks (decision D2 is
open). Everything is read from stored data; camera distances are not computed here.

Sources and their switch keys:

- ``roads``: road segments with flooding reported (Floodboard), each linked to its incident;
- ``reports``: recent reports, grouped by kind of source (``rep_traffy``, ``rep_crowd``,
  ``rep_bma``, ``rep_longdo``, ``rep_other``);
- ``facilities``: OSM schools, hospitals and clinics, and DDPM evacuation centres, with their
  computed exposure (never an officer-confirmed state);
- ``cameras``: the camera registry, grouped by provider, with a picture address only for
  relayed cameras when the relay is on;
- ``outlines``: the pilot's district outlines.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from core.flood_evidence.areas import COVERAGE_NAME, pilot_areas
from core.flood_evidence.camera_relay import PROVIDER as BMATRAFFIC
from core.flood_evidence.camera_relay import RELAYED_PROVIDERS, frame_url
from core.flood_evidence.cameras import camera_registry
from core.flood_evidence.config import PilotConfig, pilot_config
from core.flood_evidence.exposure import latest_exposure
from core.flood_evidence.incident_store import REPORT_WINDOW_HOURS, list_incidents
from core.flood_evidence.situation import current_roads, recent_reports

PILOT_ID = "bangkok"
SOURCES = ("roads", "reports", "facilities", "cameras", "outlines")
REPORT_GROUPS = {"traffy": ("traffy",), "crowd": ("crowd",), "bma": ("bma_sensor", "bma_dds"),
                 "longdo": ("itic", "longdo", "longdo_user", "doh")}
CAMERA_GROUPS = {"BMA_TRAFFIC": "cam_traffic", "BMA_DDS": "cam_bma", "ITIC_LONGDO": "cam_longdo",
                 "PAKKRET_CCTV": "cam_pakkret"}
INCIDENT_FIELDS = ("incident_id", "status", "confidence", "reasons", "source_families",
                   "max_depth_cm", "newest_evidence_at", "freshness", "center",
                   "district_codes", "closed_roads")
CREDITS = {
    "roads": "Floodboard (floodboard.org), CC BY 4.0",
    "reports": "Floodboard reports (BMA, Traffy Fondue, the public), CC BY 4.0",
    "facilities": "© OpenStreetMap contributors (ODbL); DDPM evacuation centres (GRP data library)",
    "cameras": "BMA Traffic, BMA flood cameras, iTIC/Longdo, Pak Kret municipality",
}


def config_for(hub_code: str) -> PilotConfig | None:
    config = pilot_config(PILOT_ID)
    if config is None or hub_code.strip().lower() not in config.hubs:
        return None
    return config


def report_group(source: str | None) -> str:
    return "rep_" + next((g for g, names in REPORT_GROUPS.items() if source in names), "other")


def camera_group(provider: str) -> str:
    return CAMERA_GROUPS.get(provider, "cam_other")


def _incidents(session: Session, config: PilotConfig, now: datetime) -> list[dict[str, Any]]:
    return list_incidents(session, config, now)["incidents"]


def roads(session: Session, config: PilotConfig, now: datetime) -> dict[str, Any]:
    incidents = _incidents(session, config, now)
    by_road = {key: i for i in incidents for key in i.get("road_keys") or []}
    data = current_roads(session, config, now)
    features = []
    for feature in data["features"]:
        p = feature["properties"]
        incident = by_road.get(p["id"])
        features.append({"type": "Feature", "geometry": feature["geometry"], "properties": {
            "id": p["id"], "name": p.get("name"), "name_en": p.get("name_en"),
            "depth_cm": p.get("depth_cm"), "closed_all": p.get("closed_all"),
            "cleared": p.get("cleared"), "freshness": p.get("freshness"),
            "reported_at": p.get("reported_at"),
            "incident_id": incident["incident_id"] if incident else None,
            "confidence": incident["confidence"] if incident else None,
            "status": incident["status"] if incident else None,
        }})
    return {
        "roads": {"type": "FeatureCollection", "features": features},
        "incidents": [{**{k: i.get(k) for k in INCIDENT_FIELDS},
                       "road_count": len(i.get("road_keys") or []),
                       "report_count": len(i.get("report_keys") or [])} for i in incidents],
        "snapshot_retrieved_at": data.get("snapshot_retrieved_at"),
    }


def reports(session: Session, config: PilotConfig, now: datetime) -> dict[str, Any]:
    data = recent_reports(session, config, now, REPORT_WINDOW_HOURS)
    features = []
    for feature in data["features"]:
        p = feature["properties"]
        features.append({"type": "Feature", "geometry": feature["geometry"], "properties": {
            "group": report_group(p.get("underlying_source")),
            "underlying_source": p.get("underlying_source"), "depth_cm": p.get("depth_cm"),
            "cleared": p.get("cleared"), "closed_all": p.get("closed_all"),
            "observed_at": p.get("observed_at"), "freshness": p.get("freshness"),
        }})
    return {"reports": {"type": "FeatureCollection", "features": features},
            "window_hours": REPORT_WINDOW_HOURS}


def facilities(session: Session, config: PilotConfig, now: datetime) -> dict[str, Any]:
    incidents = _incidents(session, config, now)
    incident_of = {key: i["incident_id"] for i in incidents for key in i.get("road_keys") or []}
    out = []
    for asset in latest_exposure(session, config, now)["assets"]:
        reasons = [r for r in asset.get("reasons") or [] if not r.startswith("officer")]
        frontage = next((r for r in reasons if r.startswith("frontage_road")), None)
        access = asset.get("access_state")
        if access == "access_disrupted_confirmed":  # set only by an officer (D2 open)
            access = "access_under_review" if frontage else "access_unknown"
        out.append({
            "asset_id": asset["asset_id"], "asset_type": asset["asset_type"],
            "name": asset.get("name") or asset.get("name_en") or "",
            "lat": asset["lat"], "lon": asset["lon"], "district_code": asset.get("district_code"),
            "exposure_state": asset.get("exposure_state"),
            "nearest_distance_m": asset.get("nearest_distance_m"),
            "access_state": access, "frontage": frontage,
            "incident_ids": sorted({incident_of[k] for k in asset.get("road_keys") or []
                                    if k in incident_of}),
            "source": "DDPM (GRP data library)" if asset["asset_type"] == "evacuation_centre"
            else asset.get("source") or "OpenStreetMap",
        })
    return {"facilities": out}


def cameras(config: PilotConfig, relay: bool) -> dict[str, Any]:
    out = []
    for camera in camera_registry(config.base_id):
        if camera.placeholder:
            continue
        can_picture = relay and camera.provider in RELAYED_PROVIDERS and (
            camera.provider != BMATRAFFIC or camera.provider_camera_id.isdigit())
        out.append({
            "camera_id": camera.camera_id, "group": camera_group(camera.provider),
            "provider": camera.provider, "name": camera.name,
            "source": camera.source_label or camera.provider,
            "lat": camera.lat, "lon": camera.lon, "status": camera.status,
            "viewer_url": camera.viewer_url,
            "picture_url": frame_url(config.base_id, camera.camera_id) if can_picture else None,
        })
    return {"cameras": out}


def outlines(config: PilotConfig) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": a["outline"],
         "properties": {"admin_code": a["admin_code"], "name": a["name"],
                        "name_th": a.get("name_th"), "province": a.get("province")}}
        for a in pilot_areas(config)]}


def source(session: Session, hub_code: str, name: str, relay: bool,
           now: datetime | None = None) -> dict[str, Any]:
    """One switch's data, or ``available: false`` for a Hub the pilot does not include."""

    config = config_for(hub_code)
    if config is None:
        return {"available": False, "reason": "hub_not_enabled"}
    now = now or datetime.now(UTC)
    body = {
        "roads": lambda: roads(session, config, now),
        "reports": lambda: reports(session, config, now),
        "facilities": lambda: facilities(session, config, now),
        "cameras": lambda: cameras(config, relay),
        "outlines": lambda: {"outlines": outlines(config)},
    }[name]()
    return {"available": True, "source": name, "credit": CREDITS.get(name), **body}


def summary(session: Session, hub_code: str, relay: bool,
            now: datetime | None = None) -> dict[str, Any]:
    """The count for every switch, so the panel can show them before anything is drawn."""

    config = config_for(hub_code)
    if config is None:
        return {"available": False, "reason": "hub_not_enabled"}
    now = now or datetime.now(UTC)
    road_data = current_roads(session, config, now)
    counts: Counter[str] = Counter()
    counts["roads"] = len(road_data["features"])
    for feature in recent_reports(session, config, now, REPORT_WINDOW_HOURS)["features"]:
        counts[report_group(feature["properties"].get("underlying_source"))] += 1
    for asset in latest_exposure(session, config, now)["assets"]:
        counts["fac_ddpm" if asset["asset_type"] == "evacuation_centre" else "fac_osm"] += 1
    for camera in camera_registry(config.base_id):
        if not camera.placeholder:
            counts[camera_group(camera.provider)] += 1
    counts["outline"] = len(pilot_areas(config))
    return {"available": True, "coverage": COVERAGE_NAME,
            "snapshot_retrieved_at": road_data.get("snapshot_retrieved_at"),
            "counts": dict(counts), "relay": relay}
