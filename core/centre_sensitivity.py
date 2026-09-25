"""Sample the shown sensitivity indicators at every current evacuation centre (ADR-0030).

Run from ``python -m grpcli.sensitivity build``, never from a web request. The value stored is the
source's own cell value at the centre's location, rounded for display. It is context for a planner
reading one centre, and nothing else: no classification, sorting, filtering, scoring or prompt may
read it.

Sampling on 25 September showed centres sit in settled areas: 0.4% fall outside coverage, a few
percent read exactly 0, and the value at the point agrees with the 250 m neighbourhood mean to
within 0.02 at every quartile. So a point sample is used, with no smoothing method to approve.
"""

from __future__ import annotations

import math
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from core.assessment_models import Dataset, DatasetVersion, Feature
from core.data_library_models import CentreIndicatorValue, DatasetFile

# Matches api.maps.WITHHELD_INDICATORS: a withheld indicator is not sampled for planners either.
SAMPLED_INDICATORS = ("child_sensitivity", "elderly_sensitivity")
DISPLAY_DECIMALS = 2


def sample_points(raster: Any, points: list[tuple[float, float]]) -> list[float | None]:
    """The raster's value at each (lon, lat), or None outside its extent or coverage."""

    from rasterio.warp import transform

    if not points:
        return []
    xs, ys = transform("EPSG:4326", raster.crs, [p[0] for p in points], [p[1] for p in points])
    left, bottom, right, top = raster.bounds
    nodata = raster.nodata
    inside = [left <= x < right and bottom < y <= top for x, y in zip(xs, ys, strict=True)]
    coordinates = [(x, y) for (x, y), keep in zip(zip(xs, ys, strict=True), inside, strict=True)
                   if keep]
    sampled = iter(float(values[0]) for values in raster.sample(coordinates))
    results: list[float | None] = []
    for keep in inside:
        if not keep:
            results.append(None)
            continue
        value = next(sampled)
        if not math.isfinite(value) or (nodata is not None and value == nodata):
            results.append(None)
        else:
            results.append(round(value, DISPLAY_DECIMALS))
    return results


def current_indicators(session: Session) -> list[tuple[UUID, str, str]]:
    """(version id, indicator key, stored source raster key) for each sampled indicator."""

    rows = session.execute(
        select(DatasetVersion.id, DatasetVersion.meta, DatasetFile.storage_key)
        .join(Dataset, Dataset.id == DatasetVersion.dataset_id)
        .join(DatasetFile, DatasetFile.dataset_version_id == DatasetVersion.id)
        .where(
            Dataset.type == "vulnerability",
            DatasetVersion.is_current,
            DatasetFile.role == "source_geotiff",
        )
    ).all()
    return [
        (version_id, str(meta.get("indicator_key")), str(key))
        for version_id, meta, key in rows
        if meta.get("indicator_key") in SAMPLED_INDICATORS
    ]


def build_centre_sensitivity(
    session: Session, storage: Any, *, centers_version_id: UUID
) -> dict[str, int]:
    """Replace this centre version's values for every current sampled indicator.

    Idempotent: the inputs are immutable versions, so a rerun writes the same rows. Returns the
    number of centres with a value per indicator key.
    """

    centres = session.execute(
        select(Feature.id, Feature.lon, Feature.lat).where(
            Feature.dataset_version_id == centers_version_id
        )
    ).all()
    if not centres:
        raise ValueError("The evacuation-centre version has no points")
    indicators = current_indicators(session)
    if not indicators:
        raise ValueError("No current child or older-person sensitivity raster is imported")
    points = [(float(lon), float(lat)) for _, lon, lat in centres]
    written: dict[str, int] = {}
    for version_id, key, raster_key in indicators:
        with storage.open_window(raster_key) as raster:
            values = sample_points(raster, points)
        session.execute(
            delete(CentreIndicatorValue).where(
                CentreIndicatorValue.centers_version_id == centers_version_id,
                CentreIndicatorValue.vulnerability_version_id == version_id,
            )
        )
        session.add_all(
            CentreIndicatorValue(
                feature_id=feature_id,
                centers_version_id=centers_version_id,
                vulnerability_version_id=version_id,
                value=value,
            )
            for (feature_id, _, _), value in zip(centres, values, strict=True)
        )
        written[key] = sum(value is not None for value in values)
    session.commit()
    return written
