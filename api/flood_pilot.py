"""Flood pilot operator view: stored flood evidence for a configured pilot area (ADR-0038).

Read-only. The worker fetches and stores the sources; these routes only read what is stored,
so a slow or failed provider never slows a page. A pilot is open to members of its configured
Hubs (any role) and to Platform Admins; other Hubs are refused, and unknown pilots are not found.

Report text and links are never served: they can identify people. Floodboard's per-vehicle
verdict is served as ``provider_verdict`` and is labelled as Floodboard's estimate in the page.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, Response
from pydantic import BaseModel, Field

from api.ai_gateway import run_ai_call
from api.dependencies import DatabaseSession
from api.errors import GrpError, access_not_authorized, not_found, validation_failed
from api.langfuse import send_ai_call
from api.permissions import SignedInMember
from api.rate_limits import limiter, rate_limited
from api.sessions import CurrentPrincipal
from api.settings import get_settings
from core.access_models import AuditEvent, AuditResult
from core.flood_evidence.answer import (
    PROMPT_VERSION,
    build_prompt,
    computed_answer,
    gate,
    instructions_for,
)
from core.flood_evidence.areas import pilot_areas
from core.flood_evidence.briefing import build_facts, get_situation_changes
from core.flood_evidence.camera_relay import PROVIDER as RELAY_PROVIDER
from core.flood_evidence.camera_relay import (
    RelayBusy,
    RelayUnavailable,
    shared_relay,
    with_relay,
)
from core.flood_evidence.cameras import camera_registry, nearby_cameras
from core.flood_evidence.config import PILOT_IDS, PilotConfig, pilot_config
from core.flood_evidence.exposure import latest_exposure
from core.flood_evidence.feed import build_feed, serialise
from core.flood_evidence.incident_store import (
    REPORT_WINDOW_HOURS,
    incident_detail,
    list_incidents,
)
from core.flood_evidence.models import FloodReplay
from core.flood_evidence.replay import (
    ReplayRejected,
    advance,
    available_range,
    create_replay,
    find_replay,
    inject_outage,
    inject_report,
    is_replay_id,
    replay_config,
    restart,
    wipe,
)
from core.flood_evidence.replay import public as public_replay
from core.flood_evidence.reviews import (
    NOTE_MAX,
    ReviewRejected,
    history,
    review_facility,
    review_incident,
    reviewer_names,
)
from core.flood_evidence.situation import current_roads, recent_reports, road_by_id, situation
from core.flood_evidence.snapshot_relay import PROVIDERS as SNAPSHOT_PROVIDERS
from core.flood_evidence.snapshot_relay import shared_snapshot_relay
from core.flood_evidence.weather import latest_weather

router = APIRouter(prefix="/pilot/flood", tags=["pilot"])
# ADR-0052: the anonymous copy of the live feed, served only when FLOOD_FEED_PUBLIC is on.
public_router = APIRouter(prefix="/public/flood", tags=["pilot"])
ROAD_ID = re.compile(r"^[0-9a-f]{16}$")
DEFAULT_CAMERA_RADIUS_M = 400
FRAMES_PER_PERSON_PER_MINUTE = 150


def relay_for(config: PilotConfig):
    """The local demo relay's live view for bmatraffic cameras, when it is switched on."""

    if not get_settings().bmatraffic_relay_enabled:
        return None
    return lambda camera: with_relay(camera, config.pilot_id)


def may_open(principal: CurrentPrincipal, config: PilotConfig) -> bool:
    if principal.is_platform_admin:
        return True
    return any(member.hub_code.lower() in config.hubs for member in principal.memberships)


def flood_pilot(
    pilot_id: str, principal: SignedInMember, session: DatabaseSession
) -> PilotConfig:
    """A live pilot, or a replay namespace (ADR-0044) opened with its live pilot's access."""

    if is_replay_id(pilot_id):
        replay = find_replay(session, pilot_id)
        config = replay_config(replay) if replay is not None else None
    else:
        config = pilot_config(pilot_id)
    if config is None:
        raise not_found()
    if not may_open(principal, config):
        raise access_not_authorized()
    return config


def now_for(config: PilotConfig) -> datetime:
    """Wall time for live data; the processed replay clock for a replay."""

    return config.clock or datetime.now(UTC)


