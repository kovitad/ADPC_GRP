"""Flood pilot commands (ADR-0038).

Load saved Floodboard captures into the evidence store, oldest first, through the same code the
worker uses for live pulls:

    python -m grpcli.flood_pilot ingest-capture .local/capture/floodboard

Pull once now, whatever the schedule says:

    python -m grpcli.flood_pilot pull

A capture folder is skipped when a fetch with the same source, time and SHA-256 is already stored,
so the command can be re-run safely.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.settings import get_settings
from core.db import get_engine
from core.flood_evidence.config import pilot_config
from core.flood_evidence.ingest import Pulled, http_fetch, ingest_body
from core.flood_evidence.models import FETCH_HTTP_ERROR, FETCH_OK, FloodSourceFetch
from core.storage import LocalStorage

FILES = {"floodboard_roads": "roads.geojson", "floodboard_reports": "reports.csv"}


def ingest_capture(root: Path, pilot_id: str = "bangkok") -> None:
    config = pilot_config(pilot_id)
    storage = LocalStorage(get_settings().storage_root)
    folders = sorted(p for p in root.iterdir() if (p / "manifest.json").exists())
    with Session(get_engine()) as session:
        for folder in folders:
            manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
            for source_id, name in FILES.items():
                source = config.source(source_id)
                entry = manifest["files"].get(name, {})
                path = folder / name
                when = entry.get("fetched_at") or manifest["retrieved_at"]
                fetched = datetime.fromisoformat(when)
                body = path.read_bytes() if path.exists() else None
                digest = hashlib.sha256(body).hexdigest() if body else None
                seen = session.scalar(
                    select(FloodSourceFetch.id).where(
                        FloodSourceFetch.pilot_id == pilot_id,
                        FloodSourceFetch.source_id == source_id,
                        FloodSourceFetch.retrieved_at == fetched,
                    )
                )
                if seen:
                    continue
                status = entry.get("status")
                outcome = FETCH_OK if body and status == 200 else FETCH_HTTP_ERROR
                fetch = ingest_body(
                    session, storage, config, source, Pulled(status, body, outcome), fetched
                )
                session.commit()
                print(
                    f"{folder.name} {source_id}: {fetch.outcome}, {fetch.record_count} records, "
                    f"{fetch.new_states} new states, sha256 {str(digest)[:12]}"
                )


def pull_now(pilot_id: str = "bangkok") -> None:
    config = pilot_config(pilot_id)
    storage = LocalStorage(get_settings().storage_root)
    with Session(get_engine()) as session:
        for source in config.sources:
            fetch = ingest_body(
                session, storage, config, source, http_fetch(source), datetime.now().astimezone()
            )
            session.commit()
            print(f"{source.source_id}: {fetch.outcome}, {fetch.record_count} records, "
                  f"{fetch.new_states} new states")


def main() -> None:
    parser = argparse.ArgumentParser(description="Flood pilot commands (ADR-0038)")
    commands = parser.add_subparsers(dest="command", required=True)
    capture = commands.add_parser("ingest-capture", help="load saved Floodboard captures")
    capture.add_argument("root", type=Path)
    commands.add_parser("pull", help="pull every source once now")
    args = parser.parse_args()
    if args.command == "ingest-capture":
        ingest_capture(args.root)
    else:
        pull_now()


if __name__ == "__main__":
    main()
