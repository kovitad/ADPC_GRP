"""Download everything the Planning page knows about one district, as .docx or .csv (ADR-0033).

Every fact is read here from GRP's own records, through the same functions the page uses, so the
document says what the panel says. The browser supplies only the district, the assessment and a
map picture it drew; the picture is checked to be a modest PNG and is otherwise just an image.
"""

from __future__ import annotations

import base64
import binascii
import csv
import io
import re
import struct
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from api.assessments import LIMITS, assessment_result
from api.catalog import area_profile
from api.dependencies import DatabaseSession
from api.errors import GrpError, not_found
from api.maps import CentreIndicatorRequest, centre_indicator_values, dataset_features, map_layers
from api.permissions import SignedInMember
from api.planning import _canonical_sig_place
from api.planning_access import planner_membership
from api.sessions import CurrentPrincipal
from core.assessment_models import AssessmentFeature, Boundary, Feature
from core.planning_memory_models import PlanningChatMessage
from core.summary_docx import STATUS_LABELS, render_summary

router = APIRouter(prefix="/planning", tags=["planning"])

BANGKOK = timezone(timedelta(hours=7))
MAP_PNG_MAX_BYTES = 6 * 1024 * 1024
MAP_PNG_MAX_SIDE = 4000
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_CENTRES = 2000
SUPPORTING_TITLES = {
    "volunteer_centers": "Civil-defence volunteer centres",
    "early_warning_resources": "Early-warning resources",
    "village_locations": "Villages",
}


class SummaryRequest(BaseModel):
    hub_code: str | None = Field(default=None, max_length=64)
    boundary_id: UUID
    assessment_id: UUID | None = None
    # A PNG the browser drew from the page's own layers, as base64 or a data: URL.
    map_png: str | None = Field(default=None, max_length=8_500_000)
    map_has_basemap: bool = False


def _map_picture(value: str | None) -> bytes | None:
    if not value:
        return None
    text = value.split(",", 1)[1] if value.startswith("data:") else value
    try:
        data = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError) as error:
        raise GrpError(422, "MAP_PICTURE_INVALID", "The map picture could not be read.") from error
    if len(data) > MAP_PNG_MAX_BYTES or not data.startswith(PNG_SIGNATURE) or len(data) < 24:
        raise GrpError(422, "MAP_PICTURE_INVALID", "The map picture must be a PNG under 6 MB.")
    width, height = struct.unpack(">II", data[16:24])
    if not (0 < width <= MAP_PNG_MAX_SIDE and 0 < height <= MAP_PNG_MAX_SIDE):
        raise GrpError(422, "MAP_PICTURE_INVALID", "The map picture is too large.")
    return data


def _when(value: Any) -> str:
    try:
        moment = datetime.fromisoformat(str(value))
    except ValueError:
        return str(value or "unknown time")
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(BANGKOK).strftime("%d %b %Y %H:%M")


