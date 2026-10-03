"""Floodboard adapter: its open road and report exports into GRP observations (spec FB-1, FB-2).

Measured on 3 October 2026:

- ``roads.geojson`` is a full snapshot of MultiLineString features without IDs. Names repeat,
  so a segment is identified by the SHA-256 of its geometry.
- ``conf`` decays without ``updated`` moving, and ``updated`` can move with nothing else
  changing. ``conf`` is therefore Floodboard's judgement, not part of the observed state.
- ``reports.csv`` covers about 24 hours. ``current_weight`` decays like ``conf``. ``text`` quotes
  news and Traffy complaints and can identify people: only its hash is kept.

Floodboard's own provider names are kept as the underlying sources, so a Traffy report reached
through Floodboard and later directly from Traffy is still one piece of evidence.
"""

from __future__ import annotations

import csv
import io
import json
import math
from datetime import UTC, datetime
from typing import Any

from core.flood_evidence.observation import (
    OBSERVED,
    PROVIDER_DERIVED,
    REPORT,
    ROAD_SEGMENT,
    SYNTHETIC_DEMO,
    VEHICLES,
    VERDICTS,
    ObservationDraft,
    SourceFormatError,
    sha256_text,
)

ROAD_KEYS = frozenset(
    {"name", "nameEn", "hw", "depthCm", "closedAll", "closedSmall", "cleared", "updated",
     "verdict", "sources"}
)
REPORT_COLUMNS = (
    "id", "time_utc", "lat", "lon", "source", "tier", "depth_cm", "closed_all",
    "closed_small_cars", "cleared", "current_weight", "text", "url",
)
# Floodboard's markers for a feature it inferred rather than observed.
DERIVED_FLAGS = ("estimated", "inferred")
DERIVED_SOURCES = frozenset({"cluster"})
MAX_FEATURES = 100_000
BANGKOK_REGION = (99.0, 12.5, 102.0, 15.5)  # lon/lat sanity window, wider than the pilot


def _number(value: Any, field: str) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise SourceFormatError(f"{field} is not a number")
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise SourceFormatError(f"{field} is not a number") from error
    if not math.isfinite(number):
        raise SourceFormatError(f"{field} is not finite")
    return number


