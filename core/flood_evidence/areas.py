"""The flood pilot's districts and their outlines (ADR-0057).

The pilot began in Bangkok, whose outlines live in the River Watch file. Since 4 October 2026 it
also covers Nonthaburi. ``core/data/flood_pilot_<id>_areas.json`` holds every pilot district and
sub-district outline. It is captured once from the GRP boundary table
(``python -m grpcli.flood_pilot areas``),
like the Bangkok file before it, so neither the worker nor a web request reads boundaries on the
fly. Without the file, the Bangkok outlines are used, which keeps old setups working.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from core.flood_evidence.config import DATA, PilotConfig
from core.river_watch import bangkok_outlines

COVERAGE_NAME = {"en": "Bangkok and Nonthaburi", "th": "กรุงเทพฯ และนนทบุรี"}


@lru_cache
def _captured(base_id: str) -> tuple[dict[str, Any], ...] | None:
    path = DATA / f"flood_pilot_{base_id}_areas.json"
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    return tuple(raw.get("areas") or ())


def all_areas(base_id: str = "bangkok") -> list[dict[str, Any]]:
    """Every captured district: admin_code, name, name_th, province, outline."""

    captured = _captured(base_id)
    if captured is not None:
        return [dict(area) for area in captured]
    if base_id != "bangkok":
        return []
    return [{**a, "province": "Bangkok"} for a in bangkok_outlines()]


def pilot_areas(config: PilotConfig) -> list[dict[str, Any]]:
    """The districts in the pilot's area list, with their outlines."""

    codes = set(config.demo_corridor.get("areas") or [])
    return [a for a in all_areas(config.base_id) if a["admin_code"] in codes]


@lru_cache
def _captured_subdistricts(base_id: str) -> tuple[dict[str, Any], ...]:
    path = DATA / f"flood_pilot_{base_id}_areas.json"
    if not path.exists():
        return ()
    raw = json.loads(path.read_text(encoding="utf-8"))
    return tuple(raw.get("subdistricts") or ())


def all_subdistricts(base_id: str = "bangkok") -> list[dict[str, Any]]:
    """Every captured sub-district; old captures safely return none."""

    return [dict(area) for area in _captured_subdistricts(base_id)]


def pilot_subdistricts(config: PilotConfig) -> list[dict[str, Any]]:
    """Captured sub-districts whose parent district is in the pilot."""

    codes = set(config.demo_corridor.get("areas") or [])
    return [a for a in all_subdistricts(config.base_id) if a["parent_code"] in codes]


def in_pilot(config: PilotConfig, admin_code: str | None) -> bool:
    """Whether a GRP district or sub-district code lies in the pilot (sub-districts roll up)."""

    code = str(admin_code or "")
    return len(code) >= 4 and code[:4] in set(config.demo_corridor.get("areas") or [])