def _centres(
    session, principal: CurrentPrincipal, hub_code: str, boundary: Boundary,
    assessment_id: UUID | None, layers: dict[str, Any],
) -> dict[str, Any]:
    """The assessment's rows when it belongs to this district; otherwise the source list."""

    result = None
    if assessment_id is not None:
        result = assessment_result(assessment_id, principal, session)
        if (result.get("area_detail") or {}).get("admin_code") != boundary.admin_code:
            result = None  # another district's result never enters this one's document
    rows: list[dict[str, Any]] = []
    if result is not None:
        pairs = session.execute(
            select(AssessmentFeature, Feature)
            .join(Feature, Feature.id == AssessmentFeature.feature_id)
            .where(AssessmentFeature.assessment_id == assessment_id)
            .order_by(Feature.name)
            .limit(MAX_CENTRES)
        ).all()
        for assessed, feature in pairs:
            rows.append({
                "feature_id": feature.id,
                "name": feature.name,
                "subdistrict": feature.attributes.get("subdistrict") or None,
                "village": feature.attributes.get("village") or None,
                "capacity": feature.attributes.get("capacity"),
                "supporting_unit": feature.attributes.get("supporting_unit") or None,
                "status": assessed.status,
                "depth_m": assessed.flood_depth_m,
            })
        pinned = next((d for d in result["datasets"] if d["role"] == "evacuation_centers"), {})
        source_line = (
            f"From assessment {result['assessment_id']}: "
            f"{pinned.get('title', 'evacuation centres')} "
            f"({pinned.get('provider', '')}), version {str(pinned.get('version_id', ''))[:8]}."
        )
    else:
        current = next((c for c in layers.get("evacuation_centers", []) if c.get("is_current")),
                       None)
        if current is not None:
            collection = dataset_features(
                UUID(current["version_id"]), principal, session, hub_code, boundary.id
            )
            for item in collection["features"][:MAX_CENTRES]:
                props = item["properties"]
                rows.append({
                    "feature_id": UUID(props["feature_id"]),
                    "name": props["name"],
                    "subdistrict": props.get("subdistrict"),
                    "village": props.get("village"),
                    "capacity": props.get("capacity"),
                    "supporting_unit": props.get("supporting_unit"),
                    "status": "not_assessed",
                    "depth_m": None,
                })
        source_line = (
            f"From the current source list: {current['title']} ({current['provider']}), not "
            "assessed." if current else "No evacuation-centre source is loaded."
        )
    indicators = centre_indicator_values(
        CentreIndicatorRequest(hub_code=hub_code,
                               feature_ids=[row["feature_id"] for row in rows]),
        principal, session,
    ) if rows else {"indicators": [], "values": {}}
    titles = {item["indicator_key"]: item["title"] for item in indicators["indicators"]}
    for row in rows:
        row["indicators"] = indicators["values"].get(str(row["feature_id"]), {})
    scenario = (
        f"RP{result['scenario']['return_period_years']} flood" if result else "not assessed"
    )
    method = (
        f"{result['method']['key']} {result['method']['version']} ({result['method']['status']})"
        if result else ""
    )
    return {
        "total": len(rows),
        "rows": rows,
        "summary": result["summary"] if result else None,
        "scenario": scenario,
        "method": method,
        "assessment_id": result["assessment_id"] if result else None,
        "source_line": source_line,
        "indicator_titles": titles,
        "result": result,
    }


# Global Risk's layer names, as a planner would say them. An unknown layer keeps its own name.
GLOBAL_RISK_ITEMS = {
    "schools": "Schools",
    "hospitals": "Hospitals",
    "buildings": "Buildings",
    "roads": "Roads",
    "health_facilities": "Health facilities",
}


def _item_label(name: str) -> tuple[str, str]:
    """The planner's name for a Global Risk layer, and what it means for them."""

    if "evacuation_centre" in name or "evacuation_center" in name:
        # ADPC uploaded GRP's own centre table to Global Risk as a test (ADR-0032). Its count is
        # GRP's data echoed back, not a second opinion.
        return ("Evacuation centres", "GRP's own centre data sent to Global Risk as a test "
                "upload; not an independent check")
    return GLOBAL_RISK_ITEMS.get(name, name.replace("_", " ").capitalize()), (
        "Not in GRP's data; Global Risk adds it")


def global_risk_stats(evidence: dict[str, Any]) -> list[list[Any]]:
    """Rows of what Global Risk counted in its flood hazard layer for this district.

    Hazard exposure only: Global Risk's risk levels (`at_risk`, `by_risk`) stay out (ADR-0014).
    """

    counts = (evidence.get("stats") or {}).get("counts") or {}
    rows = []
    for name, value in counts.items():
        if not isinstance(value, dict):
            continue
        label, note = _item_label(str(name))
        if isinstance(value.get("exposed"), int | float):
            severity = value.get("by_severity") or {}
            classes = ", ".join(
                f"class {key}: {severity[key]}" for key in sorted(severity)
                if isinstance(severity[key], int | float) and severity[key]
            )
            rows.append([label, value["exposed"], value.get("total"), "count",
                         classes or "none", note])
        elif isinstance(value.get("exposed_km"), int | float):
            rows.append([label, value["exposed_km"], value.get("total_km"), "km", "-", note])
    return rows


