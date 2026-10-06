"""Review stored ThaiWater shadow windows without exposing measurement values."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from api.settings import get_settings
from core.db import get_engine
from core.flood_evidence.thaiwater_analysis import thaiwater_shadow_analysis
from core.storage import LocalStorage


def _moment(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as error:
        raise argparse.ArgumentTypeError("use an ISO-8601 timestamp") from error
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("timestamp must include a timezone")
    return parsed.astimezone(UTC)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    analyze = commands.add_parser(
        "analyze", help="report cadence, missingness, churn and quality from stored captures"
    )
    analyze.add_argument("--pilot", default="bangkok")
    analyze.add_argument("--start", type=_moment, help="inclusive ISO-8601 retrieval time")
    analyze.add_argument("--end", type=_moment, help="inclusive ISO-8601 retrieval time")
    analyze.add_argument("--output", type=Path, help="write JSON to this path instead of stdout")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    settings = get_settings()
    with Session(get_engine()) as session:
        payload = thaiwater_shadow_analysis(
            session,
            LocalStorage(settings.storage_root),
            args.pilot,
            start=args.start,
            end=args.end,
        )
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
