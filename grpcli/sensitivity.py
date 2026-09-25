"""Sample the sensitivity indicators at every current evacuation centre (ADR-0030).

    python -m grpcli.sensitivity build

Reads the national 12.5 m rasters once and stores one value per centre and indicator, so the map
can show it without a web request touching a raster (AGENTS.md). Run after the baseline is loaded,
and again whenever a new centre or sensitivity version becomes current.
"""

from __future__ import annotations

import argparse
import sys
from typing import Never

from sqlalchemy import select

from api.settings import get_settings
from core.assessment_models import Dataset, DatasetVersion
from core.centre_sensitivity import build_centre_sensitivity
from core.db import session_scope
from core.storage import LocalStorage


def fail(message: str) -> Never:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(2)


def build() -> None:
    with session_scope() as session:
        centres = session.scalar(
            select(DatasetVersion)
            .join(Dataset, Dataset.id == DatasetVersion.dataset_id)
            .where(Dataset.type == "evacuation_centers", DatasetVersion.is_current)
            .order_by(DatasetVersion.created_at.desc())
        )
        if centres is None:
            fail("No current evacuation-centre version; import the baseline first")
        centres_id = centres.id
        try:
            written = build_centre_sensitivity(
                session, LocalStorage(get_settings().storage_root), centers_version_id=centres_id
            )
        except ValueError as error:
            fail(str(error))
    for key, count in sorted(written.items()):
        print(f"  {key}: {count:,} centres with a value (centres {centres_id})")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="grpcli.sensitivity")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("build", help="sample sensitivity indicators at the current centres")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "build":
        build()


if __name__ == "__main__":
    main()
