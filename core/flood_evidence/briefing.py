"""Deterministic answers for the flood pilot: what changed, and the facts an answer may use.

Slice 7a (ADR-0043). These are the read-only "tools" named in the integration tweak
(``get_current_incidents``, ``get_incident_evidence``, ``get_exposed_assets``,
``get_situation_changes``). Every number here is computed; an AI may later only word them.

History has limits, and the answers say so:

- incidents are tracked from the pilot's first incident run; events of that first run are the
  baseline, not "new", and a window starting earlier says when tracking began;
- past road counts cannot be rebuilt (a road row only remembers its newest snapshot), so changes
  come from incident events, incident-run counts and the per-snapshot facility exposure rows.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.flood_evidence.areas import all_areas
from core.flood_evidence.config import PilotConfig
from core.flood_evidence.exposure import latest_exposure
from core.flood_evidence.geo import inside_outline
from core.flood_evidence.incident_store import incident_detail, list_incidents
from core.flood_evidence.ingest import utc
from core.flood_evidence.models import (
    FloodAssetExposure,
    FloodIncident,
    FloodIncidentEvent,
    FloodIncidentRun,
    FloodSourceFetch,
)
from core.flood_evidence.situation import ROADS_ADAPTER, sources_status
from core.flood_evidence.weather import latest_weather

MAX_INCIDENTS = 15
BANGKOK = timezone(timedelta(hours=7), "Asia/Bangkok")
NAME_MAX = 60


# --- Areas ----------------------------------------------------------------------------------


def area_outlines(config: PilotConfig, area: str) -> list[dict[str, Any]] | None:
    """Outlines for ``all`` (None = no filter), ``corridor`` (the demo area) or a district code."""

    if area == "all" or config.base_id != "bangkok":
        return None
    codes = set(config.demo_corridor.get("areas") or []) if area == "corridor" else {area}
    outlines = [a["outline"] for a in all_areas(config.base_id) if a["admin_code"] in codes]
    if not outlines:
        raise LookupError(area)
    return outlines


def area_codes(config: PilotConfig, area: str) -> set[str] | None:
    if area == "all":
        return None
    if area == "corridor":
        return set(config.demo_corridor.get("areas") or [])
    return {area}


def _in(point: list[float], outlines: list[dict[str, Any]] | None) -> bool:
    return outlines is None or any(inside_outline(point[0], point[1], o) for o in outlines)


# --- Tools ----------------------------------------------------------------------------------


def get_current_incidents(
    session: Session, config: PilotConfig, area: str, now: datetime
) -> list[dict[str, Any]]:
    """Open incidents in the area, in check-first order."""

    outlines = area_outlines(config, area)
    return [i for i in list_incidents(session, config, now)["incidents"]
            if _in(i["center"], outlines)]


def get_incident_evidence(
    session: Session, config: PilotConfig, incident_id: UUID, now: datetime
) -> dict[str, Any] | None:
    return incident_detail(session, config, incident_id, now)


def get_exposed_assets(
    session: Session, config: PilotConfig, area: str, now: datetime
) -> list[dict[str, Any]]:
    """Facilities with flooding reported nearby, or whose access is to check or confirmed cut."""

    codes = area_codes(config, area)
    return [
        a for a in latest_exposure(session, config, now)["assets"]
        if (codes is None or a["district_code"] in codes)
        and (a["exposure_state"] == "potentially_exposed"
             or a["access_state"] in {"access_under_review", "access_disrupted_confirmed"})
    ]


def tracked_since(session: Session, pilot_id: str) -> datetime | None:
    value = session.scalar(
        select(func.min(FloodIncidentRun.snapshot_at)).where(FloodIncidentRun.pilot_id == pilot_id)
    )
    return utc(value) if value else None


def _run_at_or_before(session: Session, pilot_id: str, moment: datetime) -> FloodIncidentRun | None:
    return session.scalars(
        select(FloodIncidentRun)
        .where(FloodIncidentRun.pilot_id == pilot_id, FloodIncidentRun.snapshot_at <= moment)
        .order_by(FloodIncidentRun.snapshot_at.desc())
        .limit(1)
    ).first()


def _exposure_at(session: Session, config: PilotConfig, moment: datetime) -> dict[str, Any]:
    """Facility states from the newest good roads snapshot at or before ``moment``."""

    roads = next((s for s in config.sources if s.adapter == ROADS_ADAPTER), None)
    fetch = session.scalars(
        select(FloodSourceFetch)
        .where(FloodSourceFetch.pilot_id == config.pilot_id,
               FloodSourceFetch.source_id == roads.source_id,
               FloodSourceFetch.outcome == "ok",
               FloodSourceFetch.retrieved_at <= moment)
        .order_by(FloodSourceFetch.retrieved_at.desc())
        .limit(1)
    ).first() if roads else None
    if fetch is None:
        return {}
    return {
        row.asset_id: row
        for row in session.scalars(
            select(FloodAssetExposure).where(FloodAssetExposure.fetch_id == fetch.id)
        )
    }


def get_situation_changes(
    session: Session, config: PilotConfig, area: str, since: datetime, now: datetime
) -> dict[str, Any]:
    """What changed between ``since`` and ``now``, from stored events and snapshots only."""

    outlines = area_outlines(config, area)
    codes = area_codes(config, area)
    start = tracked_since(session, config.pilot_id)
    if start is None:
        return {"tracked_since": None, "since": since.isoformat(), "now": now.isoformat(),
                "window_starts_before_tracking": True, "counts": {}, "incidents": {},
                "facilities": {}}
    effective = max(since, start)
    incidents = {
        str(i.id): i for i in session.scalars(
            select(FloodIncident).where(FloodIncident.pilot_id == config.pilot_id)
        )
    }
    in_area = {key for key, i in incidents.items()
               if _in((i.summary or {}).get("center") or [0, 0], outlines)}
    # Events of the first run are the baseline: strictly after ``effective`` excludes them.
    events = list(session.scalars(
        select(FloodIncidentEvent)
        .where(FloodIncidentEvent.pilot_id == config.pilot_id,
               FloodIncidentEvent.at > effective, FloodIncidentEvent.at <= now)
        .order_by(FloodIncidentEvent.at)
    ))
    events = [e for e in events if str(e.incident_id) in in_area]
    lists: dict[str, list[str]] = {k: [] for k in (
        "new", "grew", "shrank", "receded", "closed", "reactivated", "conflict_started",
        "confidence_up", "confidence_down", "officer_reviews", "access_to_check")}
    order = {"conflicting": 0, "low": 1, "medium": 2, "high": 3}
    for event in events:
        key, d = str(event.incident_id), event.detail or {}
        if event.kind in {"created", "split"}:
            lists["new"].append(key)
        elif event.kind == "size_changed":
            lists["grew" if d.get("after", 0) > d.get("before", 0) else "shrank"].append(key)
        elif event.kind == "receding":
            lists["receded"].append(key)
        elif event.kind == "closed":
            lists["closed"].append(key)
        elif event.kind == "reactivated":
            lists["reactivated"].append(key)
        elif event.kind == "conflict_started":
            lists["conflict_started"].append(key)
        elif event.kind == "confidence_changed" and d.get("before") and d.get("after"):
            up = order[d["after"]] > order[d["before"]]
            lists["confidence_up" if up else "confidence_down"].append(key)
        elif event.kind == "officer_review":
            lists["officer_reviews"].append(key)
        elif event.kind == "access_to_check":
            lists["access_to_check"].append(key)
    unique = {k: sorted(set(v)) for k, v in lists.items()}

    before = _exposure_at(session, config, effective)
    after = _exposure_at(session, config, now)
    from core.flood_evidence.ddpm_shelters import pilot_assets

    assets = {a.asset_id: a for a in pilot_assets(session, config)[0]
              if codes is None or a.district_code in codes}

    def exposed(rows: dict[str, Any], asset_id: str) -> bool:
        row = rows.get(asset_id)
        return row is not None and row.exposure_state == "potentially_exposed"

    newly = sorted(a for a in assets if exposed(after, a) and not exposed(before, a))
    cleared = sorted(a for a in assets if exposed(before, a) and not exposed(after, a))
    run_then = _run_at_or_before(session, config.pilot_id, effective)
    run_now = _run_at_or_before(session, config.pilot_id, now)
    return {
        "tracked_since": start.isoformat(),
        "since": since.isoformat(),
        "effective_since": effective.isoformat(),
        "now": now.isoformat(),
        "window_starts_before_tracking": since < start,
        "counts": {k: len(v) for k, v in unique.items()},
        "incidents": unique,
        "facilities": {
            "newly_near_flooding": newly,
            "no_longer_near_flooding": cleared,
            "near_flooding_now": sorted(a for a in assets if exposed(after, a)),
        },
        # Demo-area wide; area filtering of past runs is not possible.
        "demo_area_active_then": run_then.active_count if run_then else None,
        "demo_area_active_now": run_now.active_count if run_now else None,
    }


# --- Fact bundle ----------------------------------------------------------------------------


def _short(text: str | None) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text if len(text) <= NAME_MAX else text[: NAME_MAX - 1] + "…"


def _clock(iso: str | None) -> str | None:
    if not iso:
        return None
    moment = datetime.fromisoformat(iso).astimezone(BANGKOK)
    return moment.strftime("%H:%M")


def _ago(iso: str | None, now: datetime) -> int | None:
    if not iso:
        return None
    return max(0, round((now - datetime.fromisoformat(iso)).total_seconds() / 60))


def build_facts(
    session: Session,
    config: PilotConfig,
    area: str,
    since: datetime,
    now: datetime,
    road_names: dict[str, str],
) -> dict[str, Any]:
    """The only facts an answer may use, each with a short opaque label (S, C, I1, F1, L).

    ``road_names`` maps road IDs to display names (from the current roads). Officer notes,
    report text, HAND and RP100 are never included.
    """

    incidents = get_current_incidents(session, config, area, now)
    assets = get_exposed_assets(session, config, area, now)
    changes = get_situation_changes(session, config, area, since, now)
    sources = sources_status(session, config, now)
    facts: list[dict[str, Any]] = []
    labels: dict[str, dict[str, str]] = {}

    active = [i for i in incidents if i["status"] == "active"]
    facts.append({
        "id": "S", "kind": "situation",
        "active_incidents": len(active),
        "receding_incidents": len(incidents) - len(active),
        "conflicting_incidents": sum(1 for i in active if i["conflict"]),
        "incidents_by_confidence": {
            c: sum(1 for i in active if i["confidence"] == c)
            for c in ("conflicting", "low", "medium", "high")
        },
        "facilities_near_flooding": sum(
            1 for a in assets if a["exposure_state"] == "potentially_exposed"),
        "facilities_access_to_check": sum(
            1 for a in assets if a["access_state"] == "access_under_review"),
        "facilities_access_confirmed_cut": sum(
            1 for a in assets if a["access_state"] == "access_disrupted_confirmed"),
        "time_now_bangkok": _clock(now.isoformat()),
    })
    labels["S"] = {"kind": "situation"}

    counts = changes["counts"]
    facts.append({
        "id": "C", "kind": "changes",
        "window_minutes": round((now - since).total_seconds() / 60),
        "tracked_since_bangkok": _clock(changes["tracked_since"]),
        "window_starts_before_tracking": changes["window_starts_before_tracking"],
        "new_incidents": counts.get("new", 0),
        "incidents_grew": counts.get("grew", 0),
        "incidents_shrank": counts.get("shrank", 0),
        "no_longer_reported": counts.get("receded", 0),
        "closed": counts.get("closed", 0),
        "reported_again": counts.get("reactivated", 0),
        "conflicts_appeared": counts.get("conflict_started", 0),
        "confidence_rose": counts.get("confidence_up", 0),
        "confidence_fell": counts.get("confidence_down", 0),
        "officer_checks": counts.get("officer_reviews", 0),
        "facilities_newly_near_flooding": len(changes["facilities"].get("newly_near_flooding", [])),
        "facilities_no_longer_near_flooding": len(
            changes["facilities"].get("no_longer_near_flooding", [])),
    })
    labels["C"] = {"kind": "changes"}

    label_of: dict[str, str] = {}
    for n, incident in enumerate(incidents[:MAX_INCIDENTS], start=1):
        label = f"I{n}"
        label_of[incident["incident_id"]] = label
        names = []
        for key in incident["road_keys"]:
            name = road_names.get(key)
            if name and name not in names:
                names.append(name)
        facts.append({
            "id": label, "kind": "incident",
            "check_order": n,
            "roads": [_short(x) for x in names[:3]] or ["unnamed roads"],
            "status": incident["status"],
            "confidence": incident["confidence"],
            "reasons": [r for r in incident["reasons"] if not r.startswith("source_types:")],
            "source_kinds": incident["source_families"],
            "officer_check": incident.get("verification", "unverified"),
            "road_segments": len(incident["road_keys"]),
            "reports": len(incident["report_keys"]),
            "newest_evidence_bangkok": _clock(incident["newest_evidence_at"]),
            "newest_evidence_minutes_ago": _ago(incident["newest_evidence_at"], now),
            "age_basis": incident["freshness_basis"],
            "deepest_reported_cm": incident.get("max_depth_cm"),
            "roads_closed": incident.get("closed_roads", 0),
            "hospital_nearby": bool(incident.get("hospital_near")),
            "facility_access_to_check": bool(incident.get("access_to_check")),
            "first_seen_bangkok": _clock(incident["opened_at"]),
        })
        labels[label] = {"kind": "incident", "ref": incident["incident_id"]}
    for n, asset in enumerate(assets, start=1):
        label = f"F{n}"
        facts.append({
            "id": label, "kind": "facility",
            "name": _short(asset["name"] or asset["name_en"]) or f"unnamed {asset['asset_type']}",
            "facility_type": asset["asset_type"],
            "flooding_reported_within_m": asset["nearest_distance_m"],
            "exposure": asset["exposure_state"],
            "access": asset["access_state"],
            "source": "DDPM evacuation centre (GRP data library)"
            if asset["asset_type"] == "evacuation_centre" else "OpenStreetMap",
            "newly_near_flooding": asset["asset_id"] in changes["facilities"].get(
                "newly_near_flooding", []),
        })
        labels[label] = {"kind": "facility", "ref": asset["asset_id"]}

    weather = latest_weather(session, config)
    if weather["available"]:
        districts = {a["admin_code"]: a["name"] for a in all_areas(config.base_id)}
        codes = area_codes(config, area)
        facts.append({
            "id": "W", "kind": "rain",
            "note": "Weather context from radar; rain is not flooding, a forecast is not an "
                    "observation",
            "radar_time_bangkok": _clock(weather["observed_at"]),
            "districts": [
                {"district": districts.get(w["id"], w["id"]),
                 "rain_now": (w["rain_now"] or {}).get("dominant_level", "unknown"),
                 "heaviest_now": (w["rain_now"] or {}).get("max_level", "unknown"),
                 "in_30_min": next((f.get("max_level", "unknown") for f in (w["forecast"] or [])
                                    if f.get("available")), "unknown")}
                for w in weather["scopes"]
                if w["kind"] == "district" and (codes is None or w["id"] in codes)
            ],
        })
        labels["W"] = {"kind": "rain"}

    facts.append({
        "id": "L", "kind": "limits",
        "incidents_not_listed": max(0, len(incidents) - MAX_INCIDENTS),
        "sources": {s["source_id"]: s["state"] for s in sources},
        "not_connected": ["BMA direct sensors and rain", "real CCTV (test entries only)",
                          "population", "road network (access cannot be confirmed by GRP)",
                          "river forecast (River Watch is separate and is not street flooding)"],
        "road_verdicts_are": "Floodboard's estimate, not a BMA rule",
        "facilities_are": "schools, hospitals and clinics from OpenStreetMap (not an official "
                          "list), plus DDPM evacuation centres from the GRP data library",
        "confidence_is": "a pilot rule with reasons, not a probability",
        **({"replay": True, "simulated_time_bangkok": _clock(now.isoformat()),
            "replay_uses": "today's facility list, cameras and rules, not those of the time"}
           if config.is_replay else {}),
    })
    labels["L"] = {"kind": "limits"}
    return {"facts": facts, "labels": labels, "changes": changes,
            "incident_labels": label_of}
