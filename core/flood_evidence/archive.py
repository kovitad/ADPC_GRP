"""Daily research archive for data scientists (ADR-0055).

Once a UTC day is over, the worker writes one gzipped JSON Lines file per table for that day,
plus a manifest, under ``research/flood/<pilot>/v1/``. Only what a model needs is kept:

- **state changes**, not snapshots: a road or facility row starts when its state changes
  (``valid_from``) and says how long it held as of the export (``valid_to``);
- **no text, links, provider IDs or names**: reports are keyed by a salted hash, and officers
  by a stable salted pseudonym;
- **pinned versions**: every row made by a rule carries its ``rule_version``.

A day is written once and never overwritten (storage keys are immutable). Replays are refused,
and today is refused because it is not over. The worker runs this before retention (ADR-0045)
removes anything.
"""

from __future__ import annotations

import gzip
import hashlib
import hmac
import json
import secrets
import tempfile
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.flood_evidence.assets import asset_registry
from core.flood_evidence.config import PilotConfig
from core.flood_evidence.geo import district_codes
from core.flood_evidence.ingest import utc
from core.flood_evidence.models import (
    FloodAssetExposure,
    FloodIncident,
    FloodIncidentEvent,
    FloodIncidentRun,
    FloodObservation,
    FloodReview,
    FloodSourceFetch,
    FloodWeather,
)
from core.flood_evidence.observation import REPORT, ROAD_SEGMENT
from core.river_watch import bangkok_outlines
from core.storage import LocalStorage

ARCHIVE_VERSION = "FloodArchive v1"
SALT_KEY = "private/flood-archive-salt"
TABLES = ("road_state", "road_geometry", "report", "incident", "incident_event",
          "incident_run", "facility_exposure", "label", "weather", "context")
# Incident summary fields worth keeping; evidence keys and display-only fields are left out.
INCIDENT_FIELDS = ("confidence", "conflict", "reasons", "source_families", "freshness_basis",
                   "newest_evidence_at", "max_depth_cm", "closed_roads", "worst_verdict",
                   "center", "facility_ids", "hospital_near", "access_to_check")
LABELS = {"flooding_seen": "flooding_seen", "dry_seen": "dry_seen",
          "cannot_tell": "cannot_tell", "access_disrupted": "access_disrupted",
          "withdraw": "withdrawn"}


def prefix(pilot_id: str) -> str:
    return f"research/flood/{pilot_id}/v1"


def manifest_key(pilot_id: str, day: date) -> str:
    return f"{prefix(pilot_id)}/manifests/{day.isoformat()}.json"


def table_key(pilot_id: str, table: str, day: date) -> str:
    return f"{prefix(pilot_id)}/{table}/{day.isoformat()}.jsonl.gz"


def _iso(value: datetime | None) -> str | None:
    return utc(value).isoformat() if value is not None else None


def archive_salt(storage: LocalStorage) -> bytes:
    """A secret made once and kept outside the research folder, so hashes cannot be reversed
    by guessing IDs, yet stay stable across days."""

    if not storage.exists(SALT_KEY):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "salt"
            path.write_text(secrets.token_hex(32), encoding="ascii")
            storage.put(SALT_KEY, path)
    return storage.read_bytes(SALT_KEY).strip()


def pseudonym(salt: bytes, value: str, length: int = 16) -> str:
    return hmac.new(salt, value.encode("utf-8"), hashlib.sha256).hexdigest()[:length]


_districts = district_codes


def _areas(config: PilotConfig) -> list[tuple[str, dict]]:
    if config.base_id != "bangkok":
        return []
    return [(a["admin_code"], a["outline"]) for a in bangkok_outlines()]


