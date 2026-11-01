"""Coastal-zoning lifecycle and API-side delegated MCP coordination (ADR-0070)."""

from __future__ import annotations

import json
import secrets
import tempfile
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.dependencies import DatabaseSession
from api.errors import GrpError, new_support_ref, not_found, validation_failed
from api.mcp_client import SigMcpClient, SigMcpError
from api.permissions import SignedInMember
from api.planning_access import planner_membership
from api.sessions import CurrentPrincipal
from api.settings import get_settings
from api.sig_connection import sig_access_token
from core.access_models import AuditEvent, AuditResult, MembershipRole, utc_now
from core.coastal_zoning.aoi import LOCAL_MAX_KM2, AoiValidationError, plan_aoi
from core.coastal_zoning.jobs import (
    ZoningTransitionError,
    new_run_steps,
    request_cancellation,
    retry_failed_run,
)
from core.coastal_zoning.models import (
    CoastalZoningArtifact,
    CoastalZoningReviewLog,
    CoastalZoningRun,
    CoastalZoningStep,
    CoastalZoningZone,
    ZoningReviewState,
    ZoningRunState,
)
from core.coastal_zoning.rules import STARTER_RULES_SHA256
from core.storage import LocalStorage
from core.validation import canonical_sha256

router = APIRouter(prefix="/coastal-zoning", tags=["coastal-zoning"])

ZONING_MCP_TOOLS = frozenset(
    {"assemble_pack", "publish_answer", "resolve_place_time", "platform_capabilities"}
)
KENYA_LAYERS = (
    "landcover_ke_gmw_v3_2class_ke_coast_1996",
    "landcover_ke_gmw_v3_2class_ke_coast_2020",
    "measure_ke_lamu_copdem30_elevation",
    "landcover_ke_gwl_fcs30d_ke_coast_2022",
    "landcover_ke_worldcover_lamu_2021",
    "population_ke_lamu_worldpop_2020",
)
SOUTH_SUMATRA_LAYERS = (
    "landcover_mangrove_indonesia_2017",
    "landcover_mangrove_indonesia_2024",
    "landcover_south_sumatra_landforms_2026",
    "measure_south_sumatra_dem",
    "population_south_sumatra_worldpop_2020",
    "hazard_flood",
    "hazard_fire",
)


class AoiFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: dict[str, object]
    properties: dict[str, object] = Field(default_factory=dict)


class CoverageRequest(BaseModel):
    hub_code: str = Field(min_length=2, max_length=64)
    aoi: AoiFeature
    country: str | None = Field(default=None, min_length=2, max_length=2)


class ZoneReviewEdit(BaseModel):
    zone_id: str = Field(min_length=1, max_length=16)
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=2_000)


class ZoningReviewSubmit(BaseModel):
    zones: list[ZoneReviewEdit] = Field(default_factory=list, max_length=50)


class ZoningRunSubmit(BaseModel):
    hub_code: str = Field(min_length=2, max_length=64)
    coverage_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    aoi: AoiFeature
    site_name: str = Field(min_length=1, max_length=200)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    params: dict[str, int | float | bool] = Field(default_factory=dict)
    language: Literal["en"] = "en"


def _available() -> None:
    if not get_settings().coastal_zoning_enabled:
        raise not_found()


def _visible_run(session: Session, principal: CurrentPrincipal, run_id: UUID) -> CoastalZoningRun:
    run = session.get(CoastalZoningRun, run_id)
    if run is None:
        raise not_found()
    if principal.is_platform_admin:
        return run
    hubs = {membership.hub_id for membership in principal.memberships}
    if run.hub_id not in hubs:
        raise not_found()
    return run


def _may_change(principal: CurrentPrincipal, run: CoastalZoningRun) -> bool:
    if principal.is_platform_admin or run.owner_id == principal.user_id:
        return True
    return _may_review(principal, run)


