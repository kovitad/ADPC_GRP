"""Read stored flood evidence for the operator view: source health, roads, reports, cards.

The current road layer is the latest successful roads snapshot, not the newest row per segment:
a segment the provider re-cut or dropped must leave the map rather than keep its last flooded
state forever. Reports are an event stream and are read by their own time.

Expired evidence keeps its record but loses its verdict: it is shown as "no recent evidence"
and never counts as the situation now (AC2).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.flood_evidence.config import PilotConfig, SourceConfig
from core.flood_evidence.freshness import EXPIRED, counts_as_current, freshness
from core.flood_evidence.ingest import utc
from core.flood_evidence.models import FETCH_OK, FloodObservation, FloodSourceFetch
from core.flood_evidence.observation import REPORT, ROAD_SEGMENT, VEHICLES

HEALTH_OK = "ok"
HEALTH_DEGRADED = "degraded"
HEALTH_OFFLINE = "offline"
HEALTH_NEVER = "never_fetched"
ROADS_ADAPTER = "floodboard_roads"
REPORTS_ADAPTER = "floodboard_reports"
# Every adapter whose observations are point reports (ADR-0048 adds the Longdo event feed).
REPORT_ADAPTERS = frozenset({REPORTS_ADAPTER, "longdo_events"})


def _iso(moment: datetime | None) -> str | None:
    return utc(moment).isoformat() if moment else None


def _latest(
    session: Session, config: PilotConfig, source_id: str, as_of: datetime, ok_only: bool
) -> FloodSourceFetch | None:
    query = select(FloodSourceFetch).where(
        FloodSourceFetch.pilot_id == config.pilot_id,
        FloodSourceFetch.source_id == source_id,
        FloodSourceFetch.retrieved_at <= as_of,
    )
    if ok_only:
        query = query.where(FloodSourceFetch.outcome == FETCH_OK)
    return session.scalars(query.order_by(FloodSourceFetch.retrieved_at.desc()).limit(1)).first()


def latest_roads_snapshot(
    session: Session, config: PilotConfig, as_of: datetime
) -> FloodSourceFetch | None:
    """The latest good roads fetch at ``as_of``: the snapshot every road read is based on."""

    source = next((s for s in config.sources if s.adapter == ROADS_ADAPTER), None)
    return _latest(session, config, source.source_id, as_of, True) if source else None


def source_health(
    session: Session, config: PilotConfig, source: SourceConfig, as_of: datetime
) -> dict[str, Any]:
    """ok: the newest pull worked and is on time. degraded: data is usable but late or the last
    pull failed. offline: no usable pull inside the stale window. Nothing is guessed."""

    attempt = _latest(session, config, source.source_id, as_of, ok_only=False)
    good = _latest(session, config, source.source_id, as_of, ok_only=True)
    on_time = timedelta(minutes=source.interval_minutes * 3)
    usable = timedelta(minutes=config.freshness_minutes["stale"])
    if attempt is None:
        state = HEALTH_NEVER
    elif good is None or as_of - utc(good.retrieved_at) > usable:
        state = HEALTH_OFFLINE
    elif attempt.outcome == FETCH_OK and as_of - utc(attempt.retrieved_at) <= on_time:
        state = HEALTH_OK
    else:
        state = HEALTH_DEGRADED
    registry = source.registry
    return {
        "source_id": source.source_id,
        "dataset": registry.get("dataset"),
        "owner": registry.get("owner"),
        "license": registry.get("license"),
        "attribution": registry.get("attribution"),
        "update_frequency": registry.get("update_frequency"),
        "quality_notes": registry.get("quality_notes"),
        "pii": registry.get("pii"),
        "state": state,
        "last_attempt_at": _iso(attempt.retrieved_at) if attempt else None,
        "last_attempt_outcome": attempt.outcome if attempt else None,
        "last_success_at": _iso(good.retrieved_at) if good else None,
        "last_success_records": good.record_count if good else None,
    }


def sources_status(session: Session, config: PilotConfig, as_of: datetime) -> list[dict[str, Any]]:
    return [source_health(session, config, source, as_of) for source in config.sources]


def _road_feature(row: FloodObservation, band: str) -> dict[str, Any]:
    state = dict(row.state)
    live = band != EXPIRED
    return {
        "type": "Feature",
        "geometry": row.geometry,
        "properties": {
            "id": row.record_key[:16],
            "name": state.get("name"),
            "name_en": state.get("name_en"),
            "road_class": state.get("road_class"),
            "depth_cm": row.depth_cm,
            "closed_all": state.get("closed_all"),
            "closed_small": state.get("closed_small"),
            "cleared": state.get("cleared"),
            # Floodboard's estimate, never a GRP or BMA rule; dropped once expired.
            "provider_verdict": state.get("verdict") if live else None,
            "provider_confidence": (row.provider_judgement or {}).get("conf"),
            "reported_at": _iso(row.reported_at),
            "freshness": band,
            "evidence_class": row.evidence_class,
            "underlying_sources": row.underlying_sources,
            "source_id": row.source_id,
        },
    }


def current_roads(
    session: Session, config: PilotConfig, as_of: datetime, include_all: bool = False
) -> dict[str, Any]:
    """Segments in the latest good roads snapshot. By default: not cleared (at any age, so old
    flooding is visible as old), plus cleared segments with current evidence."""

    source = next((s for s in config.sources if s.adapter == ROADS_ADAPTER), None)
    features: list[dict[str, Any]] = []
    snapshot = _latest(session, config, source.source_id, as_of, True) if source else None
    if snapshot is not None:
        rows = session.scalars(
            select(FloodObservation).where(FloodObservation.last_fetch_id == snapshot.id)
        )
        for row in rows:
            band = freshness(utc(row.reported_at), as_of, config.freshness_minutes)
            cleared = bool(row.state.get("cleared"))
            if include_all or not cleared or counts_as_current(band):
                features.append(_road_feature(row, band))
    return {
        "type": "FeatureCollection",
        "features": features,
        "snapshot_retrieved_at": _iso(snapshot.retrieved_at) if snapshot else None,
        "as_of": as_of.isoformat(),
    }


def road_by_id(
    session: Session, config: PilotConfig, as_of: datetime, road_id: str
) -> dict[str, Any] | None:
    """One segment of the latest good snapshot, by the short ID the page shows."""

    source = next((s for s in config.sources if s.adapter == ROADS_ADAPTER), None)
    snapshot = _latest(session, config, source.source_id, as_of, True) if source else None
    if snapshot is None:
        return None
    row = session.scalars(
        select(FloodObservation).where(
            FloodObservation.last_fetch_id == snapshot.id,
            FloodObservation.record_key.startswith(road_id, autoescape=True),
        )
    ).first()
    if row is None:
        return None
    return _road_feature(row, freshness(utc(row.reported_at), as_of, config.freshness_minutes))


def _report_rank(row: FloodObservation) -> tuple:
    direct = row.source_id != REPORTS_ADAPTER and row.external_id.startswith("longdo:")
    return (direct, utc(row.last_seen_at))


def recent_reports(
    session: Session, config: PilotConfig, as_of: datetime, hours: int
) -> dict[str, Any]:
    """The newest state of each report observed in the window. No text and no links."""

    report_sources = [s.source_id for s in config.sources if s.adapter in REPORT_ADAPTERS]
    newest: dict[str, FloodObservation] = {}
    if report_sources:
        rows = session.scalars(
            select(FloodObservation).where(
                FloodObservation.pilot_id == config.pilot_id,
                FloodObservation.source_id.in_(report_sources),
                FloodObservation.kind == REPORT,
                FloodObservation.observed_at >= as_of - timedelta(hours=hours),
                FloodObservation.observed_at <= as_of,
                FloodObservation.first_seen_at <= as_of,
            )
        )
        for row in rows:
            # The same report can arrive twice: Floodboard relays Longdo events under the same
            # ID ("longdo:<eid>"). The direct copy wins, since it names the real source family.
            held = newest.get(row.record_key)
            if held is None or _report_rank(row) > _report_rank(held):
                newest[row.record_key] = row
    features = []
    for row in sorted(newest.values(), key=lambda r: utc(r.observed_at), reverse=True):
        band = freshness(utc(row.observed_at), as_of, config.freshness_minutes)
        features.append(
            {
                "type": "Feature",
                "geometry": row.geometry,
                "properties": {
                    "id": row.record_key[:16],
                    "underlying_source": (row.underlying_sources or [None])[0],
                    "tier": row.state.get("tier"),
                    "depth_cm": row.depth_cm,
                    "closed_all": row.state.get("closed_all"),
                    "closed_small": row.state.get("closed_small"),
                    "cleared": row.state.get("cleared"),
                    "observed_at": _iso(row.observed_at),
                    "freshness": band,
                    "evidence_class": row.evidence_class,
                    "has_text": row.text_sha256 is not None,
                },
            }
        )
    return {"type": "FeatureCollection", "features": features, "hours": hours,
            "as_of": as_of.isoformat()}


def situation(session: Session, config: PilotConfig, as_of: datetime) -> dict[str, Any]:
    """Top cards (spec §24). Only current evidence counts toward "now"."""

    roads = current_roads(session, config, as_of)["features"]
    affected = [
        f for f in roads
        if not f["properties"]["cleared"] and counts_as_current(f["properties"]["freshness"])
    ]
    by_vehicle = {
        vehicle: {
            label: sum(1 for f in affected if f["properties"]["provider_verdict"][vehicle] == label)
            for label in ("caution", "risky", "blocked")
        }
        for vehicle in VEHICLES
    }
    reports = recent_reports(session, config, as_of, 1)["features"]
    sources = sources_status(session, config, as_of)
    return {
        "as_of": as_of.isoformat(),
        "roads_affected_now": len(affected),
        "roads_flood_not_recent": sum(
            1 for f in roads
            if not f["properties"]["cleared"]
            and not counts_as_current(f["properties"]["freshness"])
        ),
        "roads_closed_now": sum(1 for f in affected if f["properties"]["closed_all"]),
        "provider_verdicts_now": by_vehicle,
        "reports_last_hour": len(reports),
        "sources_not_ok": sum(1 for s in sources if s["state"] != HEALTH_OK),
        "sources": sources,
        "kinds": [ROAD_SEGMENT, REPORT],
    }
