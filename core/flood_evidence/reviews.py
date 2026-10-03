"""Officer reviews: what a person saw at an incident or a facility (ADR-0042).

A review is human evidence with a time, kept apart from what the evidence engine computed:

- an incident review (``flooding_seen``, ``dry_seen``, ``cannot_tell``) applies only while it is
  younger than ``VALID_FOR`` and while the incident still contains a road the officer reviewed;
- a facility review (``access_disrupted``) sets ``access_disrupted_confirmed`` until it expires
  or is withdrawn. GRP never records the opposite ("accessible");
- a camera named in a review must be a real registered camera with a viewer, never a placeholder.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.access_models import AppUser
from core.flood_evidence.assets import asset_registry
from core.flood_evidence.cameras import VIEWER_MODES, camera_registry
from core.flood_evidence.config import PilotConfig
from core.flood_evidence.ingest import utc
from core.flood_evidence.models import FloodIncident, FloodIncidentEvent, FloodReview

VALID_FOR = timedelta(hours=3)
NOTE_MAX = 500
INCIDENT_ACTIONS = ("flooding_seen", "dry_seen", "cannot_tell")
FACILITY_ACTIONS = ("access_disrupted", "withdraw")
VERIFICATION = {
    "flooding_seen": "officer_saw_flooding",
    "dry_seen": "officer_saw_dry",
    "cannot_tell": "officer_could_not_tell",
}


class ReviewRejected(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _clean_note(note: str | None) -> str | None:
    if note is None:
        return None
    note = note.strip()
    if len(note) > NOTE_MAX:
        raise ReviewRejected("note_too_long", f"A note can be at most {NOTE_MAX} characters")
    return note or None


def _check_camera(config: PilotConfig, camera_id: str | None) -> None:
    if camera_id is None:
        return
    camera = next((c for c in camera_registry(config.pilot_id) if c.camera_id == camera_id), None)
    if camera is None or camera.placeholder or camera.access_mode not in VIEWER_MODES:
        raise ReviewRejected("camera_not_usable", "That camera cannot be looked through")


def review_incident(
    session: Session,
    config: PilotConfig,
    *,
    incident_id: UUID,
    user_id: UUID,
    hub_id: UUID,
    action: str,
    camera_id: str | None,
    note: str | None,
    now: datetime,
) -> FloodReview:
    if action not in INCIDENT_ACTIONS:
        raise ReviewRejected("unknown_action", "Unknown review action")
    incident = session.get(FloodIncident, incident_id)
    if incident is None or incident.pilot_id != config.pilot_id:
        raise LookupError(incident_id)
    if incident.status == "closed":
        raise ReviewRejected("incident_closed", "This incident is closed")
    _check_camera(config, camera_id)
    review = FloodReview(
        pilot_id=config.pilot_id, hub_id=hub_id, user_id=user_id, target_kind="incident",
        target_id=str(incident.id), action=action, camera_id=camera_id, note=_clean_note(note),
        road_keys=list(incident.road_keys), created_at=now, expires_at=now + VALID_FOR,
    )
    session.add(review)
    session.add(FloodIncidentEvent(pilot_id=config.pilot_id, incident_id=incident.id, at=now,
                                   kind="officer_review",
                                   detail={"action": action, "camera_id": camera_id}))
    session.flush()
    return review


def review_facility(
    session: Session,
    config: PilotConfig,
    *,
    asset_id: str,
    user_id: UUID,
    hub_id: UUID,
    action: str,
    note: str | None,
    now: datetime,
) -> FloodReview:
    if action not in FACILITY_ACTIONS:
        raise ReviewRejected("unknown_action", "Unknown access action")
    assets, _ = asset_registry(config.pilot_id)
    if not any(a.asset_id == asset_id for a in assets):
        raise LookupError(asset_id)
    if action == "withdraw":
        for active in _active(session, config, "facility", now, target_id=asset_id):
            active.withdrawn_at = now
    review = FloodReview(
        pilot_id=config.pilot_id, hub_id=hub_id, user_id=user_id, target_kind="facility",
        target_id=asset_id, action=action, camera_id=None, note=_clean_note(note), road_keys=[],
        created_at=now, expires_at=now + VALID_FOR,
        withdrawn_at=now if action == "withdraw" else None,
    )
    session.add(review)
    session.flush()
    return review


def _active(
    session: Session, config: PilotConfig, kind: str, now: datetime, target_id: str | None = None
) -> list[FloodReview]:
    query = select(FloodReview).where(
        FloodReview.pilot_id == config.pilot_id,
        FloodReview.target_kind == kind,
        FloodReview.expires_at > now,
        FloodReview.withdrawn_at.is_(None),
    )
    if target_id is not None:
        query = query.where(FloodReview.target_id == target_id)
    return list(session.scalars(query.order_by(FloodReview.created_at.desc())))


def public_review(review: FloodReview, now: datetime, names: dict[UUID, str]) -> dict[str, Any]:
    expired = utc(review.expires_at) <= now
    return {
        "review_id": str(review.id),
        "action": review.action,
        "camera_id": review.camera_id,
        "note": review.note,
        "by": names.get(review.user_id, "Officer"),
        "at": utc(review.created_at).isoformat(),
        "expires_at": utc(review.expires_at).isoformat(),
        "current": not expired and review.withdrawn_at is None,
        "withdrawn_at": utc(review.withdrawn_at).isoformat() if review.withdrawn_at else None,
    }


def incident_verification(
    session: Session, config: PilotConfig, incidents: list[FloodIncident], now: datetime
) -> dict[str, dict[str, Any]]:
    """The current officer review per incident, if one still applies to its roads."""

    by_target: dict[str, FloodReview] = {}
    for review in _active(session, config, "incident", now):
        by_target.setdefault(review.target_id, review)  # newest first
    out = {}
    for incident in incidents:
        review = by_target.get(str(incident.id))
        if review is not None and set(review.road_keys) & set(incident.road_keys):
            out[str(incident.id)] = {
                "verification": VERIFICATION[review.action],
                "verified_at": utc(review.created_at).isoformat(),
                "verified_until": utc(review.expires_at).isoformat(),
            }
    return out


def facility_overrides(session: Session, config: PilotConfig, now: datetime) -> dict[str, dict]:
    """Facilities an officer confirmed as cut off, while that confirmation holds."""

    out: dict[str, dict] = {}
    for review in _active(session, config, "facility", now):
        if review.action == "access_disrupted" and review.target_id not in out:
            out[review.target_id] = {
                "confirmed_at": utc(review.created_at).isoformat(),
                "confirmed_until": utc(review.expires_at).isoformat(),
            }
    return out


def reviewer_names(
    session: Session, config: PilotConfig, kind: str, target_id: str
) -> dict[UUID, str]:
    """Display names of the officers who reviewed one target, for accountability."""

    rows = session.execute(
        select(AppUser.id, AppUser.display_name, AppUser.email)
        .join(FloodReview, FloodReview.user_id == AppUser.id)
        .where(FloodReview.pilot_id == config.pilot_id, FloodReview.target_kind == kind,
               FloodReview.target_id == target_id)
    )
    return {user_id: (name or email) for user_id, name, email in rows}


def history(
    session: Session, config: PilotConfig, kind: str, target_id: str, now: datetime,
    names: dict[UUID, str],
) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(FloodReview)
        .where(FloodReview.pilot_id == config.pilot_id, FloodReview.target_kind == kind,
               FloodReview.target_id == target_id)
        .order_by(FloodReview.created_at.desc())
        .limit(20)
    )
    return [public_review(r, now, names) for r in rows]