def _may_review(principal: CurrentPrincipal, run: CoastalZoningRun) -> bool:
    return principal.is_platform_admin or any(
        membership.hub_id == run.hub_id and membership.role == MembershipRole.ADMIN
        for membership in principal.memberships
    )


def _aoi_plan(aoi: AoiFeature):
    try:
        return plan_aoi(aoi.geometry)
    except AoiValidationError as error:
        raise validation_failed(str(error)) from error


def _evidence_profile(country: str | None, bbox: tuple[float, float, float, float]):
    code = (country or "").upper()
    west, south, east, north = bbox
    if code == "KE" and east >= 40.76 and west <= 41.0 and north >= -2.34 and south <= -2.07:
        return "lamu", 2020, list(KENYA_LAYERS), "no_hazard"
    if code == "ID" and east >= 104.6 and west <= 106.1 and north >= -3.7 and south <= -1.6:
        return "south_sumatra", 2024, list(SOUTH_SUMATRA_LAYERS), "hazard"
    raise GrpError(
        422,
        "UNSUPPORTED_AREA",
        "Live Mangrove 360 inputs currently cover the Lamu coast in Kenya and "
        "South Sumatra in Indonesia.",
    )


def _run_payload(run: CoastalZoningRun, steps: list[CoastalZoningStep]) -> dict[str, object]:
    return {
        "run_id": str(run.id),
        "status": run.status,
        "hub_id": str(run.hub_id),
        "owner_id": str(run.owner_id),
        "site_name": run.site_name,
        "country": run.country,
        "profile": run.profile,
        "scale": run.scale,
        "params": run.params,
        "review_state": run.review_state,
        "versions": run.versions,
        "lead": run.lead,
        "error": run.error,
        "cancellation_requested": run.cancellation_requested,
        "attempt": run.attempt,
        "support_ref": run.support_ref,
        "trace_id": run.trace_id,
        "created_at": run.created_at.isoformat(),
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "steps": [
            {
                "key": step.step_key,
                "label": step.label,
                "status": step.status,
                "attempts": step.attempts,
                "done": step.done,
                "total": step.total,
                "duration_ms": step.duration_ms,
                "summary": step.summary,
            }
            for step in steps
        ],
    }


def _audit(
    session: Session,
    principal: CurrentPrincipal,
    run: CoastalZoningRun,
    action: str,
    value: dict[str, object],
) -> None:
    session.add(
        AuditEvent(
            actor_user_id=principal.user_id,
            actor_kind="person",
            hub_id=run.hub_id,
            action=action,
            target_type="coastal_zoning_run",
            target_id=str(run.id),
            new_value=value,
            result=AuditResult.SUCCESS,
            support_ref=run.support_ref,
        )
    )


def _store_coverage(
    *,
    settings,
    coverage_id: str,
    principal: CurrentPrincipal,
    hub_id: UUID,
    geometry_sha256: str,
    evidence: dict[str, object],
) -> tuple[str, str, int]:
    key = f"coastal-zoning/coverage/{coverage_id}.json"
    document = {
        "owner_id": str(principal.user_id),
        "hub_id": str(hub_id),
        "geometry_sha256": geometry_sha256,
        "evidence": evidence,
    }
    encoded = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(encoded)
    try:
        digest = LocalStorage(settings.storage_root).put(key, temporary)
    finally:
        temporary.unlink(missing_ok=True)
    return key, digest, len(encoded)


def _coverage_record(
    settings,
    coverage_id: str,
    principal: CurrentPrincipal,
    hub_id: UUID,
    geometry_sha256: str,
) -> tuple[str, dict[str, object], str, int]:
    key = f"coastal-zoning/coverage/{coverage_id}.json"
    storage = LocalStorage(settings.storage_root)
    try:
        document = json.loads(storage.read_bytes(key))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise GrpError(422, "COVERAGE_EXPIRED", "Check this area's coverage again.") from error
    if (
        document.get("owner_id") != str(principal.user_id)
        or document.get("hub_id") != str(hub_id)
        or document.get("geometry_sha256") != geometry_sha256
        or not isinstance(document.get("evidence"), dict)
    ):
        raise GrpError(422, "COVERAGE_MISMATCH", "Check this area's coverage again.")
    return key, document["evidence"], storage.sha256(key), len(storage.read_bytes(key))


