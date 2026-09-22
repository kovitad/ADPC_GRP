"""Prove the delivered Thailand datasets on one district, without touching GRP.

Reads the files in `.local/data-in` directly, classifies the shelters of one district
against the RP100 flood depth, and prints the counts under both readings of "no data".
Nothing is written, no database is used, and no result from this script may be shown to a
planner: it exists to check the data and to give the Scientific and Data Authority real
numbers for the no-data decision (see docs/thailand-dataset-inventory.md).

    python -m tools.prove_dataset --district "Bang Bua Thong"
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from pyogrio.raw import read as read_vector
from rasterio.windows import Window
from shapely import from_wkb
from shapely.geometry import Point

DATA_IN = Path(".local/data-in")
DISTRICTS = DATA_IN / "administrative_boundary/district_boundary/Thailand_District_Boundaries.shp"
SHELTERS = DATA_IN / "evacuation_centers/shelters/ddpm_shelters.shp"
FLOOD_DIR = DATA_IN / "floods/flood_depth_rp100"
# Truncated Thai column names in the shelter shapefile (see the inventory note).
SHELTER_NAME = "สถ_1"
SHELTER_PLACE = "สถา"
SHELTER_DISTRICT = "อำเ"
SHELTER_PROVINCE = "จัง"
SHELTER_LAT = "ละต"
SHELTER_LON = "ลอง"
DEEP_WATER_M = 10.0


@dataclass(frozen=True)
class Shelter:
    name: str
    district: str
    province: str
    lon: float
    lat: float


def load_district(name: str):
    meta, _, geometries, fields = read_vector(DISTRICTS, read_geometry=True)
    columns = {key: values for key, values in zip(meta["fields"], fields, strict=False)}
    wanted = name.strip().lower()
    for index, english in enumerate(columns["NAME_ENG2"]):
        thai = str(columns["NAME2"][index])
        if str(english).strip().lower() == wanted or thai.strip() == name.strip():
            return {
                "name_en": str(english).title(),
                "name_th": thai,
                "province_en": str(columns["NAME_ENG1"][index]).title(),
                "admin_code": str(columns["ADMIN_ID2"][index]),
                "edition": str(columns["VERSION"][index]),
                "geometry": from_wkb(geometries[index]),
            }
    raise SystemExit(f"District not found: {name}")


def load_shelters() -> list[Shelter]:
    """Load every shelter with usable coordinates.

    The shelter file's district names are abbreviated and inconsistent (many rows say only
    "เมือง"), so a name join loses points. Membership of a district is decided by the
    boundary geometry instead, which is what the GRP method does as well.
    """

    meta, _, _, fields = read_vector(SHELTERS, read_geometry=False)
    columns = {key: values for key, values in zip(meta["fields"], fields, strict=False)}
    shelters: list[Shelter] = []
    for index in range(len(columns[SHELTER_LAT])):
        district = str(columns[SHELTER_DISTRICT][index]).strip()
        try:
            lat = float(columns[SHELTER_LAT][index])
            lon = float(columns[SHELTER_LON][index])
        except (TypeError, ValueError):
            continue
        name = str(columns[SHELTER_NAME][index] or columns[SHELTER_PLACE][index] or "unnamed")
        shelters.append(Shelter(name, district, str(columns[SHELTER_PROVINCE][index]), lon, lat))
    return shelters


def flood_tiles() -> list[Path]:
    return sorted(FLOOD_DIR.glob("*_depth.tif"))


def sample_depth(tiles: list[Path], lon: float, lat: float):
    """Return (depth, covered_by_a_tile). Depth is None where the tile holds no value."""

    for path in tiles:
        with rasterio.open(path) as raster:
            west, south, east, north = raster.bounds
            if not (west <= lon < east and south < lat <= north):
                continue
            row, col = raster.index(lon, lat)
            values = raster.read(1, window=Window(col, row, 1, 1), masked=True)
            if values.size == 0 or np.ma.is_masked(values[0, 0]):
                return None, True
            return float(values[0, 0]), True
    return None, False


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--district", default="Bang Bua Thong")
    district_name = parser.parse_args().district

    district = load_district(district_name)
    area = district["geometry"]
    shelters = load_shelters()
    inside = [s for s in shelters if area.covers(Point(s.lon, s.lat))]
    tiles = flood_tiles()

    exposed: list[tuple[Shelter, float]] = []
    dry_no_value: list[Shelter] = []
    outside_coverage: list[Shelter] = []
    deep: list[tuple[Shelter, float]] = []
    for shelter in inside:
        depth, covered = sample_depth(tiles, shelter.lon, shelter.lat)
        if not covered:
            outside_coverage.append(shelter)
        elif depth is None:
            dry_no_value.append(shelter)
        else:
            exposed.append((shelter, depth))
            if depth >= DEEP_WATER_M:
                deep.append((shelter, depth))

    print(f"District: {district['name_en']} ({district['name_th']}), {district['province_en']}")
    print(f"Admin code {district['admin_code']} · boundary edition {district['edition']}")
    print(f"Shelters in the country file: {len(shelters)}; inside this boundary: {len(inside)}")
    print(f"Flood tiles covering points: {len(tiles)} available\n")

    print("Reading A — no value means NOT FLOODED (needs the modelled-area mask to be valid):")
    print(f"  potentially exposed            {len(exposed)}")
    print(f"  not exposed under this scenario {len(dry_no_value)}")
    print(f"  unable to assess                {len(outside_coverage)}")
    print("\nReading B — no value means UNKNOWN (today's GRP method):")
    print(f"  potentially exposed            {len(exposed)}")
    print("  not exposed under this scenario 0")
    print(f"  unable to assess                {len(dry_no_value) + len(outside_coverage)}")

    if exposed:
        print("\nDeepest sampled shelters:")
        for shelter, depth in sorted(exposed, key=lambda item: -item[1])[:5]:
            flag = "  <-- check: permanent water?" if depth >= DEEP_WATER_M else ""
            print(f"  {depth:6.2f} m  {shelter.name[:46]}{flag}")
    if deep:
        print(f"\n{len(deep)} shelter(s) sit in water deeper than {DEEP_WATER_M:.0f} m.")
    print("\nThis is a data check, not a GRP result: inputs are unapproved and unpinned.")


if __name__ == "__main__":
    main()
