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


def archive_now(pilot_id: str = "bangkok") -> None:
    """Write every finished day not yet in the research archive (ADR-0055)."""

    from core.flood_evidence.archive import export_pending

    config = pilot_config(pilot_id)
    storage = LocalStorage(get_settings().storage_root)
    with Session(get_engine()) as session:
        written = export_pending(session, storage, config)
    print(f"research archive: wrote {', '.join(written) or 'nothing new'}")


def capture_areas(pilot_id: str = "bangkok") -> Path:
    """Write every pilot district's outline from the GRP boundary table (ADR-0057). Run again after
    the boundary edition or the pilot's area list changes."""

    from datetime import UTC

    from sqlalchemy import text

    from core.flood_evidence.config import DATA

    config = pilot_config(pilot_id)
    codes = sorted(config.demo_corridor.get("areas") or [])
    with Session(get_engine()) as session:
        rows = session.execute(text(
            "select distinct on (admin_code) admin_code, name, name_th, province_name, "
            "province_name_th, edition, ST_AsGeoJSON(geom_simplified_postgis, 6) "
            "from boundary where admin_level = 'district' and is_supported "
            "and admin_code = any(:codes) order by admin_code, edition desc"
        ), {"codes": codes}).all()
    found = {r[0] for r in rows}
    missing = [c for c in codes if c not in found]
    if missing:
        raise SystemExit(f"No supported boundary for {', '.join(missing)}")
    areas = [{"admin_code": code, "name": name.title() if name.isupper() else name,
              "name_th": name_th, "province": (province or "").title(),
              "province_th": province_th, "outline": json.loads(geometry)}
             for code, name, name_th, province, province_th, _edition, geometry in rows]
    payload = {
        "_source": {
            "table": "GRP boundary (supported districts, simplified geometry)",
            "editions": sorted({r[5] for r in rows}),
            "captured_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "areas": codes,
        },
        "areas": areas,
    }
    out = DATA / f"flood_pilot_{pilot_id}_areas.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
                   encoding="utf-8")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Flood pilot commands (ADR-0038)")
    commands = parser.add_subparsers(dest="command", required=True)
    capture = commands.add_parser("ingest-capture", help="load saved Floodboard captures")
    capture.add_argument("root", type=Path)
    commands.add_parser("pull", help="pull every source once now")
    commands.add_parser("archive", help="write finished days to the research archive")
    commands.add_parser("areas", help="capture the pilot districts' outlines from GRP boundaries")
    args = parser.parse_args()
    if args.command == "ingest-capture":
        ingest_capture(args.root)
    elif args.command == "archive":
        archive_now()
    elif args.command == "areas":
        print(f"wrote {capture_areas()}")
    else:
        pull_now()


if __name__ == "__main__":
    main()
