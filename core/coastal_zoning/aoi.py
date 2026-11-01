"""Bounded GeoJSON validation and geodesic planning for coastal-zoning AOIs."""

from __future__ import annotations

import math
from dataclasses import dataclass

MAX_VERTICES = 5_000
LOCAL_MAX_KM2 = 2_500.0
EARTH_RADIUS_KM = 6_371.0088


class AoiValidationError(ValueError):
    """The submitted geometry cannot safely enter the zoning pipeline."""


@dataclass(frozen=True)
class AoiPlan:
    geometry: dict[str, object]
    bbox: tuple[float, float, float, float]
    area_km2: float
    vertices: int
    scale: str
    tile_size_degrees: float
    estimated_tiles: int


def plan_aoi(geometry: dict[str, object]) -> AoiPlan:
    """Validate a WGS84 Polygon/MultiPolygon and calculate conservative work limits."""

    kind = geometry.get("type")
    raw = geometry.get("coordinates")
    if kind not in {"Polygon", "MultiPolygon"} or not isinstance(raw, list) or not raw:
        raise AoiValidationError("The area must be a non-empty GeoJSON Polygon or MultiPolygon.")
    polygons = [raw] if kind == "Polygon" else raw
    normalized: list[list[list[list[float]]]] = []
    points: list[tuple[float, float]] = []
    area = 0.0
    vertices = 0
    for polygon in polygons:
        if not isinstance(polygon, list) or not polygon:
            raise AoiValidationError("Every polygon must contain an exterior ring.")
        clean_polygon: list[list[list[float]]] = []
        for ring_index, ring in enumerate(polygon):
            clean_ring = _ring(ring)
            vertices += len(clean_ring)
            if vertices > MAX_VERTICES:
                raise AoiValidationError(f"The area exceeds the {MAX_VERTICES:,}-vertex limit.")
            ring_area = abs(_ring_area_km2(clean_ring))
            area += ring_area if ring_index == 0 else -ring_area
            points.extend((position[0], position[1]) for position in clean_ring)
            clean_polygon.append(clean_ring)
        normalized.append(clean_polygon)
    if area <= 0.0001:
        raise AoiValidationError("The area is empty or its rings are not valid.")
    west = min(point[0] for point in points)
    south = min(point[1] for point in points)
    east = max(point[0] for point in points)
    north = max(point[1] for point in points)
    if east - west > 20 or north - south > 20:
        raise AoiValidationError("The area is too wide for one coastal-zoning assessment.")
    scale = "local" if area <= LOCAL_MAX_KM2 else "province"
    tile_size = 0.03 if scale == "local" else 0.15
    tiles = max(1, math.ceil((east - west) / tile_size)) * max(
        1, math.ceil((north - south) / tile_size)
    )
    output_geometry: dict[str, object]
    if kind == "Polygon":
        output_geometry = {"type": kind, "coordinates": normalized[0]}
    else:
        output_geometry = {"type": kind, "coordinates": normalized}
    return AoiPlan(
        geometry=output_geometry,
        bbox=(west, south, east, north),
        area_km2=round(area, 3),
        vertices=vertices,
        scale=scale,
        tile_size_degrees=tile_size,
        estimated_tiles=tiles,
    )


def _ring(value: object) -> list[list[float]]:
    if not isinstance(value, list) or len(value) < 4:
        raise AoiValidationError("Every ring must contain at least four positions.")
    result: list[list[float]] = []
    for position in value:
        if not isinstance(position, list) or len(position) < 2:
            raise AoiValidationError("Every position must contain longitude and latitude.")
        lon, lat = position[:2]
        if (
            isinstance(lon, bool)
            or isinstance(lat, bool)
            or not isinstance(lon, (int, float))
            or not isinstance(lat, (int, float))
            or not math.isfinite(lon)
            or not math.isfinite(lat)
            or lon < -180
            or lon > 180
            or lat < -90
            or lat > 90
        ):
            raise AoiValidationError("Coordinates must be finite WGS84 longitude and latitude.")
        result.append([float(lon), float(lat)])
    if result[0] != result[-1]:
        raise AoiValidationError("Every polygon ring must be closed.")
    if len({tuple(item) for item in result[:-1]}) < 3:
        raise AoiValidationError("A polygon ring needs at least three distinct positions.")
    return result


def _ring_area_km2(ring: list[list[float]]) -> float:
    """Spherical polygon area; sufficient for limits and coverage planning, not science outputs."""

    total = 0.0
    for first, second in zip(ring, ring[1:], strict=False):
        lon1, lat1 = map(math.radians, first)
        lon2, lat2 = map(math.radians, second)
        delta = lon2 - lon1
        if delta > math.pi:
            delta -= 2 * math.pi
        elif delta < -math.pi:
            delta += 2 * math.pi
        total += delta * (2 + math.sin(lat1) + math.sin(lat2))
    return total * EARTH_RADIUS_KM * EARTH_RADIUS_KM / 2
