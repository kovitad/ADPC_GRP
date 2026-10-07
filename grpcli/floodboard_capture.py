"""Save Floodboard's open exports at a polite interval so a real flood can be replayed later.

Floodboard publishes Bangkok road flood states and recent reports under CC BY 4.0:

    python -m grpcli.floodboard_capture --every-minutes 20

Each pull writes ``<out>/<UTC timestamp>/`` with ``roads.geojson``, ``reports.csv`` and
``manifest.json`` (URL, HTTP status, response headers, byte size and SHA-256 per file). The
reports export only covers about the last 24 hours, so history is lost unless it is captured.

The default folder ``.local/capture/floodboard`` is ignored by Git. Report text can quote news
and Traffy complaints with other terms and personal details, so ``reports.csv`` is cleaned before
it is written: ``id`` and ``text`` become their SHA-256 and ``url`` is emptied (research archive
design, 4 October 2026). ``--clean-existing`` cleans folders captured before that.

One request per export per interval stays well inside the provider's cache headers (30 seconds
for roads, 4 hours for reports).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.flood_evidence.floodboard import clean_reports_csv

EXPORTS = {
    "roads.geojson": "https://www.floodboard.org/api/export/roads.geojson",
    "reports.csv": "https://www.floodboard.org/api/export/reports.csv",
}
USER_AGENT = "GRP-floodboard-capture/0.1 (ADPC SERVIR pilot; replay capture)"
TIMEOUT_SECONDS = 60
MIN_INTERVAL_MINUTES = 5

logger = logging.getLogger("grp.floodboard_capture")


def _fetch(url: str) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.status, dict(response.headers.items()), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers.items()), b""


def capture_once(out_root: Path, now: datetime | None = None) -> Path:
    """Pull every export once into a new timestamped folder and return that folder."""

    retrieved_at = now or datetime.now(UTC)
    folder = out_root / retrieved_at.strftime("%Y%m%dT%H%M%SZ")
    folder.mkdir(parents=True, exist_ok=False)
    files: dict[str, Any] = {}
    for name, url in EXPORTS.items():
        try:
            status, headers, body = _fetch(url)
        except Exception as error:
            files[name] = {"url": url, "error": str(error)}
            logger.warning("Floodboard %s failed: %s", name, error)
            continue
        entry: dict[str, Any] = {"url": url, "status": status, "bytes": len(body),
                                 "headers": headers, "fetched_at": datetime.now(UTC).isoformat()}
        if body and name == "reports.csv":
            entry["upstream_sha256"] = hashlib.sha256(body).hexdigest()
            try:
                body = clean_reports_csv(body)
                entry["cleaned"] = ["id", "text", "url"]
            except Exception as error:
                # Never keep the uncleaned file: report text can identify people.
                logger.warning("Floodboard reports.csv not cleaned, not kept: %s", error)
                entry["error"] = f"not cleaned: {error}"
                body = b""
        if body:
            (folder / name).write_bytes(body)
        entry["sha256"] = hashlib.sha256(body).hexdigest() if body else None
        files[name] = entry
    manifest = {
        "source": "floodboard",
        "license": "CC BY 4.0",
        "attribution": "Floodboard (floodboard.org)",
        "retrieved_at": retrieved_at.isoformat(),
        "files": files,
    }
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return folder


def clean_existing(out_root: Path) -> int:
    """Clean ``reports.csv`` in folders captured before cleaning started. Returns the count."""

    cleaned = 0
    for path in sorted(out_root.glob("*/reports.csv")):
        manifest_path = path.parent / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entry = manifest["files"].get("reports.csv", {})
        if entry.get("cleaned"):
            continue
        body = path.read_bytes()
        clean = clean_reports_csv(body)
        path.write_bytes(clean)
        entry.update(upstream_sha256=entry.get("sha256") or hashlib.sha256(body).hexdigest(),
                     sha256=hashlib.sha256(clean).hexdigest(), cleaned=["id", "text", "url"],
                     cleaned_at=datetime.now(UTC).isoformat())
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        cleaned += 1
    return cleaned


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path(".local/capture/floodboard"))
    parser.add_argument("--every-minutes", type=float, default=20.0)
    parser.add_argument("--once", action="store_true", help="capture one pull and stop")
    parser.add_argument("--clean-existing", action="store_true",
                        help="clean reports.csv in earlier folders, then stop")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.clean_existing:
        logger.info("Cleaned %d earlier reports.csv files", clean_existing(args.out))
        return
    interval = max(args.every_minutes, MIN_INTERVAL_MINUTES) * 60
    while True:
        try:
            folder = capture_once(args.out)
            logger.info("Captured %s", folder)
        except Exception:
            # A lost pull is recoverable at the next interval; a dead loop loses the event.
            logger.exception("Capture failed; trying again at the next interval")
        if args.once:
            return
        time.sleep(interval)


if __name__ == "__main__":
    main()