def refuse_replay_writes(config: PilotConfig) -> None:
    if config.is_replay:
        raise GrpError(409, "REPLAY_READ_ONLY",
                       "This is a replay. Nothing is recorded in a replay.")


FloodPilot = Annotated[PilotConfig, Depends(flood_pilot)]


def pilot_hub(principal: CurrentPrincipal, config: PilotConfig) -> UUID:
    """The pilot Hub an officer acts for. Writing needs a membership; a Platform Admin with no
    pilot-Hub membership can read but not record observations (ADR-0042)."""

    hubs = sorted(
        (m for m in principal.memberships if m.hub_code.lower() in config.hubs),
        key=lambda m: m.hub_code,
    )
    if not hubs:
        raise access_not_authorized()
    return hubs[0].hub_id


class IncidentReviewRequest(BaseModel):
    action: Literal["flooding_seen", "dry_seen", "cannot_tell"]
    camera_id: str | None = Field(default=None, max_length=120)
    note: str | None = Field(default=None, max_length=NOTE_MAX)


class FacilityAccessRequest(BaseModel):
    asset_id: str = Field(min_length=1, max_length=120)
    action: Literal["access_disrupted", "withdraw"]
    note: str | None = Field(default=None, max_length=NOTE_MAX)


def _audit(session, principal: CurrentPrincipal, hub_id: UUID, action: str, target_type: str,
           target_id: str, detail: dict[str, Any]) -> None:
    session.add(AuditEvent(actor_user_id=principal.user_id, actor_kind="person", hub_id=hub_id,
                           action=action, target_type=target_type, target_id=target_id,
                           new_value=detail, result=AuditResult.SUCCESS))


def _as_of(value: str | None, config: PilotConfig | None = None) -> datetime:
    """Now (or the replay clock), or an earlier moment. Anything later is refused."""

    now = now_for(config) if config is not None else datetime.now(UTC)
    if value is None:
        return now
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise validation_failed("as_of must be an ISO 8601 time") from error
    if moment.tzinfo is None:
        raise validation_failed("as_of needs a time zone")
    moment = moment.astimezone(UTC)
    if moment > now:
        raise validation_failed("as_of cannot be in the future")
    return moment


AsOf = Annotated[str | None, Query(description="ISO 8601 time with zone; default now")]


def _feed_response(session, config: PilotConfig, request: Request, cache: str) -> Response:
    body, etag = serialise(build_feed(session, config))
    headers = {"ETag": etag, "Cache-Control": cache}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=body, media_type="application/json", headers=headers)


@router.get(
    "/{pilot_id}/feed.json",
    summary="The live flood feed for Global Risk: open incidents and every district (ADR-0052)",
    openapi_extra={"x-grp-access": "protected"},
)
def read_flood_feed(
    pilot_id: str, principal: SignedInMember, session: DatabaseSession, request: Request
) -> Response:
    # A live pilot only: a replay ID never resolves here.
    config = pilot_config(pilot_id)
    if config is None:
        raise not_found()
    if not may_open(principal, config):
        raise access_not_authorized()
    return _feed_response(session, config, request, "private, max-age=60")


@public_router.get(
    "/{pilot_id}/feed.json",
    summary="The live flood feed, anonymous, for Global Risk to fetch (ADR-0052)",
    openapi_extra={"x-grp-access": "public"},
)
def read_public_flood_feed(pilot_id: str, session: DatabaseSession, request: Request) -> Response:
    # Fails closed: not found unless the deployment switches the public feed on.
    config = pilot_config(pilot_id) if get_settings().flood_feed_public else None
    if config is None:
        raise not_found()
    caller = request.client.host if request.client else "unknown"
    limiter.check("public_flood_feed_per_caller_per_minute", caller, 30, 60)
    return _feed_response(session, config, request, "public, max-age=60")


@router.get(
    "",
    summary="The flood pilots the signed-in person can open",
    openapi_extra={"x-grp-access": "protected"},
)
def list_flood_pilots(principal: SignedInMember) -> dict[str, Any]:
    pilots = []
    for pilot_id in PILOT_IDS:
        config = pilot_config(pilot_id)
        if config is not None and may_open(principal, config):
            pilots.append({"pilot_id": config.pilot_id, "title": config.title})
    return {"pilots": pilots}


