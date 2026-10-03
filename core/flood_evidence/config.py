"""Load a flood pilot's configuration: Hubs, map, freshness bands and its source registry."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA = Path(__file__).resolve().parent.parent / "data"
PILOT_IDS = ("bangkok",)
FRESHNESS_BANDS = ("current", "recent", "aging", "stale")


@dataclass(frozen=True)
class SourceConfig:
    source_id: str
    adapter: str
    url: str
    interval_minutes: int
    max_bytes: int
    registry: dict[str, Any]


@dataclass(frozen=True)
class PilotConfig:
    pilot_id: str
    title: dict[str, str]
    hubs: tuple[str, ...]
    # The owner's chosen demo corridor: area codes from the pilot's area list, and its title.
    demo_corridor: dict[str, Any]
    map: dict[str, Any]
    freshness_minutes: dict[str, int]
    report_window_hours: dict[str, int]
    # Facility exposure distances in metres (ADR-0040): near_m and frontage_m.
    exposure: dict[str, float]
    sources: tuple[SourceConfig, ...]

    def source(self, source_id: str) -> SourceConfig | None:
        return next((s for s in self.sources if s.source_id == source_id), None)


def _parse(raw: dict[str, Any]) -> PilotConfig:
    bands = {name: int(raw["freshness_minutes"][name]) for name in FRESHNESS_BANDS}
    limits = [bands[name] for name in FRESHNESS_BANDS]
    if limits != sorted(limits) or limits[0] <= 0:
        raise ValueError("Freshness bands must be positive and increasing")
    sources = tuple(
        SourceConfig(
            source_id=item["source_id"],
            adapter=item["adapter"],
            url=item["url"],
            interval_minutes=int(item["interval_minutes"]),
            max_bytes=int(item["max_bytes"]),
            registry={k: v for k, v in item.items() if k not in {"adapter", "max_bytes"}},
        )
        for item in raw["sources"]
    )
    hubs = tuple(code.strip().lower() for code in raw["hubs"])
    if not hubs:
        raise ValueError("A pilot needs at least one Hub")
    return PilotConfig(
        pilot_id=raw["pilot_id"],
        title=dict(raw["title"]),
        hubs=hubs,
        demo_corridor=dict(raw.get("demo_corridor") or {}),
        map=dict(raw["map"]),
        freshness_minutes=bands,
        report_window_hours={k: int(v) for k, v in raw["report_window_hours"].items()},
        exposure={
            "near_m": float(raw.get("exposure", {}).get("near_m", 150)),
            "frontage_m": float(raw.get("exposure", {}).get("frontage_m", 60)),
        },
        sources=sources,
    )


@lru_cache
def pilot_config(pilot_id: str) -> PilotConfig | None:
    """The configuration for a known pilot, or None. Unknown IDs never reach the file system."""

    if pilot_id not in PILOT_IDS:
        return None
    raw = json.loads((DATA / f"flood_pilot_{pilot_id}.json").read_text(encoding="utf-8"))
    config = _parse(raw)
    if config.pilot_id != pilot_id:
        raise ValueError("Pilot file does not match its ID")
    return config
