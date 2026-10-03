"""Group flood evidence into incidents: slice 5a of the Bangkok pilot (ADR-0041).

Pure functions, no database. An incident is a group of nearby road segments with flooding
reported now inside the demo area, with the point reports around it. Rules:

- **Independence counts source types, not reports.** Floodboard's underlying names are folded
  into families: BMA (sensor or DDS), Traffy and crowd. ``cluster`` is Floodboard's own
  inference and ``news`` is context; neither counts. Many Traffy complaints are "several reports
  of one kind", not independent corroboration.
- **Freshness comes from the newest real report.** Floodboard's ``updated`` can be a
  recalculation (ADR-0038), so it is used only when no report is attached, and that is labelled.
- **Conflict is never averaged.** A fresh report of dry or cleared ground, or a BMA sensor reading
  0 cm, close to fresh flooding marks the incident ``conflicting`` and puts it first in the queue.
- **Confidence is a word with reasons**, never a number: low, medium, high or conflicting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from core.flood_evidence.freshness import counts_as_current, freshness
from core.flood_evidence.geo import (
    bbox,
    boxes_touch,
    expand,
    geometry_to_geometry_m,
    point_to_geometry_m,
    touches_outline,
)

RULE_VERSION = "IncidentGrouping v0.1"
FAMILY = {"bma_sensor": "bma", "bma_dds": "bma", "traffy": "traffy", "crowd": "crowd"}
FRESH_CONTRARY = frozenset({"current", "recent"})
CONFIDENCE_ORDER = {"conflicting": 0, "low": 1, "medium": 2, "high": 3}


@dataclass(frozen=True)
class Params:
    link_m: float = 80.0  # segments this close belong to one incident
    attach_m: float = 200.0  # reports this close are part of the incident's evidence
    contrary_m: float = 100.0  # a dry claim this close to flooding is a conflict
    bands: dict[str, int] = field(default_factory=dict)


@dataclass
class Cluster:
    road_keys: list[str]
    segments: list[dict[str, Any]]
    reports: list[dict[str, Any]] = field(default_factory=list)
    contrary: list[dict[str, Any]] = field(default_factory=list)

    @property
    def box(self) -> tuple[float, float, float, float]:
        boxes = [bbox(s["geometry"]) for s in self.segments]
        return (min(b[0] for b in boxes), min(b[1] for b in boxes),
                max(b[2] for b in boxes), max(b[3] for b in boxes))


def _flooding_report(report: dict[str, Any]) -> bool:
    p = report["properties"]
    if p.get("cleared"):
        return False
    if p.get("underlying_source") in {"bma_sensor", "bma_dds"} and p.get("depth_cm") == 0:
        return False
    return p.get("underlying_source") in FAMILY


def _contrary_report(report: dict[str, Any]) -> bool:
    p = report["properties"]
    if p.get("freshness") not in FRESH_CONTRARY:
        return False
    sensor_zero = p.get("underlying_source") in {"bma_sensor", "bma_dds"} and p.get("depth_cm") == 0
    return bool(p.get("cleared")) or sensor_zero


def in_area(
    features: list[dict[str, Any]], outlines: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Features with any vertex inside one of the outlines, checked box-first."""

    boxes = [bbox({"type": "LineString", "coordinates": _outline_points(o)}) for o in outlines]
    out = []
    for feature in features:
        fbox = bbox(feature["geometry"])
        if any(boxes_touch(fbox, b) and touches_outline(feature["geometry"], o)
               for b, o in zip(boxes, outlines, strict=True)):
            out.append(feature)
    return out


def _outline_points(outline: dict[str, Any]) -> list[list[float]]:
    polygons = outline["coordinates"] if outline["type"] == "MultiPolygon" else [
        outline["coordinates"]
    ]
    return [p for rings in polygons for p in rings[0]]