@router.get(
    "/{pilot_id}",
    summary="A flood pilot's map settings, freshness bands and source registry",
    openapi_extra={"x-grp-access": "protected"},
)
def read_flood_pilot(config: FloodPilot) -> dict[str, Any]:
    return {
        "pilot_id": config.pilot_id,
        "title": config.title,
        "demo_corridor": config.demo_corridor,
        "map": config.map,
        "freshness_minutes": config.freshness_minutes,
        "report_window_hours": config.report_window_hours,
        "sources": [source.registry for source in config.sources],
    }


@router.get(
    "/{pilot_id}/situation",
    summary="Top cards and source health from stored flood evidence",
    openapi_extra={"x-grp-access": "protected"},
)
def read_situation(config: FloodPilot, session: DatabaseSession, as_of: AsOf = None) -> dict:
    return situation(session, config, _as_of(as_of, config))


@router.get(
    "/{pilot_id}/roads",
    summary="Road segments from the latest good snapshot, with freshness and evidence class",
    openapi_extra={"x-grp-access": "protected"},
)
def read_roads(
    config: FloodPilot,
    session: DatabaseSession,
    as_of: AsOf = None,
    include_all: Annotated[bool, Query(alias="all")] = False,
) -> dict[str, Any]:
    return current_roads(session, config, _as_of(as_of, config), include_all=include_all)


@router.get(
    "/{pilot_id}/reports",
    summary="Recent point reports, without text or links",
    openapi_extra={"x-grp-access": "protected"},
)
def read_reports(
    config: FloodPilot,
    session: DatabaseSession,
    as_of: AsOf = None,
    hours: Annotated[int | None, Query(ge=1)] = None,
) -> dict[str, Any]:
    window = hours or config.report_window_hours["default"]
    if window > config.report_window_hours["max"]:
        raise validation_failed("hours is longer than this pilot keeps reports for")
    return recent_reports(session, config, _as_of(as_of, config), window)


@router.get(
    "/{pilot_id}/areas",
    summary="Areas an operator can pick, with outlines (Bangkok and Nonthaburi)",
    openapi_extra={"x-grp-access": "protected"},
)
def read_areas(config: FloodPilot) -> dict[str, Any]:
    areas = pilot_areas(config)
    return {"areas": sorted(areas, key=lambda a: a["name"])}


@router.get(
    "/{pilot_id}/cameras",
    summary="The pilot's camera registry: location, health, access mode and official viewer",
    openapi_extra={"x-grp-access": "protected"},
)
def read_cameras(config: FloodPilot) -> dict[str, Any]:
    cameras = camera_registry(config.base_id)
    decorate = relay_for(config) or (lambda camera: camera)
    return {
        "cameras": [decorate(camera.public()) for camera in cameras],
        "placeholders_only": bool(cameras) and all(c.placeholder for c in cameras),
        "default_radius_m": DEFAULT_CAMERA_RADIUS_M,
    }


@router.get(
    "/{pilot_id}/roads/{road_id}/cameras",
    summary="Cameras near one road, nearest first, with every reason each cannot confirm it",
    openapi_extra={"x-grp-access": "protected"},
)
def read_road_cameras(
    config: FloodPilot,
    session: DatabaseSession,
    road_id: str,
    radius_m: Annotated[int, Query(ge=50, le=1000)] = DEFAULT_CAMERA_RADIUS_M,
    as_of: AsOf = None,
) -> dict[str, Any]:
    if not ROAD_ID.fullmatch(road_id):
        raise not_found()
    moment = _as_of(as_of, config)
    road = road_by_id(session, config, moment, road_id)
    if road is None:
        raise not_found()
    return {
        "road_id": road_id,
        "radius_m": radius_m,
        "cameras": nearby_cameras(
            camera_registry(config.base_id), road["geometry"], moment, radius_m,
            decorate=relay_for(config),
        ),
    }


