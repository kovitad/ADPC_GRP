"""Capture OpenStreetMap schools, hospitals and clinics for a flood pilot's demo corridor, once.

    python -m grpcli.osm_assets_capture --pilot bangkok

It asks Overpass for ``amenity`` school, hospital and clinic inside the corridor's bounding box,
keeps those inside the corridor's district outlines, and writes
``core/data/flood_pilot_<pilot>_assets.json`` with the OSM timestamp and ODbL attribution. Web
requests and the worker never call Overpass (AGENTS.md); re-run this to refresh the file.

OSM is crowd-mapped: the file is labelled as OSM everywhere it is shown, and an authoritative BMA
list replaces it when one is available.
"""

from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.flood_evidence.config import DATA, pilot_config
from core.flood_evidence.geo import inside_outline
from core.river_watch import bangkok_outlines

OVERPASS = "https://overpass-api.de/api/interpreter"
USER_AGENT = "GRP-flood-pilot-capture/0.1 (ADPC SERVIR pilot)"
AMENITIES = ("school", "hospital", "clinic")


def _bounds(outlines: list[dict[str, Any]]) -> tuple[float, float, float, float]:
    points = []
    for outline in outlines:
        polygons = outline["coordinates"] if outline["type"] == "MultiPolygon" else [
            outline["coordinates"]
        ]
        points += [p for rings in polygons for ring in rings for p in ring]
    lons, lats = [p[0] for p in points], [p[1] for p in points]
    return min(lats), min(lons), max(lats), max(lons)


def capture(pilot_id: str) -> Path:
    config = pilot_config(pilot_id)
    codes = config.demo_corridor["areas"]
    areas = [a for a in bangkok_outlines() if a["admin_code"] in codes]
    # One box per district: the districts need not touch, and one big box would fetch the gaps.
    wanted = "|".join(AMENITIES)
    boxes = "".join(
        f'nwr["amenity"~"^({wanted})$"]({",".join(map(str, _bounds([a["outline"]])))});'
        for a in areas
    )
    query = f"[out:json][timeout:120];({boxes});out center tags;"
    request = urllib.request.Request(
        OVERPASS,
        data=urllib.parse.urlencode({"data": query}).encode(),
        headers={"User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        answer = json.loads(response.read())
    assets = []
    for element in answer["elements"]:
        tags = element.get("tags", {})
        lat = element.get("lat", element.get("center", {}).get("lat"))
        lon = element.get("lon", element.get("center", {}).get("lon"))
        if lat is None or lon is None or tags.get("amenity") not in AMENITIES:
            continue
        district = next(
            (a for a in areas if inside_outline(lon, lat, a["outline"])), None
        )
        if district is None:
            continue
        assets.append(
            {
                "asset_id": f"osm:{element['type']}/{element['id']}",
                "asset_type": tags["amenity"],
                "name": tags.get("name") or "",
                "name_en": tags.get("name:en") or "",
                "lat": round(lat, 7),
                "lon": round(lon, 7),
                "district_code": district["admin_code"],
                "source": "OpenStreetMap",
            }
        )
    assets.sort(key=lambda a: (a["asset_type"], a["asset_id"]))
    out = DATA / f"flood_pilot_{pilot_id}_assets.json"
    payload = {
        "_source": {
            "provider": "OpenStreetMap contributors",
            "license": "ODbL 1.0",
            "attribution": "© OpenStreetMap contributors, ODbL",
            "query": query,
            "osm_timestamp": answer.get("osm3s", {}).get("timestamp_osm_base"),
            "captured_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "areas": codes,
            "note": "Crowd-mapped. Labelled as OSM wherever shown; replace with an authoritative "
            "BMA list when one is available.",
        },
        "assets": assets,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture OSM facilities for a pilot corridor")
    parser.add_argument("--pilot", default="bangkok")
    args = parser.parse_args()
    path = capture(args.pilot)
    data = json.loads(path.read_text(encoding="utf-8"))
    print(f"Wrote {len(data['assets'])} assets to {path}")


if __name__ == "__main__":
    main()