def _road_rows(rows: list[FloodObservation], areas) -> tuple[list[dict], list[dict]]:
    states, geometries, seen = [], [], set()
    for row in rows:
        segment = row.record_key[:16]
        geometry_hash = row.external_id
        state = dict(row.state)
        states.append({
            "segment_key": segment, "geometry_hash": geometry_hash,
            "district_codes": _districts(row.geometry, areas),
            "depth_cm": row.depth_cm, "closed_all": state.get("closed_all"),
            "closed_small": state.get("closed_small"), "cleared": state.get("cleared"),
            "provider_verdict": state.get("verdict"),
            "provider_confidence": (row.provider_judgement or {}).get("conf"),
            "underlying_sources": list(row.underlying_sources),
            "evidence_class": row.evidence_class, "reported_at": _iso(row.reported_at),
            "valid_from": _iso(row.first_seen_at), "valid_to": _iso(row.last_seen_at),
            "rule_version": row.rule_version,
        })
        if geometry_hash not in seen:
            seen.add(geometry_hash)
            geometries.append({"geometry_hash": geometry_hash, "segment_key": segment,
                               "name": state.get("name"), "name_en": state.get("name_en"),
                               "road_class": state.get("road_class"),
                               "geometry": row.geometry})
    return states, geometries


def _report_rows(rows: list[FloodObservation], salt: bytes, areas) -> list[dict]:
    out = []
    for row in rows:
        state = dict(row.state)
        out.append({
            "report_key": pseudonym(salt, row.record_key, 24),
            "observed_at": _iso(row.observed_at),
            "lon": row.geometry["coordinates"][0], "lat": row.geometry["coordinates"][1],
            "district_codes": _districts(row.geometry, areas),
            "underlying_source": (row.underlying_sources or [None])[0],
            "tier": state.get("tier"), "depth_cm": row.depth_cm,
            "closed_all": state.get("closed_all"), "closed_small": state.get("closed_small"),
            "cleared": state.get("cleared"), "evidence_class": row.evidence_class,
            "provider_weight": (row.provider_judgement or {}).get("current_weight"),
            "valid_from": _iso(row.first_seen_at), "valid_to": _iso(row.last_seen_at),
            "rule_version": row.rule_version,
        })
    return out


def _incident_row(incident: FloodIncident, areas) -> dict:
    summary = dict(incident.summary or {})
    codes, basis = summary.get("district_codes"), "roads"
    if codes is None:
        # Incidents processed before ADR-0056 have no stored codes: approximate from the box.
        west, south, east, north = incident.bbox
        box = {"type": "MultiLineString", "coordinates": [
            [[west, south], [east, south], [east, north], [west, north]],
            [[(west + east) / 2, (south + north) / 2]]]}
        codes, basis = _districts(box, areas), "box_approx"
    return {
        "incident_id": str(incident.id), "status_at_export": incident.status,
        "opened_at": _iso(incident.opened_at), "last_active_at": _iso(incident.last_active_at),
        "last_snapshot_at": _iso(incident.last_snapshot_at),
        "closed_at": _iso(incident.closed_at), "bbox": list(incident.bbox),
        "district_codes": codes, "district_codes_basis": basis,
        "road_keys": list(incident.road_keys),
        **{k: summary.get(k) for k in INCIDENT_FIELDS},
        "rule_version": incident.rule_version,
    }


def _exposure_changes(session: Session, config: PilotConfig, start: datetime,
                      end: datetime) -> list[dict]:
    """Facility rows only where the state changed from the facility's previous row."""

    assets = {a.asset_id: a for a in asset_registry(config.base_id)[0]}
    previous: dict[str, tuple] = {}
    before = session.execute(
        select(FloodAssetExposure).where(
            FloodAssetExposure.pilot_id == config.pilot_id,
            FloodAssetExposure.computed_at < start,
            FloodAssetExposure.computed_at >= start - timedelta(days=1),
        ).order_by(FloodAssetExposure.computed_at)
    ).scalars()
    for row in before:
        previous[row.asset_id] = (row.exposure_state, row.access_state, row.nearest_road_key)
    out = []
    rows = session.execute(
        select(FloodAssetExposure).where(
            FloodAssetExposure.pilot_id == config.pilot_id,
            FloodAssetExposure.computed_at >= start, FloodAssetExposure.computed_at < end,
        ).order_by(FloodAssetExposure.computed_at, FloodAssetExposure.asset_id)
    ).scalars()
    for row in rows:
        key = (row.exposure_state, row.access_state, row.nearest_road_key)
        if previous.get(row.asset_id) == key:
            continue
        previous[row.asset_id] = key
        asset = assets.get(row.asset_id)
        out.append({
            "asset_id": row.asset_id,
            "asset_type": asset.asset_type if asset else None,
            "district_code": asset.district_code if asset else None,
            "valid_from": _iso(row.computed_at), "exposure_state": row.exposure_state,
            "access_state": row.access_state, "nearest_road_key": row.nearest_road_key,
            "nearest_distance_m": row.nearest_distance_m, "road_keys": list(row.road_keys),
            "reasons": list(row.reasons), "rule_version": row.rule_version,
        })
    return out


