"""Build the Bangkok camera registry from BMA's public camera list (ADR-0046).

    python -m grpcli.bma_cameras_capture --from .local/bma_cameras.json

or, to download it once first:

    python -m grpcli.bma_cameras_capture --download .local/bma_cameras.json

BMA's flood site (floodbangkok.bangkok.go.th) serves its camera list to every visitor without a
login. The Product Owner approved using it for the Gate A local demo on 3 October 2026. Its terms
are not confirmed, so the registry says so, and GRP uses each camera only as a location, its BMA
sensor, and a link that opens the provider's live view in a new tab. GRP does not embed, relay,
record or analyse any video (``ingestion_allowed`` and ``cv_allowed`` stay false).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.flood_evidence.cameras import parse_registry
from core.flood_evidence.config import DATA
from core.flood_evidence.geo import inside_outline
from core.river_watch import bangkok_outlines

SOURCE_URL = (
    "https://floodbangkok.bangkok.go.th/bkk/dds/services/api/floods/v1/items/camera_profile"
    "?limit=-1"
)
USER_AGENT = "GRP-flood-pilot/0.1 (ADPC SERVIR pilot)"
# BMA's own page plays each camera through this public relay; the raw stream hosts are not
# reachable from the public internet (checked 3 October 2026).
RELAY = "https://floodbangkok.bangkok.go.th/api/proxy?rtcUrl="


def download(path: Path) -> None:
    request = urllib.request.Request(SOURCE_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        path.write_bytes(response.read())


def build(raw: bytes, retrieved_at: str) -> dict[str, Any]:
    items = json.loads(raw)["data"]
    outlines = bangkok_outlines()
    cameras = []
    for item in items:
        lat, lon, url = item.get("Lat"), item.get("Long"), item.get("LiveStream") or ""
        if lat is None or lon is None or not url.startswith("https://"):
            continue
        district = next((a for a in outlines if inside_outline(lon, lat, a["outline"])), None)
        if district is None:
            continue
        name = str(item["CameraName"])
        # BMA's own place label, in both languages; the district only when BMA gives none.
        label = str(item.get("camera_description") or "").strip()
        cameras.append({
            "camera_id": f"bma:{name}",
            "provider_camera_id": name,
            "name": {"th": f"{name} · {label or district['name_th']}",
                     "en": f"{name} · {label or district['name']}"},
            "lat": round(float(lat), 6),
            "lon": round(float(lon), 6),
            # The provider's own live view, opened in a new tab by the officer's browser.
            "viewer_url": RELAY + urllib.parse.quote(url, safe=""),
            "live": {"kind": "mp4", "url": RELAY + urllib.parse.quote(url, safe="")},
            "provider_stream": url,
            "related_sensor_ids": [item["SensorName"]] if item.get("SensorName") else [],
            "district_code": district["admin_code"],
        })
    cameras.sort(key=lambda c: c["camera_id"])
    payload = {
        "_source": {
            "provider": "Bangkok Metropolitan Administration, Drainage and Sewerage Department",
            "url": SOURCE_URL,
            "retrieved_at": retrieved_at,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "records_received": len(items),
            "records_kept": len(cameras),
            "terms": "Not confirmed. Approved by the Product Owner for the Gate A local demo on "
                     "3 October 2026; a request to BMA is pending "
                     "(docs/pilot/2026-10-03_BMA_CCTV_Metadata_Request.md).",
            "use": "Location, linked BMA sensor and BMA's own public live relay, played by the "
                   "officer's browser. "
                   "GRP never embeds, relays, records or analyses video.",
        },
        # Shared by every camera; ``parse_registry`` merges these into each record.
        "defaults": {
            "provider": "BMA_DDS",
            "heading_deg": None,
            "fov_deg": None,
            "access_mode": "external_viewer",
            "stream_url": None,
            "snapshot_url": None,
            "status": "unknown",
            "status_checked_at": None,
            "rights": "BMA public camera list; terms not confirmed (Gate A local demo only)",
            "retention_policy": "No video is stored",
            "ingestion_allowed": False,
            "cv_allowed": False,
            "placeholder": False,
            "source_label": "BMA flood site (floodbangkok.bangkok.go.th)",
        },
        "cameras": cameras,
    }
    parse_registry(payload)  # fail here, not in the worker, if a record breaks the rules
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--from", dest="source", type=Path, help="a saved camera_profile JSON")
    group.add_argument("--download", type=Path, help="download the list to this path first")
    parser.add_argument("--retrieved-at", help="ISO time the saved file was downloaded")
    args = parser.parse_args()
    path = args.source or args.download
    if args.download:
        download(path)
    retrieved_at = args.retrieved_at or datetime.fromtimestamp(
        path.stat().st_mtime, UTC).isoformat(timespec="seconds")
    payload = build(path.read_bytes(), retrieved_at)
    out = DATA / "flood_pilot_bangkok_cameras.json"
    # One camera per line keeps the file small and its Git diffs readable.
    lines = ",\n".join(json.dumps(c, ensure_ascii=False, separators=(",", ":"))
                       for c in payload["cameras"])
    source = json.dumps(payload["_source"], ensure_ascii=False, indent=1)
    defaults = json.dumps(payload["defaults"], ensure_ascii=False, indent=1)
    out.write_text(
        f'{{"_source": {source},\n"defaults": {defaults},\n"cameras": [\n{lines}\n]}}\n',
        encoding="utf-8",
    )
    print(f"Wrote {len(payload['cameras'])} cameras to {out}")


if __name__ == "__main__":
    main()