@router.post(
    "/coverage",
    summary="Validate an AOI and inspect live coastal evidence coverage",
    openapi_extra={"x-grp-access": "protected"},
)
async def coastal_zoning_coverage(
    payload: CoverageRequest, principal: SignedInMember
) -> dict[str, object]:
    """Perform bounded geometry planning and one delegated, read-only evidence-pack call."""

    _available()
    hub = planner_membership(principal, payload.hub_code)
    plan = _aoi_plan(payload.aoi)
    if plan.area_km2 > LOCAL_MAX_KM2:
        raise GrpError(
            422,
            "AOI_TOO_LARGE",
            f"This first release accepts coastal areas up to {LOCAL_MAX_KM2:,.0f} km².",
        )
    if plan.estimated_tiles > 400:
        raise GrpError(
            422,
            "TOO_MANY_TILES",
            "This area would require too many evidence tiles. Draw a smaller coastal area.",
        )
    profile_id, year, required_layers, zoning_profile = _evidence_profile(
        payload.country, plan.bbox
    )
    settings = get_settings()
    access_token = await sig_access_token(settings, principal.session_id)
    if not access_token:
        raise GrpError(
            401,
            "SIG_REAUTH_REQUIRED",
            "Sign in with SERVIR again to check Global Risk evidence.",
        )
    arguments: dict[str, object] = {
        "pack": "land-cover",
        "focus": "Mangrove coastal zoning input coverage",
        "geometry": plan.geometry,
        "year": year,
        "layers": required_layers,
    }
    if payload.country:
        arguments["override_country"] = payload.country.upper()
    try:
        async with SigMcpClient(settings.sig_mcp_base_url, access_token) as mcp:
            result = await mcp.call_tool("assemble_pack", arguments)
    except SigMcpError as error:
        raise GrpError(
            503,
            "SIG_UNAVAILABLE",
            "Global Risk could not check this area's evidence right now.",
        ) from error
    evidence = result.structured_content
    status = str(evidence.get("status", "error"))
    if result.is_error or status not in {"ok", "incomplete"}:
        raise GrpError(
            422,
            "COVERAGE_UNAVAILABLE",
            str(evidence.get("note") or "No governed land-cover evidence covers this area."),
        )
    layers = evidence.get("layers")
    gaps = evidence.get("gaps") or evidence.get("declared_gaps") or []
    present = set(layers) if isinstance(layers, dict) else set()
    missing = sorted(set(required_layers) - present)
    if missing:
        raise GrpError(
            422,
            "INPUT_LAYER_MISSING",
            "Required governed layers are missing: " + ", ".join(missing),
        )
    evidence["_coastal_zoning"] = {
        "profile_id": profile_id,
        "zoning_profile": zoning_profile,
        "geometry": plan.geometry,
        "bbox": list(plan.bbox),
        "area_km2": plan.area_km2,
    }
    coverage_id = secrets.token_hex(16)
    geometry_sha256 = canonical_sha256(plan.geometry)
    _store_coverage(
        settings=settings,
        coverage_id=coverage_id,
        principal=principal,
        hub_id=hub.hub_id,
        geometry_sha256=geometry_sha256,
        evidence=evidence,
    )
    return {
        "hub_code": hub.hub_code,
        "geometry": plan.geometry,
        "bbox": list(plan.bbox),
        "area_km2": plan.area_km2,
        "vertices": plan.vertices,
        "scale": plan.scale,
        "estimated_tiles": plan.estimated_tiles,
        "profile": zoning_profile,
        "country": payload.country.upper() if payload.country else None,
        "defaults": {
            "reserve_m": 100,
            "mangrove_buffer_m": 100,
            "coast_band_m": 1_000,
            "inland": False,
        },
        "coverage_id": coverage_id,
        "profile_id": profile_id,
        "pack_id": evidence.get("pack_id"),
        "gaps": gaps if isinstance(gaps, list) else [],
        "layer_names": sorted(layers) if isinstance(layers, dict) else [],
        "ready": bool(evidence.get("pack_id")) and not missing,
        "trace_id": f"cz-coverage-{secrets.token_hex(12)}",
    }


