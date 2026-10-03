"""Build the Bangkok camera registry from bmatraffic.com's public camera list (ADR-0050).

    python -m grpcli.bmatraffic_cameras_capture --from .local/bmatraffic_index.html

or, to download the page once first:

    python -m grpcli.bmatraffic_cameras_capture --download .local/bmatraffic_index.html

BMA's traffic CCTV site lists its cameras in its public home page and plays each one at
``http://www.bmatraffic.com/PlayVideo.aspx?ID=<id>``. The Product Owner found it the fastest
live view and asked to use it (3 October 2026). GRP keeps each camera's ID, Thai and English
names, viewing direction and location; the internal IP address in the list is never stored.

The player page cannot play inside GRP: its pictures come from ``show.aspx``, which sends a real
frame only to a browser holding a bmatraffic.com session cookie (``SameSite=Lax``), and a browser
never sends that cookie from inside another site's frame. GRP therefore links to the player in a
new tab and never works around the session check. The site answers only over plain http.
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

from core.flood_evidence.cameras import parse_registry
from core.flood_evidence.config import DATA
from core.flood_evidence.geo import inside_outline
from core.river_watch import bangkok_outlines

SOURCE_URL = "http://www.bmatraffic.com/index.aspx"
PLAYER = "http://www.bmatraffic.com/PlayVideo.aspx?ID={id}"
USER_AGENT = "GRP-flood-pilot/0.1 (ADPC SERVIR pilot)"
# ['ID','Thai name','English name','Thai short name','direction',lat,lon,'internal IP','pin']
RECORD = re.compile(
    r"\['(\d+)','([^']*)','([^']*)','([^']*)','([^']*)',(\d{1,2}\.\d+),(\d{2,3}\.\d+),"
    r"'[^']*','[^']*'\]"
)


def download(path: Path) -> None:
    request = urllib.request.Request(SOURCE_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        path.write_bytes(response.read())


def _clean(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


def build(raw: bytes, retrieved_at: str) -> dict[str, Any]:
    html = raw.decode("utf-8", errors="replace")
    records = RECORD.findall(html)
    if not records:
        raise ValueError("No camera records found: the page layout may have changed")
    outlines = bangkok_outlines()
    cameras, seen = [], set()
    for cam_id, name_th, name_en, _short, direction, lat, lon in records:
        if cam_id in seen:
            continue
        seen.add(cam_id)
        lat_f, lon_f = float(lat), float(lon)
        district = next((a for a in outlines if inside_outline(lon_f, lat_f, a["outline"])), None)
        if district is None:
            continue
        where = _clean(direction)
        cameras.append({
            "camera_id": f"bmatraffic:{cam_id}",
            "provider_camera_id": cam_id,
            "name": {"th": _clean(name_th) + (f" · {where}" if where else ""),
                     "en": (_clean(name_en) or _clean(name_th)) + (f" · {where}" if where else "")},
            "lat": round(lat_f, 6),
            "lon": round(lon_f, 6),
            "viewer_url": PLAYER.format(id=cam_id),
            "district_code": district["admin_code"],
        })
    cameras.sort(key=lambda c: int(c["provider_camera_id"]))
    payload = {
        "_source": {
            "provider": "BMA Traffic CCTV (bmatraffic.com)",
            "url": SOURCE_URL,
            "retrieved_at": retrieved_at,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "records_received": len(records),
            "records_kept": len(cameras),
            "terms": "Public site, no terms stated, no robots.txt. Embedding approved by the "
                     "Product Owner for the Gate A local demo on 3 October 2026; confirm with BMA "
                     "before wider use. Plain http only.",
            "use": "Location, names and a link that opens the site's own player page in a new "
                   "tab. The player shows a picture only to a browser with a bmatraffic.com "
                   "session, which a browser never sends from inside another site, so it cannot "
                   "play inside GRP (checked 3 October 2026). GRP never fetches, records or "
                   "analyses the video; internal IP addresses are dropped.",
        },
        "defaults": {
            "provider": "BMA_TRAFFIC",
            "heading_deg": None,
            "fov_deg": None,
            "access_mode": "embed",
            "stream_url": None,
            "snapshot_url": None,
            "status": "unknown",
            "status_checked_at": None,
            "related_sensor_ids": [],
            "rights": ("bmatraffic.com public player, opened on its own site; linking approved "
                       "for the local demo only"),
            "retention_policy": "No video is stored",
            "ingestion_allowed": False,
            "cv_allowed": False,
            "placeholder": False,
            "allow_http_links": True,
            "source_label": "BMA Traffic CCTV (bmatraffic.com)",
        },
        "cameras": cameras,
    }
    parse_registry(payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--from", dest="source", type=Path, help="a saved index.aspx page")
    group.add_argument("--download", type=Path, help="download the page to this path first")
    parser.add_argument("--retrieved-at", help="ISO time the saved page was downloaded")
    args = parser.parse_args()
    path = args.source or args.download
    if args.download:
        download(path)
    retrieved_at = args.retrieved_at or datetime.fromtimestamp(
        path.stat().st_mtime, UTC).isoformat(timespec="seconds")
    payload = build(path.read_bytes(), retrieved_at)
    lines = ",\n".join(json.dumps(c, ensure_ascii=False, separators=(",", ":"))
                       for c in payload["cameras"])
    source = json.dumps(payload["_source"], ensure_ascii=False, indent=1)
    defaults = json.dumps(payload["defaults"], ensure_ascii=False, indent=1)
    out = DATA / "flood_pilot_bangkok_cameras_bmatraffic.json"
    out.write_text(
        f'{{"_source": {source},\n"defaults": {defaults},\n"cameras": [\n{lines}\n]}}\n',
        encoding="utf-8",
    )
    print(f"Wrote {len(payload['cameras'])} cameras to {out}")


if __name__ == "__main__":
    main()
