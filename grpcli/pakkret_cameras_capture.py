"""Build the Pak Kret camera registry from the municipality's public CCTV page (ADR-0057).

    python -m grpcli.pakkret_cameras_capture --download .local/pakkret_cctv.html

or, from a page saved earlier:

    python -m grpcli.pakkret_cameras_capture --from .local/pakkret_cctv.html

Pak Kret City Municipality (เทศบาลนครปากเกร็ด, Nonthaburi) publishes 52 cameras on a public map.
The page lists each camera's ID (``CAMPK001``...), its Thai name and its position, and shows a
JPEG picture from ``https://www.thaiclouderp.com/src/img.php?name=<ID>_thumb.jpg``. That picture
needs no login and no session. It was checked on 4 October 2026: a live 640×480 view.

No terms of use are stated. Until the municipality replies to GRP's request
(``docs/pilot/2026-10-04_Pak_Kret_CCTV_Request.md``), pictures are shown on screen only, through
the relay, and are not put in downloaded reports.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.flood_evidence.areas import all_areas
from core.flood_evidence.cameras import parse_registry
from core.flood_evidence.config import DATA, pilot_config
from core.flood_evidence.geo import inside_outline

SOURCE_URL = "https://www.thaiclouderp.com/CCTV_MONITOR/web/pakkred"
PICTURE = "https://www.thaiclouderp.com/src/img.php?name={id}_thumb.jpg"
PROVIDER = "PAKKRET_CCTV"
USER_AGENT = "GRP-flood-pilot/0.1 (ADPC SERVIR pilot)"
STOPS = re.compile(r"const tourStops = (\[.*?\]);", re.S)
BUTTON = re.compile(r'data-camera="(CAMPK\d{3})"\s+data-title="(\d+)\.\s*([^"]*)"')


def download(path: Path) -> None:
    request = urllib.request.Request(SOURCE_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.read())


def build(raw: bytes, retrieved_at: str) -> dict[str, Any]:
    html = raw.decode("utf-8", errors="replace")
    match = STOPS.search(html)
    if not match:
        raise SystemExit("The page no longer lists its cameras in the expected form")
    stops = {int(stop[2]): stop[0] for stop in json.loads(match.group(1))}
    config = pilot_config("bangkok")
    codes = set(config.demo_corridor.get("areas") or [])
    areas = [a for a in all_areas(config.base_id) if a["admin_code"] in codes]
    cameras, skipped = [], 0
    # A map point's number is the camera's ID number (CAMPK017 is point 17), not its place in
    # the list: the list skips IDs.
    for camera_id, _number, title in BUTTON.findall(html):
        position = stops.get(int(camera_id[len("CAMPK"):]))
        name = " ".join(title.split())
        if position is None or not name:
            skipped += 1
            continue
        lat, lon = float(position["lat"]), float(position["lng"])
        district = next((a for a in areas if inside_outline(lon, lat, a["outline"])), None)
        if district is None:
            skipped += 1
            continue
        cameras.append({
            "camera_id": f"pakkret:{camera_id}",
            "provider_camera_id": camera_id,
            "name": {"th": name, "en": f"Pak Kret CCTV {camera_id}"},
            "lat": round(lat, 6), "lon": round(lon, 6),
            "snapshot_url": PICTURE.format(id=camera_id),
            "district_code": district["admin_code"],
        })
    payload = {
        "_source": {
            "provider": "Pak Kret City Municipality CCTV (เทศบาลนครปากเกร็ด)",
            "url": SOURCE_URL,
            "retrieved_at": retrieved_at,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "records_kept": len(cameras),
            "records_skipped": skipped,
            "terms": "Public page, no terms stated, empty robots.txt. Pictures on screen only, "
                     "through the GRP relay, until the municipality replies to GRP's request "
                     "(4 October 2026).",
        },
        "defaults": {
            "provider": PROVIDER, "heading_deg": None, "fov_deg": None,
            "access_mode": "snapshot", "stream_url": None, "viewer_url": SOURCE_URL,
            "status": "unknown", "status_checked_at": None, "related_sensor_ids": [],
            "rights": "Pak Kret municipality public CCTV page; pictures on screen only "
                      "until the municipality replies",
            "retention_policy": "No picture is stored", "ingestion_allowed": False,
            "cv_allowed": False, "placeholder": False,
            "source_label": "Pak Kret City Municipality CCTV",
        },
        "cameras": cameras,
    }
    parse_registry(payload)  # fail here, not in the worker, if a record breaks a rule
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--from", dest="source", type=Path, help="a saved copy of the page")
    group.add_argument("--download", type=Path, help="download the page to this path first")
    args = parser.parse_args()
    path = args.source or args.download
    if args.download:
        download(path)
    retrieved_at = datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(timespec="seconds")
    payload = build(path.read_bytes(), retrieved_at)
    lines = ",\n".join(json.dumps(c, ensure_ascii=False, separators=(",", ":"))
                       for c in payload["cameras"])
    source = json.dumps(payload["_source"], ensure_ascii=False, indent=1)
    defaults = json.dumps(payload["defaults"], ensure_ascii=False, indent=1)
    out = DATA / "flood_pilot_bangkok_cameras_pakkret.json"
    out.write_text(
        f'{{"_source": {source},\n"defaults": {defaults},\n"cameras": [\n{lines}\n]}}\n',
        encoding="utf-8",
    )
    print(f"Wrote {len(payload['cameras'])} cameras to {out}")


if __name__ == "__main__":
    main()