def _label_rows(reviews: list[FloodReview], salt: bytes) -> list[dict]:
    return [{
        "target_kind": r.target_kind, "target_id": r.target_id,
        "label": LABELS.get(r.action, r.action), "method": "officer",
        "checker": pseudonym(salt, str(r.user_id)),
        "camera_id": r.camera_id, "road_keys": list(r.road_keys),
        "at": _iso(r.created_at), "expires_at": _iso(r.expires_at),
        "withdrawn_at": _iso(r.withdrawn_at),
    } for r in reviews]


def build_day(session: Session, config: PilotConfig, day: date, salt: bytes) -> dict[str, list]:
    """Every table's rows for one UTC day. Pure reads; nothing is written."""

    start = datetime.combine(day, time(), tzinfo=UTC)
    end = start + timedelta(days=1)
    pilot = config.pilot_id
    areas = _areas(config)

    def observations(kind: str) -> list[FloodObservation]:
        return list(session.scalars(
            select(FloodObservation).where(
                FloodObservation.pilot_id == pilot, FloodObservation.kind == kind,
                FloodObservation.first_seen_at >= start, FloodObservation.first_seen_at < end,
            ).order_by(FloodObservation.first_seen_at, FloodObservation.record_key)
        ))

    road_state, road_geometry = _road_rows(observations(ROAD_SEGMENT), areas)
    incidents = session.scalars(
        select(FloodIncident).where(
            FloodIncident.pilot_id == pilot, FloodIncident.opened_at < end,
            FloodIncident.last_snapshot_at >= start,
        ).order_by(FloodIncident.opened_at, FloodIncident.id)
    )
    events = session.scalars(
        select(FloodIncidentEvent).where(
            FloodIncidentEvent.pilot_id == pilot, FloodIncidentEvent.at >= start,
            FloodIncidentEvent.at < end,
        ).order_by(FloodIncidentEvent.at, FloodIncidentEvent.id)
    )
    runs = session.scalars(
        select(FloodIncidentRun).where(
            FloodIncidentRun.pilot_id == pilot, FloodIncidentRun.snapshot_at >= start,
            FloodIncidentRun.snapshot_at < end,
        ).order_by(FloodIncidentRun.snapshot_at)
    )
    reviews = list(session.scalars(
        select(FloodReview).where(
            FloodReview.pilot_id == pilot, FloodReview.created_at >= start,
            FloodReview.created_at < end,
        ).order_by(FloodReview.created_at, FloodReview.id)
    ))
    weather = session.scalars(
        select(FloodWeather).where(
            FloodWeather.pilot_id == pilot, FloodWeather.observed_base_time >= start,
            FloodWeather.observed_base_time < end,
        ).order_by(FloodWeather.observed_base_time, FloodWeather.scope_kind,
                   FloodWeather.scope_id)
    )
    _, asset_source = asset_registry(config.base_id)
    return {
        "road_state": road_state,
        "road_geometry": road_geometry,
        "report": _report_rows(observations(REPORT), salt, areas),
        "incident": [_incident_row(i, areas) for i in incidents],
        "incident_event": [{"incident_id": str(e.incident_id), "at": _iso(e.at),
                            "kind": e.kind, "detail": e.detail} for e in events],
        "incident_run": [{"snapshot_at": _iso(r.snapshot_at), "active_count": r.active_count,
                          "duration_ms": r.duration_ms} for r in runs],
        "facility_exposure": _exposure_changes(session, config, start, end),
        "label": _label_rows(reviews, salt),
        "weather": [{"observed_base_time": _iso(w.observed_base_time),
                     "scope_kind": w.scope_kind,
                     # An incident scope is an incident ID; a district scope is its code.
                     "scope_id": w.scope_id, "radius_km": w.radius_km,
                     "rain_now": w.rain_now, "forecast": w.forecast, "outcome": w.outcome}
                    for w in weather],
        "context": [{"archive_version": ARCHIVE_VERSION, "pilot_id": pilot, "day": day.isoformat(),
                     "demo_areas": list(config.demo_corridor.get("areas") or []),
                     "freshness_minutes": config.freshness_minutes,
                     "exposure": config.exposure,
                     "facility_source": {k: v for k, v in (asset_source or {}).items()
                                         if k in ("provider", "license", "osm_timestamp",
                                                  "captured_at")}}],
    }