@router.get(
    "/capabilities",
    summary="MCP contracts available to a coastal-zoning run",
    openapi_extra={"x-grp-access": "protected"},
)
async def coastal_zoning_capabilities(
    principal: SignedInMember, hub_code: str | None = None
) -> dict[str, Any]:
    """Return allow-listed tool schemas using this person's existing SIG login."""

    _available()
    hub = planner_membership(principal, hub_code)
    settings = get_settings()
    access_token = await sig_access_token(settings, principal.session_id)
    if not access_token:
        raise GrpError(
            401,
            "SIG_REAUTH_REQUIRED",
            "Sign in with SERVIR again to connect to Global Risk evidence.",
        )
    try:
        async with SigMcpClient(settings.sig_mcp_base_url, access_token) as mcp:
            advertised = await mcp.list_tools()
    except SigMcpError as error:
        raise GrpError(
            503,
            "SIG_UNAVAILABLE",
            "Global Risk capabilities are not available right now.",
        ) from error
    tools = [
        {"name": tool.name, "description": tool.description, "input_schema": tool.input_schema}
        for tool in advertised
        if tool.name in ZONING_MCP_TOOLS
    ]
    present = {tool["name"] for tool in tools}
    return {
        "hub_code": hub.hub_code,
        "authentication": "delegated_user_mcp",
        "token_persisted": False,
        "worker_receives_token": False,
        "ready": {"assemble_pack", "publish_answer"}.issubset(present),
        "missing": sorted(ZONING_MCP_TOOLS - present),
        "tools": tools,
    }


