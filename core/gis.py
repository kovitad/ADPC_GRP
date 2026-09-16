"""Method `center-flood-overlay` 1.0.0: classify evacuation centers against a flood raster.

Runs only in the worker (AD-03). Reads one pixel window per center, never the whole raster.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

import numpy as np
from rasterio.windows import Window
from shapely.geometry import Point, shape

from core.models import CenterStatus

METHOD_KEY = "center-flood-overlay"
METHOD_VERSION = "1.0.0"
REASON_CODES = {
    "IN_FLOOD_EXTENT": {
        "status": CenterStatus.POTENTIALLY_EXPOSED,
        "meaning": "The center point lies in a flooded cell (depth above 0 m) for this scenario.",
    },
    "OUTSIDE_FLOOD_EXTENT": {
        "status": CenterStatus.NOT_EXPOSED_UNDER_SCENARIO,
        "meaning": "The center point lies in a cell with 0 m flood depth for this scenario.",
    },
    "NO_FLOOD_DATA": {
        "status": CenterStatus.UNABLE_TO_ASSESS,
        "meaning": "The flood layer has no data at the center point. Not the same as not exposed.",
    },
    "OUTSIDE_HAZARD_COVERAGE": {
        "status": CenterStatus.UNABLE_TO_ASSESS,
        "meaning": "The center point is outside the area covered by the flood layer.",
    },
}


class MethodInputError(ValueError):
    """An input cannot be used by this method; the job must stop safely."""


@dataclass(frozen=True)
class CenterInput:
    feature_id: UUID
    name: str
    lon: float
    lat: float


@dataclass(frozen=True)
class CenterResult:
    feature_id: UUID
    status: str
    reason_code: str
    flood_depth_m: float | None


def centers_in_boundary(boundary_geojson: dict[str, Any], centers: list[CenterInput]):
    area = shape(boundary_geojson)
    if area.is_empty or not area.is_valid:
        raise MethodInputError("Boundary geometry is empty or invalid")
    return [center for center in centers if area.covers(Point(center.lon, center.lat))]


def classify_center(raster: Any, center: CenterInput) -> CenterResult:
    left, bottom, right, top = raster.bounds
    if not (left <= center.lon < right and bottom < center.lat <= top):
        return CenterResult(center.feature_id, CenterStatus.UNABLE_TO_ASSESS,
                            "OUTSIDE_HAZARD_COVERAGE", None)
    row, col = raster.index(center.lon, center.lat)
    values = raster.read(1, window=Window(col, row, 1, 1), masked=True)
    if values.size == 0 or np.ma.is_masked(values[0, 0]):
        return CenterResult(center.feature_id, CenterStatus.UNABLE_TO_ASSESS, "NO_FLOOD_DATA", None)
    depth = float(values[0, 0])
    if not np.isfinite(depth):
        return CenterResult(center.feature_id, CenterStatus.UNABLE_TO_ASSESS, "NO_FLOOD_DATA", None)
    if depth > 0:
        return CenterResult(center.feature_id, CenterStatus.POTENTIALLY_EXPOSED,
                            "IN_FLOOD_EXTENT", round(depth, 3))
    return CenterResult(center.feature_id, CenterStatus.NOT_EXPOSED_UNDER_SCENARIO,
                        "OUTSIDE_FLOOD_EXTENT", 0.0)


def run_center_flood_overlay(
    boundary_geojson: dict[str, Any], centers: list[CenterInput], raster: Any
) -> tuple[list[CenterInput], list[CenterResult]]:
    if raster.crs is None or raster.crs.to_epsg() != 4326:
        raise MethodInputError("Flood layer must be in EPSG:4326 for method 1.0.0")
    if raster.count < 1:
        raise MethodInputError("Flood layer has no bands")
    in_scope = centers_in_boundary(boundary_geojson, centers)
    return in_scope, [classify_center(raster, center) for center in in_scope]
