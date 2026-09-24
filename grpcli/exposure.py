"""Compute how many people live inside a flood scenario's extent, per area.

    python -m grpcli.exposure build

The village points and the flood raster are imported separately and never meet during an import,
because exposure depends on the pair. This joins them once for the current versions and stores one
row per area (ADR-0028 slice 3). Run it after `python -m grpcli.baseline load`, and again whenever
a new village or hazard version becomes current.

Not reachable from the web. A web request must never sample 80,397 points (AGENTS.md).
"""

from __future__ import annotations

import argparse
import sys
from typing import Never

from sqlalchemy import select

from api.settings import get_settings
from core.assessment_models import Dataset, DatasetVersion
from core.data_library_models import DatasetFile
from core.db import session_scope
from core.storage import LocalStorage
from core.village_flood_exposure import build_area_flood_exposure


def fail(message: str) -> Never:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(2)


def _current_version(session, dataset_type: str, return_period_years: int | None = None):
    statement = (
        select(DatasetVersion)
        .join(Dataset, Dataset.id == DatasetVersion.dataset_id)
        .where(Dataset.type == dataset_type, DatasetVersion.is_current)
    )
    if return_period_years is not None:
        statement = statement.where(DatasetVersion.return_period_years == return_period_years)
    return session.scalar(statement.order_by(DatasetVersion.created_at.desc()))


def _raster_keys(session, hazard: DatasetVersion) -> list[str]:
    """Prefer the working COG tiles; fall back to the single stored raster.

    The same role pattern core/assessment_jobs.py pins, so the exposure table and an assessment
    read the same pixels for the same scenario.
    """

    tiles = session.scalars(
        select(DatasetFile.storage_key)
        .where(
            DatasetFile.dataset_version_id == hazard.id,
            DatasetFile.role.like("working_cog_%"),
        )
        .order_by(DatasetFile.role)
    ).all()
    if tiles:
        return [str(key) for key in tiles]
    return [hazard.storage_key] if hazard.storage_key else []


def build(return_period_years: int) -> None:
    with session_scope() as session:
        hazard = _current_version(session, "hazard", return_period_years)
        if hazard is None:
            fail(f"No current hazard version for a {return_period_years}-year return period")
        villages = _current_version(session, "village_locations")
        if villages is None:
            fail("No current village-locations version; import the baseline first")
        keys = _raster_keys(session, hazard)
        if not keys:
            fail("The current hazard version has no stored raster files")
        # Read the identifiers before the session closes; the instances detach on exit.
        hazard_id, village_id = hazard.id, villages.id
        written = build_area_flood_exposure(
            session,
            LocalStorage(get_settings().storage_root),
            hazard_version_id=hazard_id,
            village_version_id=village_id,
            return_period_years=return_period_years,
            raster_keys=keys,
        )
    print(
        f"  wrote {written:,} area rows for RP{return_period_years} "
        f"(hazard {hazard_id}, villages {village_id})"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="grpcli.exposure")
    commands = parser.add_subparsers(dest="command", required=True)
    step = commands.add_parser("build", help="compute area flood exposure for the current versions")
    step.add_argument("--return-period-years", type=int, default=100)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "build":
        build(args.return_period_years)


if __name__ == "__main__":
    main()