def _global_risk(session, principal: CurrentPrincipal, hub_id: UUID,
                 boundary: Boundary) -> dict[str, Any] | None:
    """This person's latest Global Risk evidence for exactly this place, never another's."""

    places = {_canonical_sig_place(boundary)}
    if boundary.admin_level == "subdistrict":
        # A sub-district question gathers its parent district's evidence (planning.py).
        parent = session.scalar(
            select(Boundary).where(
                Boundary.admin_level == "district",
                Boundary.admin_code == boundary.admin_code[:4],
                Boundary.is_supported,
            )
        )
        if parent is not None:
            places.add(_canonical_sig_place(parent))
    wanted = {place.casefold() for place in places if place}
    messages = session.scalars(
        select(PlanningChatMessage)
        .where(
            PlanningChatMessage.user_id == principal.user_id,
            PlanningChatMessage.hub_id == hub_id,
            PlanningChatMessage.kind == "evidence",
        )
        .order_by(PlanningChatMessage.created_at.desc())
        .limit(60)
    ).all()
    for message in messages:
        payload = message.payload or {}
        evidence = payload.get("evidence") or {}
        area = evidence.get("area") or {}
        if str(area.get("requested") or "").casefold() not in wanted:
            continue
        stats = global_risk_stats(evidence)
        receipt = evidence.get("receipt") or payload.get("receipt") or {}
        if receipt.get("receipt_id"):
            status = f"passed Global Risk's source check, receipt {receipt['receipt_id']}"
        elif payload.get("answer_source") == "deterministic_fallback":
            status = "deterministic evidence summary, not publishable"
        else:
            status = "unverified draft, not published"
        summary = evidence.get("summary") or {}
        return {
            "place": area.get("sig_place") or evidence.get("place") or "",
            "pack_id": evidence.get("pack_id") or "-",
            "assembled_at": _when(evidence.get("assembled_at")),
            "status": status,
            "question": message.question or evidence.get("question"),
            "brief": payload.get("answer") or message.text,
            "stats": stats,
            "source_note": (
                "No source was pulled live in this run; computed exposure is not a report of "
                "current flooding." if summary.get("pulled_live") == 0 else None
            ),
            "citations": [
                [c.get("n"), c.get("title"), c.get("source"), c.get("validation"),
                 c.get("retrieval")]
                for c in evidence.get("citations") or [] if isinstance(c, dict)
            ],
            "gaps": [str(gap) for gap in evidence.get("gaps") or []],
            "receipt_id": receipt.get("receipt_id"),
            "receipt_url": receipt.get("public_url"),
            "map_link": payload.get("map_link") if not payload.get("map_link_verified") else
            payload.get("map_url"),
        }
    return None


def gather(session, principal: CurrentPrincipal, request: SummaryRequest) -> dict[str, Any]:
    hub = planner_membership(principal, request.hub_code)
    boundary = session.get(Boundary, request.boundary_id)
    if boundary is None or not boundary.is_supported:
        raise not_found()
    profile = area_profile(boundary.id, principal, session, hub.hub_code)
    layers = map_layers(principal, session, hub.hub_code)
    centres = _centres(session, principal, hub.hub_code, boundary, request.assessment_id, layers)
    result = centres.pop("result")

    supporting = []
    for layer in layers.get("supporting_points", []):
        if not layer.get("available"):
            continue
        collection = dataset_features(
            UUID(layer["version_id"]), principal, session, hub.hub_code, boundary.id
        )
        supporting.append({
            "title": SUPPORTING_TITLES.get(layer["role"], layer["title"]),
            "count": collection["total"],
            "source": [layer["role"], layer["title"], layer["provider"],
                       layer["version_id"][:8]],
        })

    sources = []
    flood = next((f for f in layers.get("flood", []) if not f.get("preview_only")), None)
    if result is not None:
        sources += [[d["role"], d.get("title", ""), d.get("provider", ""),
                     str(d.get("version_id", ""))[:8]] for d in result["datasets"]]
    elif flood is not None:
        sources.append(["hazard", flood["title"], flood["provider"], flood["version_id"][:8]])
    sources += [item.pop("source") for item in supporting]
    for item in layers.get("vulnerability", []):
        if item.get("available"):
            sources.append(["sensitivity (display only)", item["title"], item["provider"],
                            item["version_id"][:8]])
    if profile.get("source"):
        source = profile["source"]
        sources.append(["villages and population", source.get("label", ""),
                        "Village register", str(source.get("version_id", ""))[:8]])
    sources.append(["boundary", f"{boundary.name} ({boundary.admin_code})", boundary.source,
                    boundary.edition])

    limits = list(result["limits"] if result else LIMITS)
    if result:
        limits += [gap for gap in result["gaps"] if gap not in limits]
    synthetic = bool(result and result.get("synthetic")) or (
        "synthetic" in boundary.source.casefold()
    )
    area = profile["area"]
    return {
        "generated_at": datetime.now(BANGKOK).strftime("%d %b %Y %H:%M"),
        "prepared_by": principal.display_name or principal.email,
        "hub": hub.hub_name,
        "area": area,
        "synthetic": synthetic,
        "centres": {
            **centres,
            "gap_note": None if centres["total"] else (
                f"{boundary.name} has no evacuation-centre records in the current shelter data. "
                "This is a gap in the data, not a finding that it has no shelters."
            ),
        },
        "people": {
            "population": profile.get("population"),
            "flood_exposure": profile.get("flood_exposure"),
        },
        "supporting": supporting,
        "global_risk": _global_risk(session, principal, hub.hub_id, boundary),
        "limits": limits,
        "sources": sources,
    }