@router.get(
    "/{pilot_id}/cameras/{camera_id}/frame.jpg",
    summary="The latest picture from one relayed camera (bmatraffic.com or Pak Kret)",
    openapi_extra={"x-grp-access": "protected"},
    response_class=Response,
)
def read_camera_frame(
    config: FloodPilot, principal: SignedInMember, camera_id: str
) -> Response:
    """ADR-0051 and ADR-0057: on demand, shared and cached for a second, never stored. Off
    unless enabled. Only registry cameras of a relayed provider; the address comes from the
    registry, never from the request."""

    if not get_settings().bmatraffic_relay_enabled:
        raise not_found()
    camera = next((c for c in camera_registry(config.base_id)
                   if c.camera_id == camera_id and not c.placeholder
                   and (c.provider == RELAY_PROVIDER
                        or (c.provider in SNAPSHOT_PROVIDERS and c.snapshot_url))), None)
    if camera is None:
        raise not_found()
    limiter.check("camera_frames_per_person_per_minute", str(principal.user_id),
                  FRAMES_PER_PERSON_PER_MINUTE, 60)
    try:
        if camera.provider in SNAPSHOT_PROVIDERS:
            frame = shared_snapshot_relay().frame(camera.camera_id, camera.snapshot_url)
        else:
            frame = shared_relay().frame(camera.provider_camera_id)
    except RelayBusy:
        raise rate_limited(retry_after=1) from None
    except (RelayUnavailable, ValueError):
        raise GrpError(502, "CAMERA_UNAVAILABLE",
                       "The camera site is not answering right now.") from None
    return Response(
        content=frame.body,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Retrieved-At": frame.retrieved_at.isoformat(timespec="seconds"),
        },
    )


@router.get(
    "/{pilot_id}/assets",
    summary="Schools, hospitals and clinics with exposure and access states from the latest roads",
    openapi_extra={"x-grp-access": "protected"},
)
def read_assets(config: FloodPilot, session: DatabaseSession, as_of: AsOf = None) -> dict:
    return latest_exposure(session, config, _as_of(as_of, config))


@router.get(
    "/{pilot_id}/incidents",
    summary="Open incidents in the demo area, in check-first order",
    openapi_extra={"x-grp-access": "protected"},
)
def read_incidents(config: FloodPilot, session: DatabaseSession) -> dict[str, Any]:
    return list_incidents(session, config, now_for(config))


@router.get(
    "/{pilot_id}/incidents/{incident_id}",
    summary="One incident: interpretation, change events, roads, reports, facilities, cameras",
    openapi_extra={"x-grp-access": "protected"},
)
def read_incident(
    config: FloodPilot, session: DatabaseSession, incident_id: UUID
) -> dict[str, Any]:
    detail = incident_detail(session, config, incident_id)
    if detail is None:
        raise not_found()
    now = now_for(config)
    keys = set(detail.get("road_keys") or [])
    roads = [f for f in current_roads(session, config, now, include_all=True)["features"]
             if f["properties"]["id"] in keys]
    wanted = set(detail.get("report_keys") or []) | set(detail.get("contrary_keys") or [])
    reports = [f for f in recent_reports(session, config, now, REPORT_WINDOW_HOURS)["features"]
               if f["properties"]["id"] in wanted]
    ids = set(detail.get("facility_ids") or [])
    facilities = [
        a for a in latest_exposure(session, config, now)["assets"] if a["asset_id"] in ids
    ]
    footprint = {
        "type": "MultiLineString",
        "coordinates": [
            line for f in roads for line in (
                f["geometry"]["coordinates"] if f["geometry"]["type"] == "MultiLineString"
                else [f["geometry"]["coordinates"]]
            )
        ],
    }
    cameras = (
        nearby_cameras(camera_registry(config.base_id), footprint, now, DEFAULT_CAMERA_RADIUS_M,
                       decorate=relay_for(config))
        if footprint["coordinates"] else []
    )
    weather = latest_weather(session, config)
    rain = next((w for w in weather["scopes"]
                 if w["kind"] == "incident" and w["id"] == str(incident_id)), None)
    return {**detail, "roads": roads, "reports": reports, "facilities": facilities,
            "cameras": cameras, "weather": {**{k: v for k, v in weather.items() if k != "scopes"},
                                            "scope": rain}}


@router.post(
    "/{pilot_id}/incidents/{incident_id}/reviews",
    summary="Record what an officer saw at an incident (time-bound human evidence)",
    openapi_extra={"x-grp-access": "protected"},
)
def post_incident_review(
    config: FloodPilot,
    principal: SignedInMember,
    session: DatabaseSession,
    incident_id: UUID,
    body: IncidentReviewRequest,
) -> dict[str, Any]:
    refuse_replay_writes(config)
    hub_id = pilot_hub(principal, config)
    now = now_for(config)
    try:
        review = review_incident(
            session, config, incident_id=incident_id, user_id=principal.user_id, hub_id=hub_id,
            action=body.action, camera_id=body.camera_id, note=body.note, now=now,
        )
    except LookupError as error:
        raise not_found() from error
    except ReviewRejected as error:
        raise validation_failed(str(error)) from error
    _audit(session, principal, hub_id, "flood_pilot.incident_review", "flood_incident",
           str(incident_id), {"action": body.action, "camera_id": body.camera_id,
                              "note_chars": len(review.note or ""), "pilot_id": config.pilot_id})
    session.commit()
    return read_incident(config, session, incident_id)


