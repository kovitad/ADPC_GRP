"""Prepare every local test dataset as a Global Risk contribution, without submitting any.

Reads `.local/data-in/` and writes `.local/data-out/` with the same folder structure. Each
contributable folder gets the converted file, `manifest.yaml` (to paste into Claude Desktop),
`manifest.json` (the values for GRP's Share data form) and `TEST.md` (what to ask afterwards
and GRP's own numbers to compare). A folder that cannot be contributed gets a `README.md`
saying why.

Nothing here calls Global Risk. Global Risk auto-approves, so a submit is public at once
(ADR-0032); submitting is the tester's decision.

    python scripts/prepare_global_risk_contributions.py points tables compare
    python scripts/prepare_global_risk_contributions.py flood
    python scripts/prepare_global_risk_contributions.py vulnerability   # slow: 2 x 9 Gpx
    python scripts/prepare_global_risk_contributions.py population
    python scripts/prepare_global_risk_contributions.py drive check   # the Google Drive kit
"""

from __future__ import annotations

import csv
import io
import json
import math
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pyogrio
import pyogrio.raw
import rasterio
import shapely
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT
from rasterio.warp import Resampling
from rasterio.windows import Window, from_bounds

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.contribution_rules import check_manifest, check_point_file  # noqa: E402

DATA_IN = ROOT / ".local" / "data-in"
DATA_OUT = ROOT / ".local" / "data-out"

# The flood tiles' grid (JRC, 3 arc-seconds). Every raster here is written on it, clipped to
# Thailand, so pixels line up with each other and with GRP's own flood reads.
RES = 1 / 1200
# Global Risk's live 100-year legend, as its own answers state it (29 Sep 2026). The runbook
# says 1.5-2.5 m and > 2.5 m for classes 4 and 5; the live layer wins so classes agree.
DEPTH_BANDS = [(0.5, 1), (1.0, 2), (1.5, 3), (2.0, 4), (math.inf, 5)]
DEPTH_LEGEND = {1: "Very low (<= 0.5 m)", 2: "Low (0.5-1 m)", 3: "Moderate (1-1.5 m)",
                4: "High (1.5-2 m)", 5: "Very high (> 2 m)"}
QUINTILE_LEGEND = {1: "Very low", 2: "Low", 3: "Moderate", 4: "High", 5: "Very high"}
GTIFF = {"driver": "GTiff", "compress": "deflate", "tiled": True, "blockxsize": 512,
         "blockysize": 512, "predictor": 1, "BIGTIFF": "IF_SAFER"}

# Districts to compare, with the Global Risk place name planners ask about.
COMPARE = [
    ("Samko", "SAMKO District, ANG THONG, Thailand"),
    ("Tha Pla", "THA PLA District, UTTARADIT, Thailand"),
    ("Ban Khok", "BAN KHOK District, UTTARADIT, Thailand"),
    ("Bang Kapi", "BANG KAPI District, BANGKOK, Thailand"),
    ("Bang Bua Thong", "BANG BUA THONG District, NONTHABURI, Thailand"),
]

URL = "https://drive.google.com/uc?export=download&id=<FILE_ID>"
UNCONFIRMED = ("Licence and vintage are not confirmed by the data owner; 'unstated' and the "
               "delivery month are used until they are.")


# ---------- helpers ----------

def clean(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and value != value:
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, str):
        value = value.strip()
        if value.lower() in {"", "null", "none", "nan", "-"}:
            return None
    return value


def to_int(value: Any) -> int | None:
    value = clean(value)
    try:
        return int(float(value)) if value is not None else None
    except (TypeError, ValueError):
        return None


def read_raw(path: Path, **options):
    """A shapefile read; a few truncated UTF-8 values are recovered as core/dataset_scan does."""

    try:
        return pyogrio.raw.read(path, **options)
    except UnicodeDecodeError:
        result = pyogrio.raw.read(path, encoding="ISO-8859-1", **options)
        for column in result[3]:
            if getattr(column, "dtype", None) is not None and column.dtype == object:
                for index, value in enumerate(column):
                    if isinstance(value, str):
                        column[index] = value.encode("ISO-8859-1").decode("utf-8", "replace")
        return result


# GRP's rule (core/thailand_full_import.py): a village's counts are used only when male + female
# equals the total and the total is a plausible village size; otherwise they are left out.
MAX_PLAUSIBLE_VILLAGE_POPULATION = 100_000


def village_population(record: dict) -> dict[str, int]:
    male, female = to_int(record["oct_side_9"]), to_int(record["oct_side10"])
    total, households = to_int(record["oct_side11"]), to_int(record["oct_side12"])
    if None in (male, female, total) or male + female != total:
        return {}
    if not 0 < total <= MAX_PLAUSIBLE_VILLAGE_POPULATION:
        return {}
    counts = {"male": male, "female": female, "total_population": total}
    if households is not None:
        counts["households"] = households
    return counts


def read_points(relative: str) -> tuple[list[dict], list[tuple[float, float]]]:
    meta, _, wkb, columns = read_raw(DATA_IN / relative)
    rows = [dict(zip(meta["fields"], values, strict=True))
            for values in zip(*columns, strict=True)]
    xy = [tuple(map(float, p)) for p in shapely.get_coordinates(shapely.from_wkb(wkb))]
    return rows, xy