@router.post(
    "/runs",
    summary="Queue a coastal-zoning run",
    status_code=202,
    openapi_extra={"x-grp-access": "protected"},
)
def create_coastal_zoning_run(
    payload: ZoningRunSubmit,
    principal: SignedInMember,
    session: DatabaseSession,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=128),
) -> JSONResponse:
    _available()
    hub = planner_membership(principal, payload.hub_code)
    if not idempotency_key or len(idempotency_key.strip()) < 8:
        raise validation_failed("An Idempotency-Key header of at least 8 characters is required.")
    key = idempotency_key.strip()
    plan = _aoi_plan(payload.aoi)
    if plan.area_km2 > LOCAL_MAX_KM2 or plan.estimated_tiles > 400:
        raise GrpError(
            422,
            "AOI_TOO_LARGE",
            "Draw a smaller coastal area and check its coverage before running the assessment.",
        )
    geometry = plan.geometry
    request_sha = canonical_sha256(payload.model_dump(mode="json"))
    existing = session.scalar(
        select(CoastalZoningRun).where(
            CoastalZoningRun.owner_id == principal.user_id,
            CoastalZoningRun.hub_id == hub.hub_id,
            CoastalZoningRun.idempotency_key == key,
        )
    )
    if existing is not None:
        if existing.request_sha256 != request_sha:
            raise GrpError(
                409, "IDEMPOTENCY_CONFLICT", "This request was already sent with different details."
            )
        return _accepted(existing)
    source = str(payload.aoi.properties.get("source", "drawn"))
    if source not in {"place", "drawn", "upload"}:
        raise validation_failed("The area source must be place, drawn, or upload.")
    coverage: tuple[str, dict[str, object], str, int] | None = None
    if payload.coverage_id:
        coverage = _coverage_record(
            get_settings(),
            payload.coverage_id,
            principal,
            hub.hub_id,
            canonical_sha256(geometry),
        )
    coverage_meta = coverage[1].get("_coastal_zoning", {}) if coverage is not None else {}
    profile = str(coverage_meta.get("zoning_profile", "no_hazard"))
    run = CoastalZoningRun(
        hub_id=hub.hub_id,
        owner_id=principal.user_id,
        idempotency_key=key,
        request_sha256=request_sha,
        site_name=payload.site_name.strip(),
        country=payload.country.upper() if payload.country else None,
        aoi_geojson={"type": "Feature", "geometry": geometry, "properties": payload.aoi.properties},
        aoi_source=source,
        aoi_sha256=canonical_sha256(geometry),
        profile=profile,
        scale=plan.scale,
        params=[
            {"name": name, "value": value, "source": "adjusted"}
            for name, value in sorted(payload.params.items())
        ],
        status=ZoningRunState.QUEUED,
        review_state="draft",
        versions={
            "rules_sha256": STARTER_RULES_SHA256,
            "pipeline": "p1-p10-v1",
            "mcp_authentication": "delegated_user_mcp",
        },
        trace_id=f"cz-{secrets.token_hex(16)}",
        support_ref=new_support_ref(),
    )
    session.add(run)
    session.flush()
    session.add_all(new_run_steps(run.id))
    if coverage is not None:
        key, _evidence, digest, size = coverage
        session.add(
            CoastalZoningArtifact(
                run_id=run.id,
                kind="coverage_pack",
                storage_key=key,
                media_type="application/json",
                bytes=size,
                sha256=digest,
            )
        )
    _audit(session, principal, run, "coastal_zoning_submitted", {"site_name": run.site_name})
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        winner = session.scalar(
            select(CoastalZoningRun).where(
                CoastalZoningRun.owner_id == principal.user_id,
                CoastalZoningRun.hub_id == hub.hub_id,
                CoastalZoningRun.idempotency_key == key,
            )
        )
        if winner is None or winner.request_sha256 != request_sha:
            raise GrpError(
                409, "IDEMPOTENCY_CONFLICT", "The idempotency key is already in use."
            ) from error
        run = winner
    return _accepted(run)


def _accepted(run: CoastalZoningRun) -> JSONResponse:
    return JSONResponse(
        status_code=202,
        headers={
            "Location": f"/api/v1/coastal-zoning/runs/{run.id}",
            "Retry-After": "3",
        },
        content={
            "run_id": str(run.id),
            "status": run.status,
            "support_ref": run.support_ref,
            "trace_id": run.trace_id,
        },
    )


@router.get(
    "/runs",
    summary="List visible coastal-zoning runs",
    openapi_extra={"x-grp-access": "protected"},
)
def list_coastal_zoning_runs(
    principal: SignedInMember,
    session: DatabaseSession,
    hub_code: str | None = Query(default=None, max_length=64),
) -> dict[str, object]:
    _available()
    if principal.is_platform_admin and hub_code is None:
        statement = select(CoastalZoningRun)
    else:
        hub = planner_membership(principal, hub_code)
        statement = select(CoastalZoningRun).where(CoastalZoningRun.hub_id == hub.hub_id)
    runs = session.scalars(statement.order_by(CoastalZoningRun.created_at.desc()).limit(100)).all()
    return {
        "runs": [
            {
                "run_id": str(run.id),
                "site_name": run.site_name,
                "status": run.status,
                "review_state": run.review_state,
                "owner_id": str(run.owner_id),
                "trace_id": run.trace_id,
                "created_at": run.created_at.isoformat(),
            }
            for run in runs
            if run.status != ZoningRunState.RETIRED
        ]
    }