@router.post(
    "/{pilot_id}/facilities/access",
    summary="Confirm, or withdraw, that an officer saw a facility cut off",
    openapi_extra={"x-grp-access": "protected"},
)
def post_facility_access(
    config: FloodPilot,
    principal: SignedInMember,
    session: DatabaseSession,
    body: FacilityAccessRequest,
) -> dict[str, Any]:
    refuse_replay_writes(config)
    hub_id = pilot_hub(principal, config)
    now = now_for(config)
    try:
        review = review_facility(
            session, config, asset_id=body.asset_id, user_id=principal.user_id, hub_id=hub_id,
            action=body.action, note=body.note, now=now,
        )
    except LookupError as error:
        raise not_found() from error
    except ReviewRejected as error:
        raise validation_failed(str(error)) from error
    _audit(session, principal, hub_id, "flood_pilot.facility_access", "flood_facility",
           body.asset_id, {"action": body.action, "note_chars": len(review.note or ""),
                           "pilot_id": config.pilot_id})
    session.commit()
    facility = next(a for a in latest_exposure(session, config, now)["assets"]
                    if a["asset_id"] == body.asset_id)
    return {**facility, "reviews": history(
        session, config, "facility", body.asset_id, now,
        reviewer_names(session, config, "facility", body.asset_id),
    )}


Area = Annotated[str, Query(max_length=16, pattern=r"^(all|corridor|\d{4})$")]
SinceMinutes = Annotated[int, Query(ge=10, le=1440)]


def road_names(session, config: PilotConfig, now: datetime) -> dict[str, str]:
    names = {}
    for feature in current_roads(session, config, now)["features"]:
        p = feature["properties"]
        names[p["id"]] = p.get("name_en") or p.get("name") or ""
    return names


@router.get(
    "/{pilot_id}/changes",
    summary="What changed in an area over a window, from stored events and snapshots",
    openapi_extra={"x-grp-access": "protected"},
)
def read_changes(
    config: FloodPilot, session: DatabaseSession, area: Area = "corridor",
    since_minutes: SinceMinutes = 60,
) -> dict[str, Any]:
    now = now_for(config)
    try:
        return get_situation_changes(session, config, area, now - timedelta(minutes=since_minutes),
                                     now)
    except LookupError as error:
        raise validation_failed("Unknown area") from error


@router.get(
    "/{pilot_id}/facts",
    summary="The labelled facts an answer about an area may use (no AI)",
    openapi_extra={"x-grp-access": "protected"},
)
def read_facts(
    config: FloodPilot, session: DatabaseSession, area: Area = "corridor",
    since_minutes: SinceMinutes = 60,
) -> dict[str, Any]:
    now = now_for(config)
    try:
        return build_facts(session, config, area, now - timedelta(minutes=since_minutes), now,
                           road_names(session, config, now))
    except LookupError as error:
        raise validation_failed("Unknown area") from error


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=300)
    area: str = Field(default="corridor", max_length=16, pattern=r"^(all|corridor|\d{4})$")
    since_minutes: int = Field(default=60, ge=10, le=1440)
    lang: Literal["th", "en"] = "th"


# Tests replace this with a fake provider; it is never a different real provider.
PROVIDER_CALL = None