def _write_jsonl_gz(rows: list[dict], path: Path) -> None:
    # mtime=0 keeps the bytes identical for identical rows, so a rerun is recognised.
    with open(path, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as handle:
        for row in rows:
            handle.write((json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n").encode())


def export_day(session: Session, storage: LocalStorage, config: PilotConfig, day: date,
               now: datetime | None = None) -> dict | None:
    """Write one finished UTC day. Returns the manifest, or None when it was already written."""

    if config.is_replay:
        raise ValueError("The research archive takes live pilots only; replays are never kept")
    now = now or datetime.now(UTC)
    if day >= now.astimezone(UTC).date():
        raise ValueError("A day is archived only once it is over")
    key = manifest_key(config.pilot_id, day)
    if storage.exists(key):
        return None
    tables = build_day(session, config, day, archive_salt(storage))
    start = datetime.combine(day, time(), tzinfo=UTC)
    fetches = session.execute(
        select(FloodSourceFetch.source_id, func.count(), func.min(FloodSourceFetch.retrieved_at),
               func.max(FloodSourceFetch.retrieved_at)).where(
            FloodSourceFetch.pilot_id == config.pilot_id,
            FloodSourceFetch.retrieved_at >= start,
            FloodSourceFetch.retrieved_at < start + timedelta(days=1),
        ).group_by(FloodSourceFetch.source_id)
    ).all()
    manifest: dict[str, Any] = {
        "archive_version": ARCHIVE_VERSION, "pilot_id": config.pilot_id,
        "day": day.isoformat(), "written_at": now.isoformat(), "tables": {},
        "source_fetches": {s: {"count": n, "first": _iso(a), "last": _iso(b)}
                           for s, n, a, b in fetches},
        "licences": {s.source_id: {"license": s.registry.get("license"),
                                   "attribution": s.registry.get("attribution")}
                     for s in config.sources},
        "notes": "valid_to is as of written_at; a state that continued is extended in later "
                 "days' files only if it changed. No text, links, provider IDs or names.",
    }
    with tempfile.TemporaryDirectory() as folder:
        for table in TABLES:
            path = Path(folder) / f"{table}.jsonl.gz"
            _write_jsonl_gz(tables[table], path)
            try:
                digest = storage.put(table_key(config.pilot_id, table, day), path)
            except FileExistsError:
                if storage.exists(key):
                    return None  # finished by another process while this one ran
                raise
            manifest["tables"][table] = {"rows": len(tables[table]), "sha256": digest}
        manifest_path = Path(folder) / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True),
                                 encoding="utf-8")
        # The manifest goes last: a day counts as archived only when every table is in.
        try:
            storage.put(key, manifest_path)
        except FileExistsError:
            # Another process (the worker, or a manual run) finished this day first.
            return None
    return manifest


def first_day(session: Session, config: PilotConfig) -> date | None:
    first = session.scalar(select(func.min(FloodSourceFetch.retrieved_at))
                           .where(FloodSourceFetch.pilot_id == config.pilot_id))
    return utc(first).date() if first else None


def export_pending(session: Session, storage: LocalStorage, config: PilotConfig,
                   now: datetime | None = None) -> list[str]:
    """Archive every finished day not yet archived, oldest first. Returns the days written."""

    now = now or datetime.now(UTC)
    day = first_day(session, config)
    written = []
    while day is not None and day < now.astimezone(UTC).date():
        if export_day(session, storage, config, day, now) is not None:
            written.append(day.isoformat())
        day += timedelta(days=1)
    return written