@router.get(
    "/runs/{run_id}",
    summary="Read coastal-zoning run status",
    openapi_extra={"x-grp-access": "protected"},
)
def read_coastal_zoning_run(
    run_id: UUID, principal: SignedInMember, session: DatabaseSession
) -> dict[str, object]:
    _available()
    run = _visible_run(session, principal, run_id)
    steps = session.scalars(
        select(CoastalZoningStep)
        .where(CoastalZoningStep.run_id == run.id)
        .order_by(CoastalZoningStep.sequence)
    ).all()
    return _run_payload(run, steps)


@router.get(
    "/runs/{run_id}/result",
    summary="Read a completed coastal-zoning map-grid result",
    openapi_extra={"x-grp-access": "protected"},
)
def read_coastal_zoning_result(
    run_id: UUID, principal: SignedInMember, session: DatabaseSession
) -> dict[str, object]:
    _available()
    run = _visible_run(session, principal, run_id)
    if run.status != ZoningRunState.SUCCEEDED:
        raise GrpError(409, "RESULT_NOT_READY", "This coastal-zoning result is not ready yet.")
    artifact = session.scalar(
        select(CoastalZoningArtifact).where(
            CoastalZoningArtifact.run_id == run.id,
            CoastalZoningArtifact.kind == "result_json",
        )
    )
    if artifact is None:
        raise not_found()
    storage = LocalStorage(get_settings().storage_root)
    try:
        if storage.sha256(artifact.storage_key) != artifact.sha256:
            raise ValueError("checksum")
        result = json.loads(storage.read_bytes(artifact.storage_key))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise GrpError(503, "RESULT_UNAVAILABLE", "The result artifact is unavailable.") from error
    if not isinstance(result, dict):
        raise GrpError(503, "RESULT_UNAVAILABLE", "The result artifact is unavailable.")
    zones = session.scalars(
        select(CoastalZoningZone).where(CoastalZoningZone.run_id == run.id)
    ).all()
    edits = {zone.zone_id: zone for zone in zones}
    for candidate in result.get("candidates", []):
        if isinstance(candidate, dict) and candidate.get("zone_id") in edits:
            zone = edits[candidate["zone_id"]]
            candidate["name"] = zone.display_name
            candidate["note"] = zone.note
    result["review_state"] = run.review_state
    result["trace_id"] = run.trace_id
    return result


@router.get(
    "/runs/{run_id}/trace",
    summary="Read the persistent P1-P10 trace",
    openapi_extra={"x-grp-access": "protected"},
)
def read_coastal_zoning_trace(
    run_id: UUID, principal: SignedInMember, session: DatabaseSession
) -> dict[str, object]:
    _available()
    run = _visible_run(session, principal, run_id)
    steps = session.scalars(
        select(CoastalZoningStep)
        .where(CoastalZoningStep.run_id == run.id)
        .order_by(CoastalZoningStep.sequence)
    ).all()
    return {
        "run_id": str(run.id),
        "trace_id": run.trace_id,
        "steps": _run_payload(run, steps)["steps"],
    }