def group_segments(segments: list[dict[str, Any]], link_m: float) -> list[Cluster]:
    """Union nearby flooded segments into clusters, deterministically."""

    ordered = sorted(segments, key=lambda s: s["properties"]["id"])
    parent = list(range(len(ordered)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    boxes = [expand(bbox(s["geometry"]), link_m) for s in ordered]
    for i in range(len(ordered)):
        for j in range(i + 1, len(ordered)):
            if find(i) == find(j) or not boxes_touch(boxes[i], boxes[j]):
                continue
            if geometry_to_geometry_m(ordered[i]["geometry"], ordered[j]["geometry"]) <= link_m:
                parent[find(j)] = find(i)
    groups: dict[int, list[dict[str, Any]]] = {}
    for i, segment in enumerate(ordered):
        groups.setdefault(find(i), []).append(segment)
    clusters = [
        Cluster(road_keys=[s["properties"]["id"] for s in members], segments=members)
        for members in groups.values()
    ]
    clusters.sort(key=lambda c: (-len(c.road_keys), c.road_keys[0]))
    return clusters


def _distance_to_cluster(geometry: dict[str, Any], cluster: Cluster) -> float:
    x, y = geometry["coordinates"][0], geometry["coordinates"][1]
    return min(point_to_geometry_m(x, y, s["geometry"]) for s in cluster.segments)


def attach_reports(clusters: list[Cluster], reports: list[dict[str, Any]], params: Params) -> None:
    """Give each report to its nearest cluster within reach; dry claims become contrary."""

    if not clusters:
        return
    boxes = [expand(c.box, params.attach_m) for c in clusters]
    for report in sorted(reports, key=lambda r: r["properties"]["id"]):
        point = report["geometry"]
        pbox = (point["coordinates"][0], point["coordinates"][1]) * 2
        best = None
        for index, cluster in enumerate(clusters):
            if not boxes_touch(pbox, boxes[index]):
                continue
            distance = _distance_to_cluster(point, cluster)
            if best is None or distance < best[0]:
                best = (distance, cluster)
        if best is None:
            continue
        distance, cluster = best
        if _contrary_report(report) and distance <= params.contrary_m:
            cluster.contrary.append({**report, "distance_m": round(distance)})
        elif _flooding_report(report) and distance <= params.attach_m:
            cluster.reports.append({**report, "distance_m": round(distance)})


def _iso_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def assess_cluster(cluster: Cluster, as_of: datetime, params: Params) -> dict[str, Any]:
    """The incident's interpretation: confidence, reasons, freshness basis and facts."""

    families: set[str] = set()
    for segment in cluster.segments:
        families |= {FAMILY[s] for s in segment["properties"]["underlying_sources"] if s in FAMILY}
    report_families: dict[str, int] = {}
    for report in cluster.reports:
        family = FAMILY[report["properties"]["underlying_source"]]
        families.add(family)
        report_families[family] = report_families.get(family, 0) + 1

    reasons: list[str] = []
    conflict = bool(cluster.contrary)
    if conflict:
        if any(c["properties"].get("depth_cm") == 0 for c in cluster.contrary):
            reasons.append("sensor_reads_zero_nearby")
        if any(c["properties"].get("cleared") for c in cluster.contrary):
            reasons.append("dry_report_nearby")
    if families:
        reasons.append("source_types:" + "+".join(sorted(families)))
    else:
        reasons.append("no_independent_source")
    if any(n >= 3 for n in report_families.values()) and len(families) == 1:
        reasons.append("several_reports_one_type")
    if "bma" in families:
        reasons.append("bma_reading")
    if all(s["properties"]["evidence_class"] == "provider_derived" for s in cluster.segments):
        reasons.append("floodboard_inferred_only")

    if conflict:
        confidence = "conflicting"
    elif "bma" in families and len(families) >= 2:
        confidence = "high"
    elif len(families) >= 2 or families == {"bma"}:
        confidence = "medium"
    else:
        confidence = "low"

    if cluster.reports:
        newest = max(_iso_time(r["properties"]["observed_at"]) for r in cluster.reports)
        basis = "newest_report"
    else:
        newest = max(_iso_time(s["properties"]["reported_at"]) for s in cluster.segments)
        basis = "floodboard_update"
        reasons.append("freshness_from_floodboard_update")
    band = freshness(newest, as_of, params.bands)

    depths = [s["properties"]["depth_cm"] for s in cluster.segments
              if s["properties"]["depth_cm"] is not None]
    depths += [r["properties"]["depth_cm"] for r in cluster.reports
               if r["properties"]["depth_cm"] is not None]
    worst = {"ok": 0, "caution": 1, "risky": 2, "blocked": 3}
    verdicts = [s["properties"]["provider_verdict"] for s in cluster.segments
                if s["properties"].get("provider_verdict")]
    box = cluster.box
    return {
        "road_keys": sorted(cluster.road_keys),
        "report_keys": sorted(r["properties"]["id"] for r in cluster.reports),
        "contrary_keys": sorted(c["properties"]["id"] for c in cluster.contrary),
        "source_families": sorted(families),
        "confidence": confidence,
        "conflict": conflict,
        "reasons": reasons,
        "newest_evidence_at": newest.isoformat(),
        "freshness_basis": basis,
        "freshness": band,
        "evidence_current": counts_as_current(band),
        "max_depth_cm": max(depths) if depths else None,
        "closed_roads": sum(1 for s in cluster.segments if s["properties"].get("closed_all")),
        "worst_verdict": {
            vehicle: max((v[vehicle] for v in verdicts), key=worst.get, default=None)
            for vehicle in ("motorbike", "sedan", "pickup", "truck")
        },
        "bbox": list(box),
        "center": [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2],
        "rule_version": RULE_VERSION,
    }


def build_incidents(
    roads: list[dict[str, Any]],
    reports: list[dict[str, Any]],
    outlines: list[dict[str, Any]],
    as_of: datetime,
    params: Params,
) -> list[dict[str, Any]]:
    """Clusters of flooding now in the area, each with its assessment and footprint."""

    flooded = [
        f for f in in_area(roads, outlines)
        if not f["properties"]["cleared"] and counts_as_current(f["properties"]["freshness"])
    ]
    clusters = group_segments(flooded, params.link_m)
    attach_reports(clusters, in_area(reports, outlines), params)
    return [{**assess_cluster(c, as_of, params), "geometry": {
        "type": "MultiLineString",
        "coordinates": [line for s in c.segments for line in _as_lines(s["geometry"])],
    }} for c in clusters]


def _as_lines(geometry: dict[str, Any]) -> list[Any]:
    return geometry["coordinates"] if geometry["type"] == "MultiLineString" else [
        geometry["coordinates"]
    ]


def facility_flags(incident: dict[str, Any], exposures: list[dict[str, Any]]) -> dict[str, Any]:
    """The facilities an incident touches, from the stored exposure of the same snapshot."""

    keys = set(incident["road_keys"])
    hit = [a for a in exposures if keys & set(a.get("road_keys") or [])]
    return {
        "facility_ids": sorted(a["asset_id"] for a in hit),
        "hospital_near": any(a["asset_type"] == "hospital" for a in hit),
        "access_to_check": any(
            a["access_state"] in {"access_under_review", "access_disrupted_confirmed"} for a in hit
        ),
    }


def priority(incident: dict[str, Any]) -> tuple:
    """Check-first order: conflict (or an officer saw it dry), access to check, hospital near,
    not yet seen by an officer, least certain, biggest."""

    verification = incident.get("verification") or "unverified"
    return (
        0 if incident["conflict"] or verification == "officer_saw_dry" else 1,
        0 if incident.get("access_to_check") else 1,
        0 if incident.get("hospital_near") else 1,
        0 if verification == "unverified" else 1,
        CONFIDENCE_ORDER[incident["confidence"]],
        -len(incident["road_keys"]),
        incident["road_keys"][0],
    )