def _flag(value: Any, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if value in ("true", "false"):
        return value == "true"
    raise SourceFormatError(f"{field} is not true or false")


def _depth(value: Any, field: str) -> float | None:
    depth = _number(value, field)
    if depth is not None and not 0 <= depth <= 1000:
        raise SourceFormatError(f"{field} is outside 0-1000 cm")
    return depth


def _epoch_ms(value: Any) -> datetime:
    millis = _number(value, "updated")
    if millis is None:
        raise SourceFormatError("updated is missing")
    return datetime.fromtimestamp(millis / 1000, UTC)


def _iso(value: str) -> datetime:
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise SourceFormatError("time_utc is not an ISO time") from error
    if moment.tzinfo is None:
        raise SourceFormatError("time_utc has no time zone")
    return moment.astimezone(UTC)


def _in_region(lon: float, lat: float) -> bool:
    west, south, east, north = BANGKOK_REGION
    return west <= lon <= east and south <= lat <= north


def _check_lines(geometry: Any) -> dict[str, Any]:
    if not isinstance(geometry, dict) or geometry.get("type") not in {
        "LineString", "MultiLineString"
    }:
        raise SourceFormatError("A road is not a line")
    lines = geometry.get("coordinates")
    if geometry["type"] == "LineString":
        lines = [lines]
    if not isinstance(lines, list) or not lines:
        raise SourceFormatError("A road has no coordinates")
    for line in lines:
        if not isinstance(line, list) or len(line) < 2:
            raise SourceFormatError("A road line has fewer than two points")
        for point in line:
            if not (isinstance(point, list) and len(point) >= 2):
                raise SourceFormatError("A road point is malformed")
            lon, lat = _number(point[0], "lon"), _number(point[1], "lat")
            if lon is None or lat is None or not _in_region(lon, lat):
                raise SourceFormatError("A road point is outside the Bangkok region")
    return {"type": geometry["type"], "coordinates": geometry["coordinates"]}


def _verdict(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise SourceFormatError("verdict is not an object")
    verdict = {}
    for vehicle in VEHICLES:
        label = value.get(vehicle)
        if label not in VERDICTS:
            raise SourceFormatError(f"verdict for {vehicle} is not one of {VERDICTS}")
        verdict[vehicle] = label
    return verdict


def parse_roads(body: bytes) -> list[ObservationDraft]:
    """Parse ``roads.geojson``. Any malformed feature rejects the whole file (fail closed)."""

    try:
        collection = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SourceFormatError("roads.geojson is not JSON") from error
    if not isinstance(collection, dict) or collection.get("type") != "FeatureCollection":
        raise SourceFormatError("roads.geojson is not a FeatureCollection")
    features = collection.get("features")
    if not isinstance(features, list):
        raise SourceFormatError("roads.geojson has no feature list")
    if len(features) > MAX_FEATURES:
        raise SourceFormatError("roads.geojson has too many features")
    drafts: dict[str, ObservationDraft] = {}
    for feature in features:
        properties = feature.get("properties") if isinstance(feature, dict) else None
        if not isinstance(properties, dict) or not ROAD_KEYS <= properties.keys():
            raise SourceFormatError("A road is missing expected properties")
        geometry = _check_lines(feature.get("geometry"))
        sources = properties["sources"]
        if not isinstance(sources, list) or not all(isinstance(s, str) for s in sources):
            raise SourceFormatError("sources is not a list of names")
        updated = _epoch_ms(properties["updated"])
        external_id = sha256_text(json.dumps(geometry, sort_keys=True, separators=(",", ":")))
        derived = (
            properties.get("hw") == "zone"
            or any(properties.get(flag) for flag in DERIVED_FLAGS)
            or bool(DERIVED_SOURCES & set(sources))
        )
        judgement = {"conf": _number(properties.get("conf"), "conf")}
        if properties.get("kept") is not None:
            judgement["kept"] = properties["kept"]
        if properties.get("spreadM") is not None:
            judgement["spread_m"] = _number(properties["spreadM"], "spreadM")
        drafts[external_id] = ObservationDraft(
            kind=ROAD_SEGMENT,
            external_id=external_id,
            observed_at=updated,
            reported_at=updated,
            geometry=geometry,
            state={
                "name": str(properties["name"] or ""),
                "name_en": str(properties["nameEn"] or ""),
                "road_class": str(properties["hw"] or ""),
                "closed_all": _flag(properties["closedAll"], "closedAll"),
                "closed_small": _flag(properties["closedSmall"], "closedSmall"),
                "cleared": _flag(properties["cleared"], "cleared"),
                "verdict": _verdict(properties["verdict"]),
            },
            underlying_sources=tuple(sorted(set(sources))),
            evidence_class=PROVIDER_DERIVED if derived else OBSERVED,
            provider_judgement=judgement,
            depth_cm=_depth(properties["depthCm"], "depthCm"),
        )
    return list(drafts.values())


def parse_reports(body: bytes) -> list[ObservationDraft]:
    """Parse ``reports.csv``. Text is reduced to its hash; links are not kept."""

    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise SourceFormatError("reports.csv is not UTF-8") from error
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if tuple(reader.fieldnames or ()) != REPORT_COLUMNS:
        raise SourceFormatError("reports.csv columns changed")
    drafts: dict[str, ObservationDraft] = {}
    for row in reader:
        if len(drafts) >= MAX_FEATURES:
            raise SourceFormatError("reports.csv has too many rows")
        external_id = row["id"].strip()
        source = row["source"].strip()
        if not external_id or not source:
            raise SourceFormatError("A report has no ID or source")
        lon, lat = _number(row["lon"], "lon"), _number(row["lat"], "lat")
        if lon is None or lat is None or not _in_region(lon, lat):
            raise SourceFormatError("A report is outside the Bangkok region")
        observed = _iso(row["time_utc"])
        report_text = row["text"] or ""
        drafts[external_id] = ObservationDraft(
            kind=REPORT,
            external_id=external_id,
            observed_at=observed,
            reported_at=observed,
            geometry={"type": "Point", "coordinates": [lon, lat]},
            state={
                "tier": row["tier"].strip(),
                "closed_all": _flag(row["closed_all"], "closed_all"),
                "closed_small": _flag(row["closed_small_cars"], "closed_small_cars"),
                "cleared": _flag(row["cleared"], "cleared"),
            },
            underlying_sources=(source,),
            # A replay injection (ADR-0044) is always labelled as made up, whatever its source.
            evidence_class=SYNTHETIC_DEMO if external_id.startswith("synthetic:")
            else PROVIDER_DERIVED if source in DERIVED_SOURCES else OBSERVED,
            provider_judgement={"current_weight": _number(row["current_weight"], "current_weight")},
            depth_cm=_depth(row["depth_cm"], "depth_cm"),
            text_sha256=sha256_text(report_text) if report_text else None,
        )
    return list(drafts.values())


PARSERS = {"floodboard_roads": parse_roads, "floodboard_reports": parse_reports}
