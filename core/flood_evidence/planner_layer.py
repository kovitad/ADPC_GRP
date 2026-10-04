"""Live reported flooding for one Planner area (ADR-0056, step 2).

Read-only, and built from stored data only: incidents already carry their district codes, which
the worker computes (step 1), so this does no spatial work. A sub-district shows its parent
district's incidents and says so. Officer checks are not included (decision D2 is open), and
nothing here touches an assessment.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from core.flood_evidence.config import pilot_config
from core.flood_evidence.incident_store import list_incidents
from core.flood_evidence.situation import current_roads
from core.river_watch import bangkok_outlines

PILOT_ID = "bangkok"
LAYER_TITLE = {"en": "Reported flooding on roads (live, not a flood map)",
               "th": "ถนนที่มีรายงานน้ำท่วม (ข้อมูลสด ไม่ใช่แผนที่น้ำท่วม)"}
CREDIT = "Floodboard (floodboard.org), CC BY 4.0"
NOTE = ("Roads with flooding reported by BMA, Traffy Fondue and the public, grouped by GRP. "
        "Estimates from reports, not a flood extent and not verified on the ground. "
        "Not part of any assessment.")
INCIDENT_FIELDS = ("incident_id", "status", "confidence", "reasons", "source_families",
                   "max_depth_cm", "newest_evidence_at", "freshness", "center",
                   "district_codes")


def _unavailable(reason: str, note: str) -> dict[str, Any]:
    return {"available": False, "reason": reason, "note": note, "title": LAYER_TITLE}


def live_layer(session: Session, hub_code: str, admin_code: str, admin_level: str,
               now: datetime | None = None) -> dict[str, Any]:
    """The incidents and their roads in the area's district, from the latest stored run."""

    config = pilot_config(PILOT_ID)
    code = str(admin_code or "")
    if config is None or not code.startswith("10") or len(code) < 4:
        return _unavailable("outside_coverage", "Live reported flooding covers Bangkok only.")
    if hub_code.strip().lower() not in config.hubs:
        return _unavailable("hub_not_enabled",
                            "Live reported flooding is not enabled for this Hub.")
    district = code[:4]
    names = {a["admin_code"]: (a["name"], a.get("name_th")) for a in bangkok_outlines()}
    if district not in names or district not in (config.demo_corridor.get("areas") or []):
        return _unavailable("outside_coverage",
                            "Live reported flooding does not cover this district.")
    now = now or datetime.now(UTC)
    listed = list_incidents(session, config, now)
    placed = [i for i in listed["incidents"] if i.get("district_codes") is not None]
    here = [i for i in placed if district in i["district_codes"]]
    incidents = [{**{k: i.get(k) for k in INCIDENT_FIELDS},
                  "road_count": len(i.get("road_keys") or [])} for i in here]
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
    gaps = []
    unplaced = len(listed["incidents"]) - len(placed)
    if unplaced:
        gaps.append(f"{unplaced} open incident(s) have no district yet; they get one at the next "
                    "snapshot.")
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
        "gaps": gaps,
    }