@router.post(
    "/{pilot_id}/ask",
    summary="Answer a question from computed facts; AI wording only when it passes the gate",
    openapi_extra={"x-grp-access": "protected"},
)
async def ask(
    config: FloodPilot,
    principal: SignedInMember,
    session: DatabaseSession,
    body: AskRequest,
    background: BackgroundTasks,
) -> dict[str, Any]:
    """The computed answer always comes back. AI wording is added only for a pilot-Hub member,
    within the AI allowance, and only when every claim is cited and every number is a fact."""

    now = now_for(config)
    try:
        since = now - timedelta(minutes=body.since_minutes)
        bundle = build_facts(session, config, body.area, since, now,
                             road_names(session, config, now))
    except LookupError as error:
        raise validation_failed("Unknown area") from error
    facts = bundle["facts"]
    result: dict[str, Any] = {
        "question": body.question,
        "lang": body.lang,
        "facts": facts,
        "labels": bundle["labels"],
        "computed": computed_answer(facts, body.lang),
        "ai": None,
        "withheld": None,
    }
    if config.is_replay:
        # No AI on simulated data: it would spend the allowance and send replayed evidence.
        result["withheld"] = {"reason": "replay", "problems": []}
        return result
    try:
        hub_id = pilot_hub(principal, config)
    except GrpError:
        result["withheld"] = {"reason": "not_a_pilot_member", "problems": []}
        return result
    hub_code = next(m.hub_code for m in principal.memberships if m.hub_id == hub_id)
    settings = get_settings()
    try:
        limiter.check("ai_requests_per_person_per_hour", str(principal.user_id),
                      settings.rate_limits["ai_requests_per_person_per_hour"], 3600)
        answer = await run_ai_call(
            session, settings, user_id=principal.user_id, hub_id=hub_id, hub_code=hub_code,
            instructions=instructions_for(body.lang), prompt=build_prompt(body.question, facts),
            prompt_version=PROMPT_VERSION, channel="web", provider_call=PROVIDER_CALL,
            export=lambda record: background.add_task(send_ai_call, settings, record),
        )
    except GrpError as error:
        result["withheld"] = {"reason": error.code, "problems": []}
        return result
    problems = gate(answer.text, facts, body.question)
    if problems:
        result["withheld"] = {"reason": "not_grounded", "problems": problems}
        return result
    result["ai"] = {"text": answer.text, "model": answer.model,
                    "label": "AI wording of the computed facts. Check the cited evidence."}
    return result


# --- Replays (ADR-0044) ---------------------------------------------------------------------


class ReplayRequest(BaseModel):
    start_at: datetime
    end_at: datetime


class AdvanceRequest(BaseModel):
    to: datetime | None = None
    by_minutes: int | None = Field(default=None, ge=1, le=720)


def _live_only(config: PilotConfig) -> None:
    if config.is_replay:
        raise not_found()


def _replay_of(session, config: PilotConfig, replay_id: str, *, lock: bool = False):
    replay = find_replay(session, replay_id, lock=lock)
    if replay is None or replay.base_pilot_id != config.pilot_id:
        raise not_found()
    return replay


