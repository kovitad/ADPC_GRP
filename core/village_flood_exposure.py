"""How many people live inside a flood scenario's extent, per area (ADR-0028 slice 3).

The village points and the flood raster were both imported but never met. This samples one
against the other and aggregates the result per district and per sub-district, so a Planner asking
"how many people in this district are in the RP100 zone" gets a number GRP computed rather than an
estimate someone read off a map.

Never called from a web request. Sampling 80,397 points is worker-side work by definition
(AGENTS.md); ``grpcli exposure build`` runs it once per pair of dataset versions.

What this deliberately does not do:

* It does not interpolate. A village is a point, so it is in the zone or it is not, at the depth
  of the cell it sits in. No area-weighted share of a village's people is invented.
* It does not claim a village is dry. The delivered RP100 layer holds a depth only where the model
  produced flooding: its lowest valid value is 0.1 m and it has no zero-depth cell. So a village
  with no value is dry, outside the modelled domain, or outside the layer's coverage, and this
  data cannot separate those. Such villages go to ``no_data_village_count`` and are left out of
  both totals; only the in-zone figures are asserted.
* It does not silently drop a village whose population was unusable. Those are counted in
  ``villages_in_zone_without_population``, because otherwise people_in_zone would look complete.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.hazard_overlay import DEPTH_CLASSES

# A depth at or below this is not inside the extent, matching core/gis.classify_center, which
# treats only depth > 0 as flooded. The delivered layer carries no zero-depth cell, so in practice
# this only guards against a future layer that encodes dry as 0 rather than as nodata.
DRY_DEPTH_M = 0.0


@dataclass(frozen=True)
class VillagePoint:
    """One village as the exposure job needs it, already read from the database."""

    lon: float
    lat: float
    district_code: str | None
    subdistrict_code: str | None
    total_population: int | None
    households: int | None


@dataclass
class AreaExposure:
    """Running totals for one area. Mutated by the aggregator, then written as one row."""

    admin_code: str
    admin_level: str
    village_count: int = 0
    measured_village_count: int = 0
    no_data_village_count: int = 0
    villages_in_zone: int = 0
    people_in_zone: int = 0
    households_in_zone: int = 0
    villages_in_zone_without_population: int = 0
    depth_bands: dict[str, dict[str, int]] = field(default_factory=dict)

    def as_row(self) -> dict[str, Any]:
        return {
            "admin_code": self.admin_code,
            "admin_level": self.admin_level,
            "village_count": self.village_count,
            "measured_village_count": self.measured_village_count,
            "no_data_village_count": self.no_data_village_count,
            "villages_in_zone": self.villages_in_zone,
            "people_in_zone": self.people_in_zone,
            "households_in_zone": self.households_in_zone,
            "villages_in_zone_without_population": self.villages_in_zone_without_population,
            "depth_bands": self.depth_bands,
        }


def depth_band(depth: float) -> str | None:
    """Name the legend band a depth falls in, or None when the depth is dry.

    Bands come from core/hazard_overlay.DEPTH_CLASSES so the table and the map legend cannot
    disagree about what "1-1.5 m" means.
    """

    if depth <= DRY_DEPTH_M:
        return None
    for depth_class in DEPTH_CLASSES:
        upper = depth_class["max"]
        if depth > depth_class["min"] and (upper is None or depth <= upper):
            return str(depth_class["label"])
    return None


def _accumulate(area: AreaExposure, village: VillagePoint, depth: float | None) -> None:
    area.village_count += 1
    if depth is None:
        area.no_data_village_count += 1
        return
    area.measured_village_count += 1
    band = depth_band(depth)
    if band is None:
        return
    area.villages_in_zone += 1
    if village.total_population is None:
        area.villages_in_zone_without_population += 1
    else:
        area.people_in_zone += village.total_population
    if village.households is not None:
        area.households_in_zone += village.households
    bucket = area.depth_bands.setdefault(band, {"villages": 0, "people": 0})
    bucket["villages"] += 1
    bucket["people"] += village.total_population or 0


def aggregate_exposure(
    villages: list[VillagePoint], depths: list[float | None]
) -> list[AreaExposure]:
    """Fold sampled depths into one AreaExposure per district and per sub-district.

    ``depths`` is parallel to ``villages``; None means the village could not be measured. A village
    with no recorded area code contributes to no area, because guessing one would move people
    between districts.
    """

    if len(villages) != len(depths):
        raise ValueError("Every village needs exactly one sampled depth")
    areas: dict[tuple[str, str], AreaExposure] = {}
    for village, depth in zip(villages, depths, strict=True):
        for level, code in (
            ("district", village.district_code),
            ("subdistrict", village.subdistrict_code),
        ):
            if not code:
                continue
            area = areas.setdefault((code, level), AreaExposure(code, level))
            _accumulate(area, village, depth)
    return [areas[key] for key in sorted(areas)]


def sample_depth(rasters: list[Any], lon: float, lat: float) -> float | None:
    """Read the flood depth at one point from the first tile that covers it.

    Returns None when no tile covers the point or the cell carries nodata, which the caller records
    as unmeasured rather than dry.
    """

    import numpy as np
    from rasterio.windows import Window

    for raster in rasters:
        left, bottom, right, top = raster.bounds
        if not (left <= lon < right and bottom < lat <= top):
            continue
        row, col = raster.index(lon, lat)
        values = raster.read(1, window=Window(col, row, 1, 1), masked=True)
        if values.size == 0 or np.ma.is_masked(values[0, 0]):
            return None
        depth = float(values[0, 0])
        return depth if np.isfinite(depth) else None
    return None


def _village_points(session: Any, village_version_id: Any) -> list[VillagePoint]:
    """Read the delivered village points and their recorded population for one version."""

    from sqlalchemy import select

    from core.assessment_models import Feature

    def whole(value: Any) -> int | None:
        # The village importer stores population as text in attributes; anything that is not a
        # whole number is treated as absent rather than coerced.
        try:
            return int(str(value))
        except (TypeError, ValueError):
            return None

    rows = session.scalars(
        select(Feature).where(Feature.dataset_version_id == village_version_id)
    ).all()
    return [
        VillagePoint(
            lon=row.lon,
            lat=row.lat,
            district_code=(row.attributes or {}).get("admin_code"),
            subdistrict_code=(row.attributes or {}).get("subdistrict_code"),
            total_population=whole((row.attributes or {}).get("total_population")),
            households=whole((row.attributes or {}).get("households")),
        )
        for row in rows
    ]


def build_area_flood_exposure(
    session: Any,
    storage: Any,
    *,
    hazard_version_id: Any,
    village_version_id: Any,
    return_period_years: int,
    raster_keys: list[str],
) -> int:
    """Compute and store exposure rows for one hazard and village version pair.

    Idempotent: existing rows for the same pair are replaced, because the inputs are immutable
    versions so a rerun can only produce the same answer or a corrected one. Returns the number of
    rows written.
    """

    from contextlib import ExitStack
    from uuid import NAMESPACE_URL, uuid5

    from sqlalchemy import delete

    from core.data_library_models import AreaFloodExposure

    if not raster_keys:
        raise ValueError("The hazard version has no raster files to sample")
    villages = _village_points(session, village_version_id)
    if not villages:
        raise ValueError("The village version has no materialized points")
    with ExitStack() as stack:
        rasters = [stack.enter_context(storage.open_window(key)) for key in raster_keys]
        for raster in rasters:
            if raster.crs is None or raster.crs.to_epsg() != 4326:
                raise ValueError("Flood layer must be in EPSG:4326 to sample village points")
        depths = [sample_depth(rasters, village.lon, village.lat) for village in villages]
    areas = aggregate_exposure(villages, depths)

    session.execute(
        delete(AreaFloodExposure).where(
            AreaFloodExposure.hazard_version_id == hazard_version_id,
            AreaFloodExposure.village_version_id == village_version_id,
        )
    )
    for area in areas:
        row = area.as_row()
        session.add(
            AreaFloodExposure(
                id=uuid5(
                    NAMESPACE_URL,
                    f"grp:area-flood-exposure:{hazard_version_id}:{village_version_id}:"
                    f"{area.admin_level}:{area.admin_code}",
                ),
                hazard_version_id=hazard_version_id,
                village_version_id=village_version_id,
                return_period_years=return_period_years,
                **row,
            )
        )
    session.flush()
    return len(areas)
