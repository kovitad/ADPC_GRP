"""The live flood feed for Global Risk: one JSON document, two record lists (ADR-0052).

``records`` has one row per open incident; ``districts`` has one row per pilot district, all of
them, even with no incident. Global Risk's ``generic_json`` adapter reads one list per manifest,
so each list is registered as its own feed. The feed is a pure function of stored data: built from
an explicit allow-list of fields, in a fixed order, so the same data always gives the same bytes.

Left out on purpose:

- report text, contributor names, photos and report IDs (never stored);
- officer reviews and anything officer-confirmed (internal, decision D2 open);
- camera URLs, IDs and pictures;
- DDPM evacuation centres (redistribution not cleared): facility counts are OpenStreetMap only;
- Longdo values: an incident keeps ``doh``, ``itic`` or ``longdo_user`` in ``source_families``,
  but depth, report count and evidence time come from Floodboard sources only.

Global Risk caches a feed for six hours and treats an empty list as a failure, so every record
carries ``valid_until``, and ``districts`` is never empty.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from core.flood_evidence.areas import COVERAGE_NAME, pilot_areas
from core.flood_evidence.config import PilotConfig
from core.flood_evidence.exposure import latest_exposure
from core.flood_evidence.incident_store import REPORT_WINDOW_HOURS, list_incidents
from core.flood_evidence.incidents import OFFICIAL
from core.flood_evidence.situation import current_roads, recent_reports

FEED_VERSION = "bangkok-flood-feed v1"
VALID_FOR = timedelta(minutes=30)  # three missed ten-minute roads fetches
LONGDO_SOURCES = frozenset({"itic", "longdo", "longdo_user", "doh"})
OSM_TYPES = ("school", "hospital", "clinic")
# Least concern first: Global Risk returns the newest tail, and all districts share one as_of,
# so the most concerning districts are the ones a short query returns.
CONCERN = {None: 0, "low": 1, "medium": 2, "high": 3, "conflicting": 4}
SOURCES = [
    {"name": "Floodboard (floodboard.org)", "use": "road flood ratings and public reports",
     "license": "CC BY 4.0"},
    {"name": "OpenStreetMap contributors", "use": "schools, hospitals and clinics",
     "license": "ODbL"},
]
LIMITS = [
    "Estimates from crowd and agency reports, grouped by rule: not a flood map and not verified "
    "on the ground.",
    "No water-level sensors. Zero incidents means no flooding was found in the reports, not proof "
    "that an area is dry.",
    "\"Facilities nearby\" means flooding was reported on a road close by, not that the building "
    "is flooded.",
    "Not a warning. For official warnings, follow TMD, DDPM and the BMA.",
]


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z") if value else None


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def _evidence_class(families: list[str]) -> str:
    official = set(families) & OFFICIAL
    if official and set(families) - OFFICIAL:
        return "crowd_and_official_mix"
    return "official_only" if official else "crowd_only"


def build_feed(
    session: Session, config: PilotConfig, now: datetime | None = None
) -> dict[str, Any]:
    """The feed document. Deterministic for the same stored data and ``now``."""

    now = now or datetime.now(UTC)
    listed = list_incidents(session, config, now)
    roads = current_roads(session, config, now)
    road_props = {f["properties"]["id"]: f["properties"] for f in roads["features"]}
    reports = {f["properties"]["id"]: f["properties"]
               for f in recent_reports(session, config, now, REPORT_WINDOW_HOURS)["features"]}
    areas = pilot_areas(config)
    area_names = {a["admin_code"]: a for a in areas}

    # OpenStreetMap facilities with flooding reported nearby, by incident.
    incident_of = {key: i["incident_id"] for i in listed["incidents"]
                   for key in i.get("road_keys") or []}
    nearby: dict[str, Counter[str]] = {}
    for asset in latest_exposure(session, config, now)["assets"]:
        if (asset.get("exposure_state") != "potentially_exposed"
                or asset["asset_type"] not in OSM_TYPES):
            continue
        keys = asset.get("road_keys") or []
        for incident_id in {incident_of[k] for k in keys if k in incident_of}:
            nearby.setdefault(incident_id, Counter())[asset["asset_type"]] += 1

    checked_at = _parse(roads.get("snapshot_retrieved_at"))
    valid_until = checked_at + VALID_FOR if checked_at else None
    records = []
    for incident in listed["incidents"]:
        segments = [road_props[k] for k in incident.get("road_keys") or [] if k in road_props]
        floodboard = [reports[k] for k in incident.get("report_keys") or []
                      if k in reports and reports[k].get("underlying_source") not in LONGDO_SOURCES]
        depths = [s["depth_cm"] for s in segments if s.get("depth_cm") is not None]
        depths += [r["depth_cm"] for r in floodboard if r.get("depth_cm") is not None]
        times = [_parse(r.get("observed_at")) for r in floodboard]
        times += [_parse(s.get("reported_at")) for s in segments]
        times = [t for t in times if t is not None]
        codes = sorted(incident.get("district_codes") or [])
        bbox = [round(v, 5) for v in incident.get("bbox") or []]
        center = incident.get("center") or ([(bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2]
                                            if len(bbox) == 4 else [None, None])
        families = sorted(incident.get("source_families") or [])
        records.append({
            "incident_id": incident["incident_id"],
            "status": incident["status"],
            "confidence": incident.get("confidence"),
            "confidence_reasons": sorted(r for r in incident.get("reasons") or []
                                         if not r.startswith("officer")),
            "source_families": families,
            "evidence_class": _evidence_class(families),
            "district_codes": codes,
            "district_names_en": [area_names[c]["name"] for c in codes if c in area_names],
            "district_names_th": [area_names[c].get("name_th") for c in codes if c in area_names],
            "road_names_en": sorted({s["name_en"] for s in segments if s.get("name_en")}),
            "road_names_th": sorted({s["name"] for s in segments if s.get("name")}),
            "lon": round(center[0], 5) if center[0] is not None else None,
            "lat": round(center[1], 5) if center[1] is not None else None,
            "bbox": bbox,
            "max_depth_cm": max(depths) if depths else None,
            "report_count": len(floodboard),
            "facilities_nearby": {t: nearby.get(incident["incident_id"], Counter())[t]
                                  for t in OSM_TYPES},
            "camera_check": None,  # Step 2 (ADR-0054), after Gate B
            "first_seen": _iso(_parse(incident.get("opened_at"))),
            "last_evidence_at": _iso(max(times) if times
                                     else _parse(incident.get("newest_evidence_at"))),
            "valid_until": _iso(valid_until),
        })
    records.sort(key=lambda r: (r["first_seen"] or "", r["incident_id"]))
    as_of = max((r["last_evidence_at"] for r in records if r["last_evidence_at"]), default=None)
    as_of = as_of or _iso(checked_at)

    districts = []
    for area in areas:
        mine = [r for r in records if area["admin_code"] in r["district_codes"]]
        active = [r for r in mine if r["status"] == "active"]
        worst = max((r["confidence"] for r in active), key=lambda c: CONCERN.get(c, 0),
                    default=None)
        districts.append({
            "district_code": area["admin_code"],
            "district_name_en": area["name"],
            "district_name_th": area.get("name_th"),
            "province": area.get("province"),
            "active_incidents": len(active),
            "receding_incidents": len(mine) - len(active),
            "worst_confidence": worst,
            "facilities_nearby": {t: sum(r["facilities_nearby"][t] for r in active)
                                  for t in OSM_TYPES},
            "as_of": as_of,
            "valid_until": _iso(valid_until),
        })
    districts.sort(key=lambda d: (CONCERN.get(d["worst_confidence"], 0), d["active_incidents"],
                                  d["district_code"]))
    return {
        "feed_version": FEED_VERSION,
        "pilot_id": config.pilot_id,
        "coverage": {"name": COVERAGE_NAME, "districts": len(areas)},
        "run_at": _iso(_parse(listed.get("last_processed_at"))),
        "checked_at": _iso(checked_at),
        "as_of": as_of,
        "valid_until": _iso(valid_until),
        "rule_version": listed.get("rule_version"),
        "sources": SOURCES,
        "limits": LIMITS,
        "records": records,
        "districts": districts,
    }


def serialise(feed: dict[str, Any]) -> tuple[bytes, str]:
    """Stable bytes (sorted keys, no spaces) and their ETag."""

    body = json.dumps(feed, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return body, '"' + hashlib.sha256(body).hexdigest()[:32] + '"'
