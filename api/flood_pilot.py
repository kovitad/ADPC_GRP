"""Flood pilot operator view: stored flood evidence for a configured pilot area (ADR-0038).

Read-only. The worker fetches and stores the sources; these routes only read what is stored,
so a slow or failed provider never slows a page. A pilot is open to members of its configured
Hubs (any role) and to Platform Admins; other Hubs are refused, and unknown pilots are not found.

Report text and links are never served: they can identify people. Floodboard's per-vehicle
verdict is served as ``provider_verdict`` and is labelled as Floodboard's estimate in the page.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from api.dependencies import DatabaseSession
from api.errors import access_not_authorized, not_found, validation_failed
from api.permissions import SignedInMember
from api.sessions import CurrentPrincipal
from core.flood_evidence.cameras import camera_registry, nearby_cameras
from core.flood_evidence.config import PILOT_IDS, PilotConfig, pilot_config
from core.flood_evidence.situation import current_roads, recent_reports, road_by_id, situation
from core.river_watch import bangkok_outlines

router = APIRouter(prefix="/pilot/flood", tags=["pilot"])
ROAD_ID = re.compile(r"^[0-9a-f]{16}$")
DEFAULT_CAMERA_RADIUS_M = 400


def may_open(principal: CurrentPrincipal, config: PilotConfig) -> bool:
    if principal.is_platform_admin:
        return True
    return any(member.hub_code.lower() in config.hubs for member in principal.memberships)


def flood_pilot(pilot_id: str, principal: SignedInMember) -> PilotConfig:
    config = pilot_config(pilot_id)
    if config is None:
        raise not_found()
    if not may_open(principal, config):
        raise access_not_authorized()
    return config


FloodPilot = Annotated[PilotConfig, Depends(flood_pilot)]


def _as_of(value: str | None) -> datetime:
    """Now, or an earlier moment to look back at. The future is refused."""

    now = datetime.now(UTC)
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
    return situation(session, config, _as_of(as_of))


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
    return current_roads(session, config, _as_of(as_of), include_all=include_all)


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
    return recent_reports(session, config, _as_of(as_of), window)


@router.get(
    "/{pilot_id}/areas",
    summary="Areas an operator can pick, with outlines (Bangkok's 50 districts)",
    openapi_extra={"x-grp-access": "protected"},
)
def read_areas(config: FloodPilot) -> dict[str, Any]:
    areas = bangkok_outlines() if config.pilot_id == "bangkok" else []
    return {"areas": sorted(areas, key=lambda a: a["name"])}


@router.get(
    "/{pilot_id}/cameras",
    summary="The pilot's camera registry: location, health, access mode and official viewer",
    openapi_extra={"x-grp-access": "protected"},
)
def read_cameras(config: FloodPilot) -> dict[str, Any]:
    cameras = camera_registry(config.pilot_id)
    return {
        "cameras": [camera.public() for camera in cameras],
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
    moment = _as_of(as_of)
    road = road_by_id(session, config, moment, road_id)
    if road is None:
        raise not_found()
    return {
        "road_id": road_id,
        "radius_m": radius_m,
        "cameras": nearby_cameras(
            camera_registry(config.pilot_id), road["geometry"], moment, radius_m
        ),
    }
