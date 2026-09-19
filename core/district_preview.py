"""Preview one district's delivered source data, with its warnings (backlog Epic P).

The product owner asked to *see* the real Thailand files on a map before the blocking decisions
are made. This builds that picture in the worker (AD-03): the district outline, its shelters,
and the RP100 flood depth clipped to the district, plus the gaps that make it unfit to be a
result.

It is deliberately not an assessment. It pins no versions, uses no method, and never classifies
a shelter as "not exposed": a shelter on a no-value pixel is reported as exactly that, because
what no-value means is the open DEP-05 decision. Nothing here may reach a planner, a brief or
SIG.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from core.hazard_overlay import DEPTH_CLASSES, colourise

DISTRICTS = "administrative_boundary/district_boundary/Thailand_District_Boundaries.shp"
SHELTERS = "evacuation_centers/shelters/ddpm_shelters.shp"
FLOOD_DIR = "floods/flood_depth_rp100"
# Truncated Thai column names in the shelter shapefile (docs/thailand-dataset-inventory.md).
SHELTER_NAME = "สถ_1"
SHELTER_PLACE = "สถา"
SHELTER_DISTRICT = "อำเ"
SHELTER_PROVINCE = "จัง"
DEEP_WATER_M = 10.0
# Outline simplification for the browser, in degrees (about 50 m). Display only.
OUTLINE_TOLERANCE = 0.0005
# The largest flood picture drawn, in pixels on its longer side.
MAX_PICTURE_PX = 2000
# Hatching for no-value pixels inside the district, so "no data" never reads as "dry".
HATCH_RGBA = (150, 60, 160, 150)

LABEL = "Delivered data preview — not a GRP assessment"


class PreviewError(ValueError):
    """The request cannot be answered from these files (for example, no such district)."""


def _columns(meta: dict[str, Any], fields: Any) -> dict[str, Any]:
    return {key: values for key, values in zip(meta["fields"], fields, strict=False)}


def _text(value: Any) -> str:
    return str(value or "").strip()


def find_district(root: Path, query: str) -> dict[str, Any]:
    """Match an English name, Thai name or admin code. Several matches return the candidates."""

    from pyogrio.raw import read as read_vector
    from shapely import from_wkb

    meta, _, geometries, fields = read_vector(root / DISTRICTS, read_geometry=True)
    columns = _columns(meta, fields)
    wanted = query.strip().lower()
    matches = []
    for index in range(len(columns["NAME2"])):
        codes = {_text(columns["ADMIN_ID2"][index]).lower()}
        names = {_text(columns["NAME2"][index]).lower(), _text(columns["NAME_ENG2"][index]).lower()}
        if wanted in codes or wanted in names:
            matches.append(index)
    if not matches:
        raise PreviewError(f"No district called “{query}” in the boundary file.")

    def describe(index: int) -> dict[str, Any]:
        return {
            "admin_code": _text(columns["ADMIN_ID2"][index]),
            "name_th": _text(columns["NAME2"][index]),
            "name_en": _text(columns["NAME_ENG2"][index]).title(),
            "province_th": _text(columns["NAME1"][index]),
            "province_en": _text(columns["NAME_ENG1"][index]).title(),
            "edition": _text(columns["VERSION"][index]),
        }

    if len(matches) > 1:
        return {"candidates": [describe(index) for index in matches]}
    index = matches[0]
    return {**describe(index), "geometry": from_wkb(geometries[index])}


def _shelters(
    root: Path, area: Any, district_th: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Shelters inside the outline, and shelters that name this district but lie elsewhere."""

    from pyogrio.raw import read as read_vector
    from shapely import from_wkb
    from shapely.prepared import prep

    meta, _, geometries, fields = read_vector(root / SHELTERS, read_geometry=True)
    columns = _columns(meta, fields)
    inside_area = prep(area)
    inside: list[dict[str, Any]] = []
    elsewhere: list[dict[str, Any]] = []
    for index, raw in enumerate(geometries):
        if raw is None:
            continue
        point = from_wkb(raw)
        if point.is_empty:
            continue
        named = _text(columns[SHELTER_DISTRICT][index])
        row = {
            "name": _text(columns[SHELTER_NAME][index])
            or _text(columns[SHELTER_PLACE][index])
            or "unnamed",
            "named_district": named,
            "named_province": _text(columns[SHELTER_PROVINCE][index]),
            "lon": round(point.x, 6),
            "lat": round(point.y, 6),
        }
        if inside_area.covers(point):
            row["names_this_district"] = named == district_th
            inside.append(row)
        elif named == district_th:
            elsewhere.append(row)
    return inside, elsewhere


