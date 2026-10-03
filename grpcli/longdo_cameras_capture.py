"""Build the Bangkok camera registry from the iTIC Foundation / Longdo Traffic feed (ADR-0047).

    python -m grpcli.longdo_cameras_capture --from .local/longdo_cameras.json

or, to download it once first:

    python -m grpcli.longdo_cameras_capture --download .local/longdo_cameras.json

The feed (https://camera.longdo.com/feed/?command=json) is a documented public integration feed
of iTIC Motion cameras with HLS live streams that allow any site to play them. Only cameras
inside Bangkok with a stream are kept. The officer's browser plays the stream; GRP never fetches,
relays, records or analyses it. Each camera keeps the feed's sponsor line as its credit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.flood_evidence.cameras import parse_registry
from core.flood_evidence.config import DATA
from core.flood_evidence.geo import inside_outline
from core.river_watch import bangkok_outlines

SOURCE_URL = "https://camera.longdo.com/feed/?command=json"
VIEWER = "https://camera.longdo.com/"
USER_AGENT = "GRP-flood-pilot/0.1 (ADPC SERVIR pilot)"


def download(path: Path) -> None:
    request = urllib.request.Request(SOURCE_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        path.write_bytes(response.read())


def build(raw: bytes, retrieved_at: str) -> dict[str, Any]:
    items = json.loads(raw)
    outlines = bangkok_outlines()
    cameras = []
    for item in items:
        hls = item.get("hls_url") or ""
        try:
            lat, lon = float(item["latitude"]), float(item["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        if not hls.startswith("https://"):
            continue
        district = next((a for a in outlines if inside_outline(lon, lat, a["outline"])), None)
        if district is None:
            continue
        title = str(item.get("title") or item["camid"]).strip()
        cameras.append({
            "camera_id": f"itic:{item['camid']}",
            "provider_camera_id": str(item["camid"]),
            "name": {"th": title, "en": title},
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "live": {"kind": "hls", "url": hls},
            "district_code": district["admin_code"],
            "credit": str(item.get("sponsertext") or item.get("organization") or "iTIC"),
        })
    cameras.sort(key=lambda c: c["camera_id"])
    payload = {
        "_source": {
            "provider": "iTIC Foundation / Longdo Traffic (Metamedia Technology)",
            "url": SOURCE_URL,
            "retrieved_at": retrieved_at,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "records_received": len(items),
            "records_kept": len(cameras),
            "terms": "Documented public feed; no licence stated beyond copyright. Used for the "
                     "Gate A local demo with credit; confirm terms before wider use.",
            "use": "Location and the published HLS live stream, played by the officer's browser.",
        },
        "defaults": {
            "provider": "ITIC_LONGDO",
            "heading_deg": None,
            "fov_deg": None,
            "access_mode": "embed",
            "viewer_url": VIEWER,
            "stream_url": None,
            "snapshot_url": None,
            "status": "unknown",
            "status_checked_at": None,
            "related_sensor_ids": [],
            "rights": "iTIC Foundation / Longdo Traffic public feed; credit required",
            "retention_policy": "No video is stored",
            "ingestion_allowed": False,
            "cv_allowed": False,
            "placeholder": False,
            "source_label": "iTIC Foundation · Longdo Traffic",
        },
        "cameras": cameras,
    }
    parse_registry(payload)  # fail here if a record breaks the rules
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--from", dest="source", type=Path, help="a saved feed JSON")
    group.add_argument("--download", type=Path, help="download the feed to this path first")
    parser.add_argument("--retrieved-at", help="ISO time the saved file was downloaded")
    args = parser.parse_args()
    path = args.source or args.download
    if args.download:
        download(path)
    retrieved_at = args.retrieved_at or datetime.fromtimestamp(
        path.stat().st_mtime, UTC).isoformat(timespec="seconds")
    payload = build(path.read_bytes(), retrieved_at)
    out = DATA / "flood_pilot_bangkok_cameras_longdo.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"Wrote {len(payload['cameras'])} cameras to {out}")


if __name__ == "__main__":
    main()