def write_geojson(path: Path, name: str, rows: list[dict], xy: list[tuple[float, float]]) -> None:
    features = [
        {"type": "Feature",
         "geometry": {"type": "Point", "coordinates": [round(x, 7), round(y, 7)]},
         "properties": {k: v for k, v in row.items() if v is not None}}
        for row, (x, y) in zip(rows, xy, strict=False)
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"type": "FeatureCollection", "name": name, "features": features},
                               ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def yaml_value(value: Any, indent: int = 0) -> str:
    pad = " " * indent
    if isinstance(value, dict):
        return "\n" + "\n".join(f"{pad}  {json.dumps(str(k), ensure_ascii=False)}: "
                                f"{yaml_value(v, indent + 2).lstrip()}" for k, v in value.items())
    if isinstance(value, list):
        return "[" + ", ".join(json.dumps(v, ensure_ascii=False) for v in value) + "]"
    if isinstance(value, bool | int | float):
        return json.dumps(value)
    text = str(value)
    if "\n" in text:
        return "|\n" + "\n".join(f"{pad}  {line}" for line in text.splitlines())
    return json.dumps(text, ensure_ascii=False)


def write_manifest(folder: Path, kind: str, manifest: dict[str, Any], header: str) -> None:
    checked = check_manifest(kind, manifest)
    if checked.problems:
        raise SystemExit(f"{folder}: GRP's own check refused the manifest: {checked.problems}")
    folder.mkdir(parents=True, exist_ok=True)
    lines = [f"# {line}" for line in header.strip().splitlines()]
    lines += [f"kind: {kind}"]
    lines += [f"{key}: {yaml_value(value)}" for key, value in manifest.items()]
    (folder / "manifest.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (folder / "manifest.json").write_text(
        json.dumps({"kind": kind, "manifest": manifest}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def size_mb(path: Path) -> float:
    return round(path.stat().st_size / 1_048_576, 1)


def thailand_grid() -> tuple[Any, int, int]:
    info = pyogrio.read_info(
        DATA_IN / "administrative_boundary/nation_boundary/Thailand_Boundaries.shp")
    west, south, east, north = info["total_bounds"]
    # Snap outwards onto the flood tiles' grid (origin at the tiles' west/north edges).
    origin_x, origin_y = 89.9766667, 30.0050000
    with rasterio.open(next((DATA_IN / "floods/flood_depth_rp100").glob("*.tif"))) as tile:
        origin_x, origin_y = tile.bounds.left, tile.bounds.top
    col0 = math.floor((west - origin_x) / RES)
    col1 = math.ceil((east - origin_x) / RES)
    row0 = math.floor((origin_y - north) / RES)
    row1 = math.ceil((origin_y - south) / RES)
    transform = from_origin(origin_x + col0 * RES, origin_y - row0 * RES, RES, RES)
    return transform, col1 - col0, row1 - row0


def blocks(width: int, height: int, size: int = 2048):
    for row in range(0, height, size):
        for col in range(0, width, size):
            yield Window(col, row, min(size, width - col), min(size, height - row))


# ---------- points ----------

def points() -> None:
    # Shelters: the allow-list from .local/prepare_sig_shelters.py. The truncated Thai fields
    # ชื่ and หมา are a contact name and a phone number and are never read.
    rows, xy = read_points("evacuation_centers/shelters/ddpm_shelters.shp")
    at = Counter(xy)
    shelters = []
    for row, point in zip(rows, xy, strict=False):
        source_id = to_int(row["ที่"])
        facility, unit = clean(row["สถา"]), clean(row["สถ_1"])
        capacity = to_int(row["รอง"])
        shelters.append({
            "centre_id": f"DDPM-SHELTER-{source_id}",
            "name": facility or unit or f"DDPM shelter {source_id}",
            "facility": facility, "supporting_unit": unit,
            "capacity": capacity if capacity else None,
            "region": clean(row["ภาค"]), "province": clean(row["จัง"]),
            "district": clean(row["อำเ"]), "subdistrict": clean(row["ตำบ"]),
            "village": clean(row["หมู"]),
            "records_at_coordinate": at[point] if at[point] > 1 else None,
        })
    repeated = sum(1 for p in xy if at[p] > 1)
    folder = DATA_OUT / "evacuation_centers/shelters"
    write_geojson(folder / "evacuation_centres_ddpm.geojson", "evacuation_centres_ddpm",
                  shelters, xy)
    write_manifest(folder, "vector", {
        "layer": "evacuation_centres_ddpm", "url": URL,
        "title": "Evacuation centres, Thailand (DDPM)",
        "description": (f"One point per evacuation-centre record supplied by DDPM "
                        f"({len(xy):,} records), with capacity where greater than zero. Contact "
                        "names and telephone numbers are excluded."),
        "source": "Thailand DDPM, compiled by ADPC", "license": "unstated", "vintage": "2026-09",
        "countries": ["Thailand"], "name_field": "name",
        "usage_notes": (f"{repeated:,} records share a coordinate with another record, some across "
                        "districts; counts may include duplicates until DDPM confirms them. "
                        + UNCONFIRMED)[:500],
    }, "GRP's own evacuation centres (the same records GRP assesses). Layer name differs from\n"
       "the 24 Sep test layer evacuation_centres_th_test; withdraw that one first or every\n"
       "centre is counted twice in Global Risk answers.")

    # Early-warning towers.
    rows, xy = read_points(
        "evacuation_centers/earlywarning_resources/ddpm_earlywarning_resources.shp")
    towers = [{
        "code": clean(r["Code"]), "name": clean(r["Location"]) or clean(r["Code"]),
        "equipment": clean(r["Equipment"]), "subdistrict": clean(r["Subdistric"]),
        "district": clean(r["District"]), "province": clean(r["Province"]),
    } for r in rows]
    folder = DATA_OUT / "evacuation_centers/earlywarning_resources"
    write_geojson(folder / "early_warning_towers_ddpm.geojson", "early_warning_towers_ddpm",
                  towers, xy)
    write_manifest(folder, "vector", {
        "layer": "early_warning_towers_ddpm", "url": URL,
        "title": "Early-warning towers and equipment, Thailand (DDPM)",
        "description": f"One point per DDPM early-warning resource ({len(xy):,}), mostly warning "
                       "towers, with the site name and administrative area.",
        "source": "Thailand DDPM, compiled by ADPC", "license": "unstated", "vintage": "2026-09",
        "countries": ["Thailand"], "name_field": "name",
        "usage_notes": "Counts tell you how many warning points sit in the flood hazard layer, "
                       "i.e. which may be damaged or unreachable in a 100-year flood. "
                       + UNCONFIRMED,
    }, "DDPM early-warning towers. GRP shows these as a supporting map layer.")

    # Civil-defence volunteer centres: TEL, FAX, EMAIL and the street address never leave GRP.
    rows, xy = read_points(
        "evacuation_centers/volunteer_center/ddpm_civil_defense_volunteer_center.shp")
    centres = [{
        "center_id": to_int(r["CENTER_ID"]), "name": clean(r["NAME"]),
        "type": clean(r["TYPE_DESC"]), "province": clean(r["PROVINCE_N"]),
        "district": clean(r["AMPHUR_NAM"]), "subdistrict": clean(r["DISTRICT_N"]),
        "subdistrict_code": clean(r["DISTRICT_I"]),
    } for r in rows]
    folder = DATA_OUT / "evacuation_centers/volunteer_center"
    write_geojson(folder / "civil_defence_volunteer_centres_ddpm.geojson",
                  "civil_defence_volunteer_centres_ddpm", centres, xy)
    write_manifest(folder, "vector", {
        "layer": "civil_defence_volunteer_centres_ddpm", "url": URL,
        "title": "Civil-defence volunteer (OPPR) centres, Thailand (DDPM)",
        "description": f"One point per civil-defence volunteer centre ({len(xy):,}) with its type "
                       "and administrative area. Telephone, fax, e-mail and street address are "
                       "excluded.",
        "source": "Thailand DDPM, compiled by ADPC", "license": "unstated", "vintage": "2026-09",
        "countries": ["Thailand"], "name_field": "name",
        "usage_notes": "Response capacity, not shelter: a centre in the hazard layer may itself "
                       "be cut off. " + UNCONFIRMED,
    }, "Civil-defence volunteer centres, with every contact field removed.")

    # Villages with registered population (field mapping from core/thailand_full_import.py).
    rows, xy = read_points("administrative_boundary/village/village.shp")
    # A few villages carry projected metres (UTM) instead of degrees; they cannot be placed.
    lonlat = [(-180 <= x <= 180 and -90 <= y <= 90) for x, y in xy]
    dropped = [(r, p) for r, p, ok in zip(rows, xy, lonlat, strict=False) if not ok]
    rows = [r for r, ok in zip(rows, lonlat, strict=False) if ok]
    xy = [p for p, ok in zip(xy, lonlat, strict=False) if ok]
    villages = [{
        "village_code": clean(r["mcode"]), "name": clean(r["mname"]),
        "subdistrict": clean(r["tname"]), "district": clean(r["aname"]),
        "province": clean(r["pname"]), "district_code": clean(r["acode"]),
        **village_population(r),
    } for r in rows]
    untrusted = sum(1 for v in villages if "total_population" not in v)
    folder = DATA_OUT / "administrative_boundary/village"
    write_geojson(folder / "villages_th_register.geojson", "villages_th_register", villages, xy)
    people = sum(v.get("total_population", 0) for v in villages)
    write_manifest(folder, "vector", {
        "layer": "villages_th_register", "url": URL,
        "title": "Villages with registered population, Thailand",
        "description": f"One point per village ({len(xy):,}) with registered male, female and "
                       f"total population and households ({people:,} people in all).",
        "source": "Thailand village register, delivered to ADPC", "license": "unstated",
        "vintage": "2026-09", "countries": ["Thailand"], "name_field": "name",
        # Global Risk and GRP refuse more than 500 characters; never cut a sentence short.
        "usage_notes": (f"{untrusted} villages whose male + female does not equal the total, or "
                        "whose total is implausible, carry no population (GRP's rule). "
                        f"{len(dropped)} villages with projected coordinates are left out. "
                        "Global Risk counts villages, not people; see "
                        "population_th_village_register for a headcount. Population is where "
                        "people are registered, not where they are. " + UNCONFIRMED),
    }, "Village points. Global Risk will count villages in the hazard layer, not people.")
    with (folder / "villages_left_out.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream)
        writer.writerow(["village_code", "name", "province", "district", "x", "y"])
        for r, (x, y) in dropped:
            writer.writerow([clean(r["mcode"]), clean(r["mname"]), clean(r["pname"]),
                             clean(r["aname"]), x, y])
    print("points written")


# ---------- tables ----------

def tables() -> None:
    meta, _, _, columns = read_raw(
        DATA_IN / "administrative_boundary/sub-district_boundary"
        / "Thailand_SubDistrict_Boundaries.dbf.shp",
        read_geometry=False)
    rows = [dict(zip(meta["fields"], values, strict=True))
            for values in zip(*columns, strict=True)]
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["Subdistrict_code", "Subdistrict", "District", "Province", "Pop_year",
                     "Population", "Male", "Female", "Households"])
    for r in rows:
        writer.writerow([clean(r["ADMIN_ID3"]), clean(r["NAME_ENG3"]), clean(r["NAME_ENG2"]),
                         clean(r["NAME_ENG1"]), to_int(r["POP_YEAR"]), to_int(r["POPULATION"]),
                         to_int(r["MALE"]), to_int(r["FEMALE"]), to_int(r["HOUSE"])])
    folder = DATA_OUT / "administrative_boundary/sub-district_boundary"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "th_subdistrict_population.csv").write_text(out.getvalue(), encoding="utf-8")
    years = sorted({to_int(r["POP_YEAR"]) for r in rows} - {None})
    write_manifest(folder, "table", {
        "dataset": "th_subdistrict_population",
        "title": "Registered population by sub-district, Thailand",
        "description": f"Registered population, male, female and households for {len(rows):,} "
                       "sub-districts, with English names and codes.",
        "source": "Thailand sub-district boundary delivery (DOPA register)",
        "validation": "official-statistic", "license": "unstated",
        "vintage": f"{years[-1]}-01" if years else "2026-09", "cadence": "annual",
        "columns": {"subdistrict_code": "Subdistrict_code", "subdistrict": "Subdistrict",
                    "district": "District", "province": "Province", "population": "Population",
                    "male": "Male", "female": "Female", "households": "Households",
                    "pop_year": "Pop_year"},
        # No as_of_field: Pop_year is a year, not a date, and as_of_field names an output field.
        "units": "people (households for households); pop_year is the register year",
        "url": URL, "pack": "risk",
        "usage_notes": "A lookup table: it reaches answers through feeds_query only and never "
                       "enters Global Risk's exposure counts. " + UNCONFIRMED,
    }, "A table reaches Global Risk's feeds_query, never its exposure counts.")
    for name in ("district_boundary", "nation_boundary", "province_boundary"):
        write_text(DATA_OUT / "administrative_boundary" / name / "README.md", f"""
# {name}: not contributable

Global Risk has no boundary contribution kind (runbook section 10). It resolves every place from
OpenStreetMap, so its "Tha Pla District" is an OpenStreetMap polygon, not this DOPA polygon.
GRP keeps using this file. `compare/district_comparison.md` shows how much the two areas
differ for the test districts; a difference in counts can come from the boundary alone.
""")
    print("tables written")


# ---------- flood ----------

def flood() -> None:
    transform, width, height = thailand_grid()
    folder = DATA_OUT / "floods/flood_depth_rp100"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "hazard_flood_thailand_rp100.tif"
    tiles = [rasterio.open(p) for p in sorted((DATA_IN / "floods/flood_depth_rp100").glob("*.tif"))]
    counts = Counter()
    profile = {**GTIFF, "dtype": "uint8", "count": 1, "width": width, "height": height,
               "crs": "EPSG:4326", "transform": transform, "nodata": 0}
    with rasterio.open(target, "w", **profile) as out:
        for window in blocks(width, height):
            bounds = rasterio.windows.bounds(window, transform)
            depth = np.full((window.height, window.width), np.nan, dtype="float32")
            for tile in tiles:
                if (tile.bounds.right <= bounds[0] or tile.bounds.left >= bounds[2]
                        or tile.bounds.top <= bounds[1] or tile.bounds.bottom >= bounds[3]):
                    continue
                source = from_bounds(*bounds, tile.transform).round_offsets().round_lengths()
                part = tile.read(1, window=source, boundless=True, fill_value=tile.nodata,
                                 out_shape=(window.height, window.width))
                valid = part != tile.nodata
                depth[valid] = part[valid]
            classes = np.zeros(depth.shape, dtype="uint8")
            lower = 0.0
            for upper, value in DEPTH_BANDS:
                classes[(depth > lower) & (depth <= upper)] = value
                lower = upper
            counts.update(dict(zip(*np.unique(classes, return_counts=True), strict=False)))
            out.write(classes, 1, window=window)
    for tile in tiles:
        tile.close()
    mb = size_mb(target)
    write_manifest(folder, "raster", {
        "layer": "hazard_flood_thailand_rp100", "url": URL,
        "title": "Flood depth, 1-in-100 year, Thailand (JRC tiles, reclassed 1-5)",
        "description": "The 100-year flood-depth tiles GRP assesses with, clipped to Thailand and "
                       "reclassed to five depth bands matching Global Risk's live flood legend. "
                       "0 means dry or no data: the source does not tell them apart.",
        "source": "JRC Global Flood Hazard Maps (RP100 depth tiles), as delivered to ADPC",
        "license": "unstated", "vintage": "2026-09",
        "legend": {str(k): v for k, v in DEPTH_LEGEND.items()},
        "declared": {"dtype": "uint8", "valid_min": 0, "valid_max": 5, "nodata": 0},
        "usage_notes": "Likely the same model as Global Risk's hazard_flood (derived from JRC "
                       "GLOFAS v2.1): use it to test that both engines agree on identical input, "
                       "not as new evidence. No risk recipe exists for flood_thailand until a "
                       "weights contribution adds one.",
    }, "OPTIONAL. Probably duplicates Global Risk's own flood layer (JRC-derived). Useful only\n"
       f"to prove both engines give the same count on identical input. File: {mb} MB.")
    (folder / "class_counts.json").write_text(json.dumps(
        {str(k): int(v) for k, v in sorted(counts.items())}, indent=2), encoding="utf-8")
    print(f"flood written: {mb} MB", dict(sorted(counts.items())))


# ---------- vulnerability ----------

def vulnerability() -> None:
    transform, width, height = thailand_grid()
    for source_name, layer, title in (
        ("childSensitivity_01", "vulnerability_child_sensitivity_th", "children"),
        ("elderlySensitivity_01", "vulnerability_elderly_sensitivity_th", "older people"),
    ):
        folder = DATA_OUT / "vulnerable_people"
        folder.mkdir(parents=True, exist_ok=True)
        average = folder / f"{source_name}_avg_4326.tif"
        with rasterio.open(DATA_IN / "vulnerable_people" / f"{source_name}.tif") as src:
            with WarpedVRT(src, crs="EPSG:4326", transform=transform, width=width, height=height,
                           resampling=Resampling.average, src_nodata=np.nan, nodata=np.nan,
                           warp_mem_limit=512) as vrt, rasterio.open(
                    average, "w", **{**GTIFF, "predictor": 3, "dtype": "float32", "count": 1,
                                     "width": width, "height": height, "crs": "EPSG:4326",
                                     "transform": transform, "nodata": np.nan}) as out:
                for n, window in enumerate(blocks(width, height)):
                    out.write(vrt.read(1, window=window), 1, window=window)
                    if n % 20 == 0:
                        print(f"  {source_name}: block {n}", flush=True)
        # Quintiles over positive values. 0 (no sensitivity) joins class 1; outside Thailand is 0.
        with rasterio.open(average) as src:
            sample = src.read(1, out_shape=(1, height // 4, width // 4))
        positive = sample[np.isfinite(sample) & (sample > 0)]
        breaks = np.quantile(positive, [0.2, 0.4, 0.6, 0.8]).astype("float32")
        target = folder / f"{layer}.tif"
        with rasterio.open(average) as src, rasterio.open(
                target, "w", **{**GTIFF, "dtype": "uint8", "count": 1, "width": width,
                                "height": height, "crs": "EPSG:4326", "transform": transform,
                                "nodata": 0}) as out:
            for window in blocks(width, height):
                value = src.read(1, window=window)
                classes = np.where(np.isfinite(value),
                                   np.digitize(value, breaks) + 1, 0).astype("uint8")
                out.write(classes, 1, window=window)
        average.unlink()
        mb = size_mb(target)
        write_manifest(folder / layer, "raster", {
            "layer": layer, "url": URL,
            "title": f"Sensitivity of {title}, Thailand (relative index, quintiles 1-5)",
            "description": f"Relative sensitivity index for {title} (0-1, 12.5 m), averaged to the "
                           "flood grid and reclassed into quintiles of the non-zero values; 0 "
                           "means no data. A relative index, not a headcount.",
            "source": "ADPC vulnerable-people sensitivity layers, as delivered", "license":
            "unstated", "vintage": "2026-09",
            "legend": {str(k): v for k, v in QUINTILE_LEGEND.items()},
            "declared": {"dtype": "uint8", "valid_min": 0, "valid_max": 5, "nodata": 0},
            "usage_notes": "Quintile breaks " + ", ".join(f"{b:.3f}" for b in breaks)
                           + " over non-zero values; index 0 (no sensitivity) is class 1. GRP "
                           "shows this index for display only (ADR-0030). " + UNCONFIRMED,
        }, f"Relative sensitivity of {title}. Only takes part in risk levels through a weights\n"
           f"contribution. File: {mb} MB.")
        target.replace(folder / layer / target.name)
        write_text(folder / layer / "TEST.md", f"""
# Foundation check: sensitivity of {title}

Load `{target.name}` as a separate EPSG:4326 display/foundation raster. It contains uint8
quintile classes 1–5 and NoData 0, aligned to the flood grid. The non-zero source-index breaks are
{", ".join(f"{value:.3f}" for value in breaks)}.

This is a relative index, not a headcount, exposure result or risk score. Before a later public
contribution, confirm source meaning, licence and vintage, put the direct file URL in
`manifest.yaml`, and run GRP **Check**. Do not add weights without a separate approved scoring
decision.
""")
        print(f"{layer} written: {mb} MB, breaks {breaks.round(3).tolist()}")
    disability_source = DATA_IN / "vulnerable_people/disability_total.tif"
    disability_folder = DATA_OUT / "vulnerable_people/vulnerability_disability_class_th"
    write_manifest(disability_folder, "raster", {
        "layer": "vulnerability_disability_class_th", "url": URL,
        "title": "Disability support indicator class, Thailand",
        "description": (
            "Source ordinal disability-support indicator at 12.5 m resolution. Values 1-4 are "
            "source classes, not numbers of people, percentages, exposure or flood risk. The "
            "source did not provide meanings or direction for the classes."
        ),
        "source": "ADPC Data Science Thailand delivery", "license": "unstated",
        "vintage": "2026-09",
        "legend": {str(value): f"Source class {value}; meaning and direction not supplied"
                   for value in range(1, 5)},
        "declared": {"dtype": "uint8", "valid_min": 1, "valid_max": 4, "nodata": 255},
        "usage_notes": (
            "Foundation/display context only. Never sum classes or describe them as people with "
            "disabilities, exposure, vulnerability counts or risk. Class meaning, licence and "
            "vintage require owner confirmation before publication."
        ),
    }, "Foundation/display class raster. Despite the source filename, values are ordinal classes, "
       "not totals.")
    shutil.copy2(disability_source, disability_folder / "disability_support_class_th.tif")
    write_text(disability_folder / "TEST.md", """
# Foundation check: disability support indicator

Load `disability_support_class_th.tif` as a separate source-native EPSG:32647 display/foundation
raster. Only classes 1–4 may render; NoData 255 is transparent. The source did not provide approved
meanings or direction for the classes, and despite its original filename the values are not totals.

Before a later public contribution, confirm class meaning, licence and vintage, put the direct file
URL in `manifest.yaml`, and run GRP **Check**. Never sum the classes or call them people, exposure,
vulnerability counts or risk.
""")
    write_manifest(DATA_OUT / "vulnerable_people/weights_flood_thailand", "weights", {
        "hazard": "flood_thailand",
        "weights": {"vulnerability_child_sensitivity_th": 0.2,
                    "vulnerability_elderly_sensitivity_th": 0.2,
                    "vulnerability_pop_all_total": 0.3,
                    "vulnerability_reclass_blddensity": 0.2,
                    "vulnerability_reclass_road": 0.1},
        "rationale": "EXAMPLE for testing, not an agreed scoring: for evacuation planning the "
                     "sensitivity of children and older people is weighted beside population, "
                     "building density and road access. Replace with weights the owner approves.",
    }, "EXAMPLE weights for flood_thailand ONLY. Needs hazard_flood_thailand_rp100 and both\n"
       "sensitivity rasters landed first. Never submit weights for hazard 'flood': that changes\n"
       "every user's Thailand risk levels. Weighting sensitivity is a scoring decision GRP\n"
       "itself does not make (ADR-0030); the owner decides.")


# ---------- population ----------

def population() -> None:
    """A headcount grid from registered village points: GRP's own register, labelled so."""

    transform, width, height = thailand_grid()
    factor = 10  # about 1 km pixels
    coarse = from_origin(transform.c, transform.f, RES * factor, RES * factor)
    cols, rows = math.ceil(width / factor), math.ceil(height / factor)
    grid = np.zeros((rows, cols), dtype="float32")
    records, xy = read_points("administrative_boundary/village/village.shp")
    placed = 0
    for record, (x, y) in zip(records, xy, strict=False):
        people = village_population(record).get("total_population")
        if not people:
            continue
        col, row = ~coarse * (x, y)
        if 0 <= int(row) < rows and 0 <= int(col) < cols:
            grid[int(row), int(col)] += people
            placed += people
    folder = DATA_OUT / "administrative_boundary/village/population_th_village_register"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "population_th_village_register.tif"
    with rasterio.open(target, "w", **{**GTIFF, "predictor": 3, "dtype": "float32", "count": 1,
                                       "width": cols, "height": rows, "crs": "EPSG:4326",
                                       "transform": coarse}) as out:
        out.write(grid, 1)
    write_manifest(folder, "raster", {
        "layer": "population_th_village_register", "url": URL,
        "title": "Registered population count, Thailand (village register, ~1 km, EXPERIMENTAL)",
        "description": f"Registered residents summed into ~1 km pixels at each village point "
                       f"({placed:,} people). A count grid, not classes.",
        "source": "Thailand village register, delivered to ADPC; gridded by ADPC",
        "license": "unstated", "vintage": "2026-09",
        "declared": {"dtype": "float32", "valid_min": 0, "valid_max": float(grid.max()) + 1},
        "usage_notes": "EXPERIMENTAL: each village's whole population sits in the pixel of its "
                       "point, so a flood edge through a village counts all or none of it. Same "
                       "register GRP reports; WorldPop would be the independent alternative.",
    }, "EXPERIMENTAL headcount grid. Lets Global Risk answer 'how many people live in the flood\n"
       "zone' with GRP's own register; not an independent population source.")
    print(f"population grid written: {size_mb(target)} MB, {placed:,} people")


# ---------- GRP's own numbers ----------

def compare() -> None:
    """GRP's side of each test: the DOPA district, the full-resolution depth at each point."""

    meta, _, wkb, columns = read_raw(
        DATA_IN / "administrative_boundary/district_boundary/Thailand_District_Boundaries.shp")
    districts = [dict(zip(meta["fields"], values, strict=False), geometry=geometry)
                 for *values, geometry in zip(*columns, shapely.from_wkb(wkb), strict=False)]

    def area_km2(polygon) -> float:
        # Equal-area (Lambert cylindrical on a sphere of the authalic radius) is exact enough to
        # compare two districts' areas.
        radius = 6371.0072

        def project(x, y):
            return np.radians(x) * radius, np.sin(np.radians(y)) * radius

        return float(shapely.area(shapely.transform(
            polygon, lambda xy: np.column_stack(project(xy[:, 0], xy[:, 1])))))
    tiles = [rasterio.open(p) for p in sorted((DATA_IN / "floods/flood_depth_rp100").glob("*.tif"))]

    def depth_at(x: float, y: float) -> float | None:
        for tile in tiles:
            b = tile.bounds
            if b.left <= x < b.right and b.bottom < y <= b.top:
                value = next(tile.sample([(x, y)]))[0]
                return None if value == tile.nodata else float(value)
        return None

    def band(depth: float | None) -> int:
        if depth is None:
            return 0
        lower = 0.0
        for upper, value in DEPTH_BANDS:
            if lower < depth <= upper:
                return value
            lower = upper
        return 0

    layers = {}
    for key, path in (
        ("evacuation_centres_ddpm", "evacuation_centers/shelters/evacuation_centres_ddpm.geojson"),
        ("early_warning_towers_ddpm",
         "evacuation_centers/earlywarning_resources/early_warning_towers_ddpm.geojson"),
        ("civil_defence_volunteer_centres_ddpm",
         "evacuation_centers/volunteer_center/civil_defence_volunteer_centres_ddpm.geojson"),
        ("villages_th_register", "administrative_boundary/village/villages_th_register.geojson"),
    ):
        document = json.loads((DATA_OUT / path).read_text(encoding="utf-8"))
        layers[key] = [(f["geometry"]["coordinates"], f["properties"])
                       for f in document["features"]]

    lines = ["# GRP's own numbers for the test districts", "",
             "Computed from `.local/data-in` exactly as GRP's engine sees it: the DOPA district "
             "polygon and the full-resolution depth at each point (exposed = depth > 0). Global "
             "Risk uses an OpenStreetMap polygon and its reclassed layer, so compare each row with "
             "its answer and read the gaps in `README.md`.", ""]
    for short, place in COMPARE:
        province = place.split(", ")[1].casefold()
        match = [d for d in districts
                 if str(d["NAME_ENG2"]).casefold() == short.casefold()
                 and str(d["NAME_ENG1"]).casefold() == province]
        if not match:
            lines += [f"## {place}", "", "Not found in the DOPA district file.", ""]
            continue
        row = match[0]
        polygon = row["geometry"]
        area = area_km2(polygon)
        shapely.prepare(polygon)
        lines += [f"## {place}", "",
                  f"DOPA polygon {area:,.0f} km² ({row['NAME_ENG1']}, code {row['ADMIN_ID2']}). "
                  "Global Risk states its own polygon's area in each answer; a large difference "
                  "means the two engines count different ground.", "",
                  "| Layer | Inside district | In flood (depth > 0) | By class 1-5 "
                  "| Dry or no data |",
                  "|---|---:|---:|---|---:|"]
        people_total = people_flooded = 0
        for key, features in layers.items():
            inside = [(c, p) for c, p in features
                      if shapely.contains_xy(polygon, c[0], c[1])]
            classes = Counter(band(depth_at(*c)) for c, _ in inside)
            flooded = sum(v for k, v in classes.items() if k)
            by_class = ", ".join(f"{k}: {classes[k]}" for k in range(1, 6) if classes[k]) or "none"
            lines.append(f"| {key} | {len(inside):,} | {flooded:,} | {by_class} | {classes[0]:,} |")
            if key == "villages_th_register":
                for c, p in inside:
                    people = p.get("total_population") or 0
                    people_total += people
                    people_flooded += people if band(depth_at(*c)) else 0
        lines += ["", f"Registered population: {people_total:,} in the district, "
                      f"{people_flooded:,} in villages whose point is in the flood layer.", ""]
    for tile in tiles:
        tile.close()
    write_text(DATA_OUT / "compare/district_comparison.md", "\n".join(lines))
    print("comparison written")


# ---------- self-check ----------

def check() -> None:
    ok = True
    for manifest in sorted(DATA_OUT.rglob("manifest.json")):
        body = json.loads(manifest.read_text(encoding="utf-8"))
        problems = check_manifest(body["kind"], body["manifest"]).problems
        print(("ok  " if not problems else "BAD ") + str(manifest.relative_to(DATA_OUT)),
              problems or "")
        ok &= not problems
    for geojson in sorted(DATA_OUT.rglob("*.geojson")):
        if "sig" in geojson.relative_to(DATA_OUT).parts[:1]:
            continue
        result = check_point_file(geojson.read_bytes())
        print(("ok  " if not result.problem else "BAD ") + str(geojson.relative_to(DATA_OUT)),
              result.feature_count, size_mb(geojson), "MB", result.problem or "")
        ok &= result.problem is None
    for tif in sorted(DATA_OUT.rglob("*.tif")):
        with rasterio.open(tif) as src:
            sample = src.read(1, out_shape=(1, max(1, src.height // 8), max(1, src.width // 8)))
            finite = sample[np.isfinite(sample)]
            print(f"ok   {tif.relative_to(DATA_OUT)} {src.crs} {src.dtypes[0]} nodata={src.nodata}"
                  f" range={finite.min():g}..{finite.max():g} {size_mb(tif)} MB"
                  + ("  (over 100 MB: Google Drive shows a virus-scan page)"
                     if size_mb(tif) > 100 else ""))
    print("all checks passed" if ok else "SOME CHECKS FAILED")


# ---------- the folder to upload to Google Drive ----------

# (folder, source folder, file, what it is). Order is the stable foundation order. Loading a
# foundation is not publication approval; each manifest preserves its later contribution gates.
DRIVE = [
    ("01_early_warning_towers", "evacuation_centers/earlywarning_resources",
     "early_warning_towers_ddpm.geojson", "Early-warning towers (DDPM)"),
    ("02_volunteer_centres", "evacuation_centers/volunteer_center",
     "civil_defence_volunteer_centres_ddpm.geojson", "Civil-defence volunteer centres (DDPM)"),
    ("03_villages", "administrative_boundary/village",
     "villages_th_register.geojson", "Villages (register)"),
    ("04_OPTIONAL_population_grid",
     "administrative_boundary/village/population_th_village_register",
     "population_th_village_register.tif", "Population count grid, experimental"),
    ("05_OPTIONAL_subdistrict_population_table", "administrative_boundary/sub-district_boundary",
     "th_subdistrict_population.csv", "Sub-district population table"),
    ("06_OPTIONAL_flood_thailand_rp100", "floods/flood_depth_rp100",
     "hazard_flood_thailand_rp100.tif", "GRP's flood tiles, classed 1-5"),
    ("07_evacuation_centres", "evacuation_centers/shelters",
     "evacuation_centres_ddpm.geojson", "Evacuation centres (DDPM)"),
    ("08_child_sensitivity", "vulnerable_people/vulnerability_child_sensitivity_th",
     "vulnerability_child_sensitivity_th.tif", "Child sensitivity index"),
    ("09_older_person_sensitivity", "vulnerable_people/vulnerability_elderly_sensitivity_th",
     "vulnerability_elderly_sensitivity_th.tif", "Older-person sensitivity index"),
    ("10_disability_support_indicator", "vulnerable_people/vulnerability_disability_class_th",
     "disability_support_class_th.tif", "Disability support indicator class"),
]


def drive() -> None:
    import shutil

    target = DATA_OUT / "google-drive-upload"
    # A LINKS.csv someone has filled in survives a rebuild.
    links = (target / "LINKS.csv").read_bytes() if (target / "LINKS.csv").exists() else None
    if target.exists():
        shutil.rmtree(target)
    rows = [["folder", "dataset", "file", "size_mb", "google_drive_link", "submitted_by",
             "submitted_at", "contribution_id", "status", "notes"]]
    for folder, source, name, title in DRIVE:
        out = target / folder
        out.mkdir(parents=True)
        for file in (name, "manifest.yaml", "TEST.md"):
            if (DATA_OUT / source / file).exists():
                shutil.copy2(DATA_OUT / source / file, out / file)
        # The population grid shares its TEST.md with the villages.
        if not (out / "TEST.md").exists():
            shutil.copy2(DATA_OUT / source / ".." / "TEST.md", out / "TEST.md")
        rows.append([folder, title, name, size_mb(out / name), "", "", "", "", "", ""])
    for guide in ("global-risk-contribute-guide.docx", "share-data-with-global-risk-guide.docx",
                  "share-data-with-global-risk-guide.md"):
        if (ROOT / "docs" / "guides" / guide).exists():
            shutil.copy2(ROOT / "docs" / "guides" / guide, target / guide)
    if links is not None:
        (target / "LINKS.csv").write_bytes(links)
    else:
        with (target / "LINKS.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            csv.writer(handle).writerows(rows)
    write_text(
        target / "00_START_HERE.md",
        """# Foundation and future-contribution kit: GRP data for Global Risk

Folders 01–10 give developers stable foundation files and reusable manifests. Loading a file into
an isolated development foundation is not permission to publish it. Global Risk may auto-approve
every contribution: anything sent is public to every user at once
(confirmed 30 Sep 2026), and removing an approved one may need a Global Risk reviewer. Only the
GRP team sends. Testers practise with Check and a dry run, which send nothing (see the guide's
"Try it yourself"). Already live from ADPC: the test copies evacuation_centres_th_test and
early_warning_towers_test_kovitad.

## For the person uploading
1. Upload this whole folder to Google Drive.
2. Share the folder with "Anyone with the link" (Viewer). The files inherit it.
3. For each data file: right-click, Share, Copy link. Paste the link into `LINKS.csv`.
   Share the file, not the folder: a folder link returns a web page, not data.

## For the tester
- Do not send anything yourself. For each dataset the GRP team sends, it chooses ONE route and
  submits once:
  - GRP's Share data page: follow `share-data-with-global-risk-guide.docx` (Appendix A has
    every field value to type);
  - Claude Desktop: follow `global-risk-contribute-guide.docx` (paste `manifest.yaml`).
- Load foundations in folder order 01–10. Folders 04–06 are optional/experimental.
- Each folder has `manifest.yaml` and `TEST.md` (what to check and the limits to preserve).
- Before contributing folder 07 publicly, remove the older duplicate test layer
  `evacuation_centres_th_test` (c66ade79bc2605ac), or answers may count centres twice.
- Folders 08–10 are separate relative/class indicators, never vulnerable-person counts. Confirm
  source meaning, licence and vintage before public contribution; do not add weights merely to
  make them affect a risk score.
- One person submits each dataset, once. Record the time, `contribution_id` and status in
  `LINKS.csv`.
""",
    )
    print(f"wrote {target.relative_to(ROOT)}")


STEPS = {"points": points, "tables": tables, "flood": flood, "vulnerability": vulnerability,
         "population": population, "compare": compare, "drive": drive, "check": check}

if __name__ == "__main__":
    for step in sys.argv[1:] or ["points", "tables", "compare", "check"]:
        STEPS[step]()
