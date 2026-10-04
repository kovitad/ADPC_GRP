"""Keep incidents' identity across snapshots and record what changed (ADR-0041).

Runs in the worker after each good roads snapshot. Matching is deterministic:

- a new cluster continues the open incident it shares the most road segments with;
- if it shares none, it continues an open incident whose footprint is within reach (Floodboard
  re-cuts segments, so geometry hashes alone would spawn duplicates);
- when one cluster reaches several incidents, the oldest survives and the others are closed as
  ``merged`` into it; when several clusters reach one incident, the biggest keeps it and the
  others open new incidents ``split`` from it;
- an incident with no cluster this time becomes ``receding``, and closes after
  ``RECEDING_CLOSE`` without returning.

A snapshot not newer than the last one processed is skipped, so loading older captures can
never rewrite lifecycle history.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.flood_evidence.areas import pilot_areas
from core.flood_evidence.config import PilotConfig
from core.flood_evidence.exposure import latest_exposure
from core.flood_evidence.geo import boxes_touch, district_codes, expand
from core.flood_evidence.incidents import (
    RULE_VERSION,
    Params,
    build_incidents,
    facility_flags,
    priority,
)
from core.flood_evidence.ingest import utc
from core.flood_evidence.models import (
    FloodIncident,
    FloodIncidentEvent,
    FloodIncidentRun,
    FloodSourceFetch,
)
from core.flood_evidence.reviews import history, incident_verification, reviewer_names
from core.flood_evidence.situation import current_roads, recent_reports

ACTIVE = "active"
RECEDING = "receding"
CLOSED = "closed"
OPEN = (ACTIVE, RECEDING)
RECEDING_CLOSE = timedelta(hours=2)
REPORT_WINDOW_HOURS = 6


def params_for(config: PilotConfig) -> Params:
    return Params(bands=config.freshness_minutes)


def demo_areas(config: PilotConfig) -> list[tuple[str, dict[str, Any]]]:
    """(district code, outline) for each district in the demo area."""

    codes = set(config.demo_corridor.get("areas") or [])
    if config.base_id != "bangkok" or not codes:
        return []
    return [(a["admin_code"], a["outline"]) for a in pilot_areas(config)
            if a["admin_code"] in codes]


def demo_outlines(config: PilotConfig) -> list[dict[str, Any]]:
    return [outline for _, outline in demo_areas(config)]


def _event(session: Session, incident: FloodIncident, at: datetime, kind: str, **detail) -> None:
    session.add(FloodIncidentEvent(pilot_id=incident.pilot_id, incident_id=incident.id, at=at,
                                   kind=kind, detail=detail))


def _changes(session: Session, incident: FloodIncident, new: dict[str, Any], at: datetime) -> None:
    old = incident.summary or {}
    if old.get("confidence") != new["confidence"]:
        _event(session, incident, at, "confidence_changed",
               before=old.get("confidence"), after=new["confidence"], reasons=new["reasons"])
    if bool(old.get("conflict")) != new["conflict"]:
        _event(session, incident, at, "conflict_started" if new["conflict"] else "conflict_ended",
               contrary_keys=new["contrary_keys"])
    before, after = len(old.get("road_keys") or []), len(new["road_keys"])
    if before != after:
        _event(session, incident, at, "size_changed", before=before, after=after)
    if old.get("access_to_check") != new.get("access_to_check") and new.get("access_to_check"):
        _event(session, incident, at, "access_to_check", facility_ids=new["facility_ids"])


def last_processed(session: Session, pilot_id: str) -> datetime | None:
    value = session.scalar(
        select(func.max(FloodIncidentRun.snapshot_at)).where(FloodIncidentRun.pilot_id == pilot_id)
    )
    return utc(value) if value else None


def update_incidents(session: Session, config: PilotConfig, fetch: FloodSourceFetch) -> int | None:
    """Process one roads snapshot. Returns the active count, or None when it was skipped."""

    started = time.monotonic()
    at = utc(fetch.retrieved_at)
    previous = last_processed(session, config.pilot_id)
    if previous is not None and at <= previous:
        return None
    outlines = demo_outlines(config)
    params = params_for(config)
    roads = current_roads(session, config, at)["features"]
    reports = recent_reports(session, config, at, REPORT_WINDOW_HOURS)["features"]
    exposures = latest_exposure(session, config, at)["assets"]
    found = build_incidents(roads, reports, outlines, at, params) if outlines else []
    areas = demo_areas(config)
    for item in found:
        item.update(facility_flags(item, exposures))
        # Computed once here, in the worker, so the Planner, the feed and the archive never
        # do spatial work in a request (ADR-0056).
        item["district_codes"] = district_codes(item["geometry"], areas)

    open_incidents = list(
        session.scalars(
            select(FloodIncident)
            .where(FloodIncident.pilot_id == config.pilot_id, FloodIncident.status.in_(OPEN))
            .order_by(FloodIncident.opened_at, FloodIncident.id)
        )
    )
    # Match against footprints as they were before this snapshot, not as updated in this loop.
    before_keys = {i.id: set(i.road_keys) for i in open_incidents}
    before_box = {i.id: tuple(i.bbox) for i in open_incidents}
    claimed: set[UUID] = set()
    for item in found:  # biggest first, from build_incidents
        keys = set(item["road_keys"])
        overlap = sorted(
            ((len(keys & before_keys[i.id]), i) for i in open_incidents
             if keys & before_keys[i.id]),
            key=lambda pair: (-pair[0], pair[1].opened_at, str(pair[1].id)),
        )
        candidates = [i for _, i in overlap]
        if not candidates:
            reach = expand(tuple(item["bbox"]), params.link_m)
            candidates = [i for i in open_incidents if boxes_touch(reach, before_box[i.id])]
        available = sorted((i for i in candidates if i.id not in claimed),
                           key=lambda i: (i.opened_at, str(i.id)))
        if available:
            survivor = available[0]
            claimed.add(survivor.id)
            for other in available[1:]:
                claimed.add(other.id)
                other.status, other.closed_at = CLOSED, at
                _event(session, other, at, "merged", into=str(survivor.id))
                _event(session, survivor, at, "absorbed", absorbed_id=str(other.id))
            if survivor.status == RECEDING:
                _event(session, survivor, at, "reactivated")
            _changes(session, survivor, item, at)
            incident = survivor
        else:
            incident = FloodIncident(pilot_id=config.pilot_id, opened_at=at, summary={},
                                     road_keys=[], bbox=item["bbox"], rule_version=RULE_VERSION,
                                     status=ACTIVE, last_active_at=at, last_snapshot_at=at)
            session.add(incident)
            session.flush()
            if candidates:
                _event(session, incident, at, "split", from_incident=str(candidates[0].id))
            _event(session, incident, at, "created", confidence=item["confidence"],
                   road_count=len(item["road_keys"]))
            claimed.add(incident.id)
        incident.status = ACTIVE
        incident.last_active_at = at
        incident.last_snapshot_at = at
        incident.road_keys = item["road_keys"]
        incident.bbox = item["bbox"]
        incident.rule_version = RULE_VERSION
        incident.summary = {k: v for k, v in item.items() if k != "geometry"}

    for incident in open_incidents:
        if incident.id in claimed or incident.status == CLOSED:
            continue
        incident.last_snapshot_at = at
        if incident.status == ACTIVE:
            incident.status = RECEDING
            _event(session, incident, at, "receding")
        elif at - utc(incident.last_active_at) >= RECEDING_CLOSE:
            incident.status, incident.closed_at = CLOSED, at
            _event(session, incident, at, "closed", reason="no_flooding_reported")

    active = sum(1 for _ in found)
    session.add(FloodIncidentRun(pilot_id=config.pilot_id, fetch_id=fetch.id, snapshot_at=at,
                                 active_count=active,
                                 duration_ms=int((time.monotonic() - started) * 1000)))
    session.flush()
    return active


def _public(incident: FloodIncident) -> dict[str, Any]:
    summary = dict(incident.summary or {})
    return {
        "incident_id": str(incident.id),
        "status": incident.status,
        "opened_at": utc(incident.opened_at).isoformat(),
        "last_active_at": utc(incident.last_active_at).isoformat(),
        "last_snapshot_at": utc(incident.last_snapshot_at).isoformat(),
        **summary,
    }


def list_incidents(
    session: Session, config: PilotConfig, now: datetime | None = None
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    rows = list(
        session.scalars(
            select(FloodIncident).where(
                FloodIncident.pilot_id == config.pilot_id, FloodIncident.status.in_(OPEN)
            )
        )
    )
    officer = incident_verification(session, config, rows, now)
    public = {str(r.id): _with_officer(_public(r), officer) for r in rows}
    active = sorted((public[str(r.id)] for r in rows if r.status == ACTIVE), key=priority)
    receding = sorted((public[str(r.id)] for r in rows if r.status == RECEDING),
                      key=lambda i: i["last_active_at"], reverse=True)
    return {
        "incidents": active + receding,
        "last_processed_at": (lp.isoformat() if (lp := last_processed(session, config.pilot_id))
                              else None),
        "rule_version": RULE_VERSION,
    }


def _with_officer(item: dict[str, Any], officer: dict[str, dict]) -> dict[str, Any]:
    return {**item, "verification": "unverified", **officer.get(item["incident_id"], {})}


def incident_detail(
    session: Session, config: PilotConfig, incident_id: UUID, now: datetime | None = None
) -> dict[str, Any] | None:
    now = now or datetime.now(UTC)
    incident = session.get(FloodIncident, incident_id)
    if incident is None or incident.pilot_id != config.pilot_id:
        return None
    officer = incident_verification(session, config, [incident], now)
    events = session.scalars(
        select(FloodIncidentEvent)
        .where(FloodIncidentEvent.incident_id == incident.id)
        .order_by(FloodIncidentEvent.at.desc(), FloodIncidentEvent.id.desc())
        .limit(50)
    )
    reviews = history(session, config, "incident", str(incident.id), now,
                      reviewer_names(session, config, "incident", str(incident.id)))
    return {
        **_with_officer(_public(incident), officer),
        "reviews": reviews,
        "events": [
            {"at": utc(e.at).isoformat(), "kind": e.kind, "detail": e.detail} for e in events
        ],
    }