@router.post(
    "/runs/{run_id}/review",
    summary="Review names and notes for a completed coastal-zoning report",
    openapi_extra={"x-grp-access": "protected"},
)
def review_coastal_zoning_run(
    run_id: UUID,
    payload: ZoningReviewSubmit,
    principal: SignedInMember,
    session: DatabaseSession,
) -> dict[str, object]:
    _available()
    run = _visible_run(session, principal, run_id)
    if not _may_review(principal, run):
        raise not_found()
    if run.status != ZoningRunState.SUCCEEDED:
        raise GrpError(409, "RUN_NOT_REVIEWABLE", "Only a completed report can be reviewed.")
    if len({edit.zone_id for edit in payload.zones}) != len(payload.zones):
        raise validation_failed("Each zone may be edited only once per review.")
    reviewer_role = "platform_admin" if principal.is_platform_admin else "hub_admin"
    for edit in payload.zones:
        zone = session.get(CoastalZoningZone, (run.id, edit.zone_id))
        if zone is None:
            raise validation_failed(f"Unknown zone: {edit.zone_id}.")
        for field in ("display_name", "note"):
            value = getattr(edit, field)
            if value is None or value == getattr(zone, field):
                continue
            previous = getattr(zone, field)
            setattr(zone, field, value)
            session.add(
                CoastalZoningReviewLog(
                    run_id=run.id,
                    reviewer_id=principal.user_id,
                    reviewer_role=reviewer_role,
                    field=f"zone.{zone.zone_id}.{field}",
                    old_value=previous,
                    new_value=value,
                    support_ref=new_support_ref(),
                )
            )
    previous_state = run.review_state
    run.review_state = ZoningReviewState.REVIEWED
    session.add(
        CoastalZoningReviewLog(
            run_id=run.id,
            reviewer_id=principal.user_id,
            reviewer_role=reviewer_role,
            field="review_state",
            old_value=previous_state,
            new_value=run.review_state,
            support_ref=new_support_ref(),
        )
    )
    _audit(
        session,
        principal,
        run,
        "coastal_zoning_reviewed",
        {"review_state": run.review_state, "edited_zones": len(payload.zones)},
    )
    session.commit()
    return {"run_id": str(run.id), "review_state": run.review_state, "trace_id": run.trace_id}


@router.post(
    "/runs/{run_id}/retire",
    summary="Retire a coastal-zoning report without deleting its evidence receipts",
    openapi_extra={"x-grp-access": "protected"},
)
def retire_coastal_zoning_run(
    run_id: UUID, principal: SignedInMember, session: DatabaseSession
) -> dict[str, object]:
    _available()
    run = _visible_run(session, principal, run_id)
    if not _may_review(principal, run):
        raise not_found()
    if run.status not in {ZoningRunState.SUCCEEDED, ZoningRunState.FAILED}:
        raise GrpError(409, "RUN_NOT_RETIRABLE", "Only a finished report can be retired.")
    run.status = ZoningRunState.RETIRED
    run.retired_at = utc_now()
    _audit(session, principal, run, "coastal_zoning_retired", {"status": run.status})
    session.commit()
    return {"run_id": str(run.id), "status": run.status, "trace_id": run.trace_id}


@router.post(
    "/runs/{run_id}/cancel",
    summary="Cancel a queued or running coastal-zoning run",
    openapi_extra={"x-grp-access": "protected"},
)
def cancel_coastal_zoning_run(
    run_id: UUID, principal: SignedInMember, session: DatabaseSession
) -> dict[str, object]:
    _available()
    run = _visible_run(session, principal, run_id)
    if not _may_change(principal, run):
        raise not_found()
    try:
        request_cancellation(session, run)
    except ZoningTransitionError as error:
        raise GrpError(409, "RUN_NOT_CANCELLABLE", str(error)) from error
    _audit(session, principal, run, "coastal_zoning_cancelled", {"status": run.status})
    session.commit()
    return {"run_id": str(run.id), "status": run.status, "trace_id": run.trace_id}


@router.post(
    "/runs/{run_id}/retry",
    summary="Retry a failed coastal-zoning run",
    status_code=202,
    openapi_extra={"x-grp-access": "protected"},
)
def retry_coastal_zoning_run(
    run_id: UUID, principal: SignedInMember, session: DatabaseSession
) -> JSONResponse:
    _available()
    run = _visible_run(session, principal, run_id)
    if not _may_change(principal, run):
        raise not_found()
    try:
        retry_failed_run(session, run)
    except ZoningTransitionError as error:
        raise GrpError(409, "RUN_NOT_RETRYABLE", str(error)) from error
    _audit(session, principal, run, "coastal_zoning_retried", {"status": run.status})
    session.commit()
    return _accepted(run)
