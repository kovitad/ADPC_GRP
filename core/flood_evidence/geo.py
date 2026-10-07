"""Small, dependency-free geometry for flood evidence: distances in metres and area tests.

Distances use a local flat projection around the points involved, which is accurate to well
under a metre at the scale of a city district. Inputs are GeoJSON-style lon/lat coordinates.
"""

from __future__ import annotations

import math
from typing import Any

M_PER_DEG_LAT = 110_540.0


def _m_per_deg_lon(lat: float) -> float:
    return 111_320.0 * math.cos(math.radians(lat))


def lines_of(geometry: dict[str, Any]) -> list[list[tuple[float, float]]]:
    kind, coords = geometry["type"], geometry["coordinates"]
    if kind == "Point":
        return [[(coords[0], coords[1])]]
    raw = coords if kind == "MultiLineString" else [coords]
    return [[(p[0], p[1]) for p in line] for line in raw]


def points_of(geometry: dict[str, Any]) -> list[tuple[float, float]]:
    return [p for line in lines_of(geometry) for p in line]


def _segment(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    length = dx * dx + dy * dy
    t = 0.0 if length == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def point_to_geometry_m(lon: float, lat: float, geometry: dict[str, Any]) -> float:
    """Metres from a point to the nearest part of a point or line geometry."""

    sx, sy = _m_per_deg_lon(lat), M_PER_DEG_LAT
    best = math.inf
    for line in lines_of(geometry):
        pts = [((x - lon) * sx, (y - lat) * sy) for x, y in line]
        if len(pts) == 1:
            best = min(best, math.hypot(*pts[0]))
            continue
        for (ax, ay), (bx, by) in zip(pts, pts[1:], strict=False):
            best = min(best, _segment(0.0, 0.0, ax, ay, bx, by))
    return best


def geometry_to_geometry_m(a: dict[str, Any], b: dict[str, Any]) -> float:
    """Shortest distance between two point or line geometries (vertex-to-line, both ways)."""

    best = min(point_to_geometry_m(x, y, b) for x, y in points_of(a))
    return min(best, min(point_to_geometry_m(x, y, a) for x, y in points_of(b)))


def bbox(geometry: dict[str, Any]) -> tuple[float, float, float, float]:
    pts = points_of(geometry)
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def expand(box: tuple[float, float, float, float], metres: float) -> tuple[float, ...]:
    west, south, east, north = box
    dlat = metres / M_PER_DEG_LAT
    dlon = metres / _m_per_deg_lon((south + north) / 2)
    return west - dlon, south - dlat, east + dlon, north + dlat


def boxes_touch(a: tuple[float, ...], b: tuple[float, ...]) -> bool:
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def _inside_ring(x: float, y: float, ring: list[list[float]]) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def inside_outline(lon: float, lat: float, outline: dict[str, Any]) -> bool:
    polygons = outline["coordinates"] if outline["type"] == "MultiPolygon" else [
        outline["coordinates"]
    ]
    return any(
        _inside_ring(lon, lat, rings[0]) and not any(_inside_ring(lon, lat, r) for r in rings[1:])
        for rings in polygons
    )


def outline_box(outline: dict[str, Any]) -> tuple[float, float, float, float]:
    """The bounding box of a Polygon or MultiPolygon outline (outer rings)."""

    polygons = outline["coordinates"] if outline["type"] == "MultiPolygon" else [
        outline["coordinates"]
    ]
    points = [p for rings in polygons for p in rings[0]]
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def district_codes(
    geometry: dict[str, Any], areas: list[tuple[str, dict[str, Any]]]
) -> list[str]:
    """Codes of every area that any vertex of the geometry falls in, checked box-first."""

    box = bbox(geometry)
    return sorted(code for code, outline in areas
                  if boxes_touch(box, outline_box(outline)) and touches_outline(geometry, outline))


def touches_outline(geometry: dict[str, Any], outline: dict[str, Any]) -> bool:
    """True when any vertex of the geometry lies inside the outline."""

    return any(inside_outline(x, y, outline) for x, y in points_of(geometry))