def _when(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise validation_failed("Times need a time zone")
    return value.astimezone(UTC)


@router.get(
    "/{pilot_id}/replays",
    summary="Replays of this pilot and the period that can be replayed",
    openapi_extra={"x-grp-access": "protected"},
)
def list_replays(config: FloodPilot, session: DatabaseSession) -> dict[str, Any]:
    _live_only(config)
    from sqlalchemy import select as _select


    rows = session.scalars(_select(FloodReplay).where(FloodReplay.base_pilot_id == config.pilot_id)
                           .order_by(FloodReplay.created_at.desc()))
    return {"replays": [public_replay(r) for r in rows],
            "available": available_range(session, config)}


@router.post(
    "/{pilot_id}/replays",
    summary="Start building a replay of a stored period (pilot-Hub members)",
    openapi_extra={"x-grp-access": "protected"},
)
def post_replay(
    config: FloodPilot, principal: SignedInMember, session: DatabaseSession, body: ReplayRequest
) -> dict[str, Any]:
    _live_only(config)
    hub_id = pilot_hub(principal, config)
    try:
        replay = create_replay(session, config, start_at=_when(body.start_at),
                               end_at=_when(body.end_at), user_id=principal.user_id,
                               hub_id=hub_id, now=datetime.now(UTC))
    except ReplayRejected as error:
        raise validation_failed(str(error)) from error
    session.commit()
    return public_replay(replay)


@router.get(
    "/{pilot_id}/replays/{replay_id}",
    summary="One replay's progress and simulated clock",
    openapi_extra={"x-grp-access": "protected"},
)
def read_replay(config: FloodPilot, session: DatabaseSession, replay_id: str) -> dict[str, Any]:
    _live_only(config)
    return public_replay(_replay_of(session, config, replay_id))


@router.post(
    "/{pilot_id}/replays/{replay_id}/advance",
    summary="Move a replay's simulated time forward",
    openapi_extra={"x-grp-access": "protected"},
)
def post_advance(
    config: FloodPilot, principal: SignedInMember, session: DatabaseSession, replay_id: str,
    body: AdvanceRequest,
) -> dict[str, Any]:
    _live_only(config)
    pilot_hub(principal, config)
    replay = _replay_of(session, config, replay_id, lock=True)
    current = replay.processed_at or replay.start_at
    if body.to is not None:
        to = _when(body.to)
    elif body.by_minutes is not None:
        to = current.astimezone(UTC) + timedelta(minutes=body.by_minutes)
    else:
        raise validation_failed("Give a time or a number of minutes")
    try:
        advance(replay, to)
    except ReplayRejected as error:
        raise validation_failed(str(error)) from error
    session.commit()
    return public_replay(replay)


@router.post(
    "/{pilot_id}/replays/{replay_id}/restart",
    summary="Wipe a replay and build it again from its start",
    openapi_extra={"x-grp-access": "protected"},
)
def post_restart(
    config: FloodPilot, principal: SignedInMember, session: DatabaseSession, replay_id: str
) -> dict[str, Any]:
    _live_only(config)
    pilot_hub(principal, config)
    replay = _replay_of(session, config, replay_id, lock=True)
    restart(session, replay)
    session.commit()
    return public_replay(replay)


@router.delete(
    "/{pilot_id}/replays/{replay_id}",
    summary="Delete a replay and everything in its namespace",
    openapi_extra={"x-grp-access": "protected"},
)
def delete_replay(
    config: FloodPilot, principal: SignedInMember, session: DatabaseSession, replay_id: str
) -> dict[str, Any]:
    _live_only(config)
    pilot_hub(principal, config)
    replay = _replay_of(session, config, replay_id, lock=True)
    wipe(session, replay.replay_pilot_id)
    session.delete(replay)
    session.commit()
    return {"deleted": replay_id}


class InjectReportRequest(BaseModel):
    at: datetime
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    source: Literal["traffy", "crowd", "bma_sensor"] = "crowd"
    depth_cm: float | None = Field(default=None, ge=0, le=300)
    cleared: bool = False


class InjectOutageRequest(BaseModel):
    source_id: str = Field(min_length=1, max_length=64)
    start: datetime
    end: datetime


@router.post(
    "/{pilot_id}/replays/{replay_id}/inject-report",
    summary="Add a made-up report to a replay, labelled synthetic (scenario testing)",
    openapi_extra={"x-grp-access": "protected"},
)
def post_inject_report(
    config: FloodPilot, principal: SignedInMember, session: DatabaseSession, replay_id: str,
    body: InjectReportRequest,
) -> dict[str, Any]:
    _live_only(config)
    pilot_hub(principal, config)
    replay = _replay_of(session, config, replay_id, lock=True)
    try:
        inject_report(replay, at=_when(body.at), lat=body.lat, lon=body.lon, source=body.source,
                      depth_cm=body.depth_cm, cleared=body.cleared)
    except ReplayRejected as error:
        raise validation_failed(str(error)) from error
    session.commit()
    return public_replay(replay)


@router.post(
    "/{pilot_id}/replays/{replay_id}/inject-outage",
    summary="Make one source fail for a window of a replay (scenario F)",
    openapi_extra={"x-grp-access": "protected"},
)
def post_inject_outage(
    config: FloodPilot, principal: SignedInMember, session: DatabaseSession, replay_id: str,
    body: InjectOutageRequest,
) -> dict[str, Any]:
    _live_only(config)
    pilot_hub(principal, config)
    replay = _replay_of(session, config, replay_id, lock=True)
    try:
        inject_outage(replay, config, source_id=body.source_id, start=_when(body.start),
                      end=_when(body.end))
    except ReplayRejected as error:
        raise validation_failed(str(error)) from error
    session.commit()
    return public_replay(replay)


@router.get(
    "/{pilot_id}/weather",
    summary="Rain now and the next 30 minutes per district and top incident (context only)",
    openapi_extra={"x-grp-access": "protected"},
)
def read_weather(config: FloodPilot, session: DatabaseSession) -> dict[str, Any]:
    return latest_weather(session, config)