def _filename(area: dict[str, Any], extension: str) -> tuple[str, str]:
    stem = re.sub(r"[^A-Za-z0-9]+", "-", str(area.get("name") or "district")).strip("-").lower()
    day = datetime.now(BANGKOK).strftime("%Y-%m-%d")
    ascii_name = f"grp-flood-summary-{stem or 'district'}-{day}.{extension}"
    return ascii_name, (
        f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(ascii_name)}"
    )


@router.post(
    "/summary.docx",
    summary="The district's planning summary as a Word document",
    openapi_extra={"x-grp-access": "protected"},
    response_class=Response,
)
def summary_docx(
    payload: SummaryRequest, principal: SignedInMember, session: DatabaseSession
) -> Response:
    picture = _map_picture(payload.map_png)
    facts = gather(session, principal, payload)
    facts["map"] = {
        "png": picture,
        "caption": (
            f"{_map_title(facts)} District outline and evacuation centres over the flood-depth "
            "display preview (about 1.9 km per pixel; each centre's status comes from the "
            "full-resolution layer)."
            + (" Base map © OpenStreetMap contributors." if payload.map_has_basemap else "")
        ),
    }
    _, disposition = _filename(facts["area"], "docx")
    return Response(
        render_summary(facts),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": disposition, "Cache-Control": "no-store"},
    )


def _map_title(facts: dict[str, Any]) -> str:
    return f"Figure 1. {facts['area'].get('name', '')} ({facts['centres']['scenario']})."


def _cell(value: Any) -> Any:
    # A leading = + - @ would run as a formula when the file is opened in a spreadsheet.
    if isinstance(value, str) and value[:1] in {"=", "+", "-", "@"}:
        return f"'{value}"
    return "" if value is None else value


@router.get(
    "/summary/centres.csv",
    summary="The district's evacuation-centre table as CSV",
    openapi_extra={"x-grp-access": "protected"},
    response_class=Response,
)
def summary_centres_csv(
    principal: SignedInMember,
    session: DatabaseSession,
    boundary_id: UUID,
    hub_code: str | None = Query(default=None, max_length=64),
    assessment_id: UUID | None = None,
) -> Response:
    facts = gather(
        session, principal,
        SummaryRequest(hub_code=hub_code, boundary_id=boundary_id, assessment_id=assessment_id),
    )
    centres = facts["centres"]
    titles = centres["indicator_titles"]
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Centre", "Sub-district", "Village", "Capacity", "Supporting unit", "Status",
                     "Flood depth (m)", *titles.values()])
    for row in centres["rows"]:
        writer.writerow([_cell(v) for v in (
            row["name"], row.get("subdistrict"), row.get("village"), row.get("capacity"),
            row.get("supporting_unit"), STATUS_LABELS.get(row["status"], row["status"]),
            "" if row.get("depth_m") is None else round(row["depth_m"], 2),
            *[(row["indicators"] or {}).get(key) for key in titles],
        )])
    _, disposition = _filename(facts["area"], "csv")
    # A byte-order mark so Excel opens Thai names correctly.
    return Response(
        "﻿" + out.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": disposition, "Cache-Control": "no-store"},
    )
