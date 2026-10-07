"""Capture GEOGLOWS river lines for one province's districts, once, for the River Watch pilot.

Run inside the API or worker container, which has the GIS extra and database access:

    python -m grpcli.river_watch_capture --province Bangkok --out /tmp/river_watch_bangkok.json

It reads only the province's rectangle from GEOGLOWS's open stream file over HTTP, matches each
stream segment to the supported district polygons, names the nearest OpenStreetMap waterway for
each district's main river, and writes one small JSON file for ``core/data``. The web request never
does this GIS work (AGENTS.md). Nothing here changes a forecast, an assessment or Global Risk.
"""

from __future__ import annotations

import argparse
import json
import math
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

STREAMS = (
    "/vsicurl/https://geoglows-v2.s3-us-west-2.amazonaws.com/hydrography/vpu=407/streams_407.gpkg"
)
STREAMS_PUBLIC = "https://geoglows-v2.s3-us-west-2.amazonaws.com/hydrography/vpu=407/streams_407.gpkg"
NOMINATIM = "https://nominatim.openstreetmap.org/reverse"
USER_AGENT = "GRP-river-watch-capture/0.1 (ADPC pilot)"
EARTH = 6378137.0


def _to_mercator(lon: float, lat: float) -> tuple[float, float]:
    y = math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * EARTH
    return math.radians(lon) * EARTH, y


def _to_lonlat(x: float, y: float) -> tuple[float, float]:
    return math.degrees(x / EARTH), math.degrees(2 * math.atan(math.exp(y / EARTH)) - math.pi / 2)


def _districts(province: str) -> list[dict]:
    from shapely import wkb
    from sqlalchemy import text

    from core.db import session_scope

    sql = text(
        """
        select admin_code, name, name_th,
               ST_AsBinary(geom_postgis) as geom,
               ST_AsGeoJSON(coalesce(geom_simplified_postgis, geom_postgis), 5) as outline
        from boundary
        where is_supported and admin_level = 'district'
          and (province_name ilike :p or province_name_th like :pth)
        order by name
        """
    )
    with session_scope() as session:
        rows = session.execute(sql, {"p": f"%{province}%", "pth": "%กรุงเทพ%"}).fetchall()
    return [
        {
            "admin_code": row.admin_code,
            "name": row.name.title(),
            "name_th": row.name_th,
            "geom": wkb.loads(bytes(row.geom)),
            "outline": json.loads(row.outline),
        }
        for row in rows
    ]


def _streams(bounds: tuple[float, float, float, float]) -> list[dict]:
    import pyogrio
    from shapely import LineString, MultiLineString, wkb
    from shapely.ops import transform

    x0, y0 = _to_mercator(bounds[0], bounds[1])
    x1, y1 = _to_mercator(bounds[2], bounds[3])
    meta, _, geoms, fields = pyogrio.raw.read(
        STREAMS,
        bbox=(x0, y0, x1, y1),
        columns=["LINKNO", "strmOrder", "DSContArea", "LengthGeodesicMeters"],
    )
    names = list(meta["fields"])
    out = []
    for i, raw in enumerate(geoms):
        line = transform(lambda x, y, z=None: _to_lonlat(x, y), wkb.loads(raw))
        if isinstance(line, MultiLineString):
            line = LineString([c for part in line.geoms for c in part.coords])
        out.append(
            {
                "reach_id": int(fields[names.index("LINKNO")][i]),
                "stream_order": int(fields[names.index("strmOrder")][i]),
                "upstream_area_km2": round(float(fields[names.index("DSContArea")][i]) / 1e6),
                "length_km": round(float(fields[names.index("LengthGeodesicMeters")][i]) / 1000, 1),
                "geom": line,
            }
        )
    return out


def _nearest_waterway(lon: float, lat: float) -> dict | None:
    query = urllib.parse.urlencode(
        {
            "format": "jsonv2", "lat": lat, "lon": lon, "zoom": 17,
            "layer": "natural", "namedetails": 1,
        }
    )
    request = urllib.request.Request(f"{NOMINATIM}?{query}", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.load(response)
    except Exception:  # noqa: BLE001 - a missing name is fine; the line still shows
        return None
    if data.get("category") != "waterway":
        return None
    names = data.get("namedetails") or {}
    if not (names.get("name") or names.get("name:en")):
        return None
    return {
        "name_th": names.get("name"),
        "name_en": names.get("name:en") or names.get("name"),
        "kind": data.get("type"),
        "osm": f"{data.get('osm_type')}/{data.get('osm_id')}",
    }


def capture(province: str, *, names: bool = True) -> dict:
    districts = _districts(province)
    if not districts:
        raise SystemExit(f"No supported districts found for {province!r}.")
    minx = min(d["geom"].bounds[0] for d in districts)
    miny = min(d["geom"].bounds[1] for d in districts)
    maxx = max(d["geom"].bounds[2] for d in districts)
    maxy = max(d["geom"].bounds[3] for d in districts)
    streams = _streams((minx, miny, maxx, maxy))

    reaches: dict[str, dict] = {}
    out_districts: dict[str, dict] = {}
    for district in districts:
        inside = [s for s in streams if s["geom"].intersects(district["geom"])]
        inside.sort(key=lambda s: (-s["upstream_area_km2"], s["reach_id"]))
        for s in inside:
            reaches.setdefault(
                str(s["reach_id"]),
                {
                    "stream_order": s["stream_order"],
                    "upstream_area_km2": s["upstream_area_km2"],
                    "length_km": s["length_km"],
                    "line": [
                        [round(x, 5), round(y, 5)]
                        for x, y in s["geom"].simplify(0.00005).coords
                    ],
                },
            )
        out_districts[district["admin_code"]] = {
            "name": district["name"],
            "name_th": district["name_th"],
            "outline": district["outline"],
            "reaches": [s["reach_id"] for s in inside],
            "main_reach": inside[0]["reach_id"] if inside else None,
        }

    if names:
        for district in out_districts.values():
            main = district["main_reach"]
            if main is None or "nearby" in reaches[str(main)]:
                continue
            line = reaches[str(main)]["line"]
            lon, lat = line[len(line) // 2]
            reaches[str(main)]["nearby"] = _nearest_waterway(lon, lat)
            time.sleep(1.1)  # Nominatim usage policy: at most one request per second

    return {
        "_source": {
            "captured_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "province": province,
            "streams": f"GEOGLOWS v2 open hydrography, {STREAMS_PUBLIC} (EPSG:3857, read for the "
            "province's rectangle and matched to supported district polygons).",
            "waterways": "Nearest named waterway to the middle of each district's main river, "
            "from OpenStreetMap Nominatim. Data (c) OpenStreetMap contributors, ODbL.",
            "note": "Main river = the segment that drains the most land inside the district. "
            "Chosen by rule, not confirmed by a hydrologist.",
        },
        "districts": out_districts,
        "reaches": reaches,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--province", default="Bangkok")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--no-names", action="store_true", help="Skip the OpenStreetMap name lookups"
    )
    args = parser.parse_args()
    started = time.perf_counter()
    data = capture(args.province, names=not args.no_names)
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    args.out.write_text(text, encoding="utf-8")
    print(
        f"{len(data['districts'])} districts, {len(data['reaches'])} river segments, "
        f"{args.out.stat().st_size // 1024} KB in {time.perf_counter() - started:.0f} s"
    )


if __name__ == "__main__":
    main()