def _flood(
    root: Path, area: Any, shelters: list[dict[str, Any]], storage, key: str
) -> dict[str, Any]:
    """Sample each shelter and draw the flood depth clipped to the district."""

    import numpy as np
    import rasterio
    from rasterio.features import geometry_mask
    from rasterio.merge import merge
    from rasterio.windows import Window

    tiles = sorted((root / FLOOD_DIR).glob("*_depth.tif"))
    west, south, east, north = area.bounds
    covering = []
    for path in tiles:
        with rasterio.open(path) as raster:
            if raster.crs is None or raster.crs.to_epsg() != 4326:
                continue  # never place a raster we would have to reproject
            b = raster.bounds
            if b.left < east and b.right > west and b.bottom < north and b.top > south:
                covering.append(path)

    for shelter in shelters:
        shelter["flood"] = "outside_tiles"
        shelter["depth_m"] = None
        for path in covering:
            with rasterio.open(path) as raster:
                b = raster.bounds
                if not (b.left <= shelter["lon"] < b.right and b.bottom < shelter["lat"] <= b.top):
                    continue
                row, col = raster.index(shelter["lon"], shelter["lat"])
                value = raster.read(1, window=Window(col, row, 1, 1), masked=True)
                if value.size == 0 or np.ma.is_masked(value[0, 0]):
                    shelter["flood"] = "no_value"
                else:
                    shelter["depth_m"] = round(float(value[0, 0]), 2)
                    shelter["flood"] = "on_flood_pixel" if value[0, 0] > 0 else "zero_depth"
                break

    if not covering:
        return {"available": False, "reason": "No flood tile covers this district."}

    depth, transform = merge(
        [str(p) for p in covering], bounds=(west, south, east, north), nodata=-9999.0
    )
    depth = depth[0]
    outside = geometry_mask([area.__geo_interface__], out_shape=depth.shape, transform=transform)
    no_value = (depth == -9999.0) & ~outside
    rgba = colourise(np.where(no_value, 0, depth), np.zeros_like(no_value))
    rows, cols = np.indices(depth.shape)
    hatch = no_value & (((rows + cols) % 6) < 2)
    for band in range(4):
        rgba[band][no_value] = 0
        rgba[band][hatch] = HATCH_RGBA[band]
        rgba[band][outside] = 0

    step = max(1, int(np.ceil(max(depth.shape) / MAX_PICTURE_PX)))
    rgba = rgba[:, ::step, ::step]
    inside_pixels = int((~outside).sum())
    stats = {
        "pixels_in_district": inside_pixels,
        "no_value_share": round(float(no_value.sum()) / inside_pixels, 3)
        if inside_pixels
        else None,
        "flooded_share": (
            round(float(((depth > 0) & ~no_value & ~outside).sum()) / inside_pixels, 3)
            if inside_pixels
            else None
        ),
        "deep_water_share": (
            round(float(((depth >= DEEP_WATER_M) & ~no_value & ~outside).sum()) / inside_pixels, 3)
            if inside_pixels
            else None
        ),
    }
    with tempfile.TemporaryDirectory() as folder:
        png = Path(folder) / "flood.png"
        with rasterio.open(
            png,
            "w",
            driver="PNG",
            width=rgba.shape[2],
            height=rgba.shape[1],
            count=4,
            dtype="uint8",
        ) as out:
            out.write(rgba)
        storage.put(key, png)
    top, left = transform.f, transform.c
    bottom = top + transform.e * depth.shape[0]
    right = left + transform.a * depth.shape[1]
    return {
        "available": True,
        "image_key": key,
        # Leaflet order: [[south, west], [north, east]].
        "bounds": [[bottom, left], [top, right]],
        "tiles": [p.name for p in covering],
        "classes": [{"label": c["label"], "rgba": c["rgba"]} for c in DEPTH_CLASSES],
        "no_value": {"label": "No value — meaning undecided (DEP-05)", "rgba": list(HATCH_RGBA)},
        **stats,
    }


def _warnings(counts: dict[str, int], flood: dict[str, Any]) -> list[dict[str, str]]:
    """Plain-words warnings for what is on the map: what, why it matters, what it waits on."""

    notes: list[dict[str, str]] = []
    if counts["on_no_value_pixel"] or (flood.get("no_value_share") or 0) > 0:
        share = flood.get("no_value_share")
        notes.append(
            {
                "grade": "blocker",
                "title": f"{counts['on_no_value_pixel']} shelter(s) sit on a no-value flood pixel"
                + (f"; {share:.0%} of the district has no value" if share is not None else ""),
                "why": "No-value could mean “not flooded” or “never modelled”. The two readings "
                "give opposite answers for these shelters, so they are shown hatched, not as dry.",
                "waits_on": "DEP-05: what an absent flood value means, and a modelled-area mask",
            }
        )
    if counts["deep_water"]:
        notes.append(
            {
                "grade": "problem",
                "title": f"{counts['deep_water']} shelter(s) sit in water deeper than "
                f"{DEEP_WATER_M:.0f} m",
                "why": "Depths like this are usually a river or reservoir, not flooding. Until "
                "permanent water is masked they overstate exposure.",
                "waits_on": "Permanent-water threshold decision (backlog A8)",
            }
        )
    if counts["names_other_district"]:
        notes.append(
            {
                "grade": "problem",
                "title": f"{counts['names_other_district']} shelter(s) inside this outline name "
                "another district",
                "why": "Either the point or the name is wrong. A loader must report these, "
                "never silently move them.",
                "waits_on": "DDPM correction (backlog A2 follow-up)",
            }
        )
    if counts["named_here_but_elsewhere"]:
        notes.append(
            {
                "grade": "problem",
                "title": f"{counts['named_here_but_elsewhere']} shelter(s) name this district "
                "but lie outside it",
                "why": "People told to go to these shelters may be sent the wrong way. They are "
                "drawn in orange where their coordinates put them.",
                "waits_on": "DDPM correction (backlog A2 follow-up)",
            }
        )
    if counts["outside_tiles"]:
        notes.append(
            {
                "grade": "problem",
                "title": f"{counts['outside_tiles']} shelter(s) fall outside every flood tile",
                "why": "There is no flood information at all for these points.",
                "waits_on": "Flood provider coverage (DEP-05)",
            }
        )
    if not counts["in_district"]:
        notes.append(
            {
                "grade": "problem",
                "title": "No shelter lies inside this district",
                "why": "Either the district has none or they are misplaced; the shelter file "
                "cannot tell which.",
                "waits_on": "DDPM (backlog A2 follow-up)",
            }
        )
    notes.append(
        {
            "grade": "known",
            "title": "Shelter columns สถา and รอง are not shown",
            "why": "Their meaning has not been confirmed, so showing them could mislead.",
            "waits_on": "DEP-06",
        }
    )
    return notes


def build_preview(root: Path, query: str, storage, image_key: str) -> dict[str, Any]:
    """Return the preview report for one district, or its candidates when the name is shared."""

    from shapely import simplify

    found = find_district(root, query)
    if "candidates" in found:
        return {"kind": "district_preview", "label": LABEL, "query": query, **found}
    area = found.pop("geometry")
    shelters, elsewhere = _shelters(root, area, found["name_th"])
    flood = _flood(root, area, shelters, storage, image_key)
    counts = {
        "in_district": len(shelters),
        "on_flood_pixel": sum(s["flood"] == "on_flood_pixel" for s in shelters),
        "zero_depth": sum(s["flood"] == "zero_depth" for s in shelters),
        "on_no_value_pixel": sum(s["flood"] == "no_value" for s in shelters),
        "outside_tiles": sum(s["flood"] == "outside_tiles" for s in shelters),
        "deep_water": sum((s["depth_m"] or 0) >= DEEP_WATER_M for s in shelters),
        "names_other_district": sum(not s["names_this_district"] for s in shelters),
        "named_here_but_elsewhere": len(elsewhere),
    }
    return {
        "kind": "district_preview",
        "label": LABEL,
        "query": query,
        "district": found,
        "outline": simplify(area, OUTLINE_TOLERANCE, preserve_topology=True).__geo_interface__,
        "shelters": shelters,
        "shelters_elsewhere": elsewhere,
        "counts": counts,
        "flood": flood,
        "warnings": _warnings(counts, flood),
    }
