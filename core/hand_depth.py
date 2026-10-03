"""HAND flood-depth rule, and the synthetic practice grid for the Pilot tab (Phase B1).

HAND is a cell's height above the drainage cell it flows to, in metres. For a water height H on
the same reference, the modelled depth is ``max(H - HAND, 0)`` inside the supported area.

- ``HAND < H``: positive depth (wet).
- ``HAND == H``: zero depth, the water's edge; not counted as wet.
- ``HAND > H``: a valid dry cell, depth 0.
- Missing, invalid (including negative) HAND, or outside the supported area: unknown (``None``),
  never dry and never evidence of safety.

This is a stage-based approximation, not a hydraulic simulation: it ignores barriers, gates,
pumps, flow and volume. The practice grid is made up; it is not Bang Bua Thong. No forecast,
rating curve or real terrain is used here.
"""

from __future__ import annotations

import math
from typing import Any

MODE = "synthetic_hand_demo"
LABEL = "Synthetic practice example: this is not Bang Bua Thong"
MAX_DEMO_STAGE_M = 5.0
SHALLOW_LIMIT_M = 1.0

WET = "wet"
EDGE = "edge"
DRY = "dry"
UNKNOWN = "unknown"
OUTSIDE = "outside"


class StageError(ValueError):
    """The water height cannot be used."""


def check_stage(stage_m: float) -> float:
    if isinstance(stage_m, bool) or not isinstance(stage_m, int | float):
        raise StageError("The water height must be a number of metres.")
    if not math.isfinite(stage_m) or stage_m < 0:
        raise StageError("The water height must be zero or more metres.")
    return float(stage_m)


def cell_depth(hand_m: float | None, stage_m: float, supported: bool = True) -> float | None:
    """Depth in metres for one cell, or ``None`` when it is unknown or outside the area."""

    stage_m = check_stage(stage_m)
    if not supported or hand_m is None:
        return None
    if not math.isfinite(hand_m) or hand_m < 0:
        return None
    return max(stage_m - hand_m, 0.0)


def cell_state(hand_m: float | None, stage_m: float, supported: bool = True) -> str:
    if not supported:
        return OUTSIDE
    depth = cell_depth(hand_m, stage_m, supported)
    if depth is None:
        return UNKNOWN
    if depth > 0:
        return WET
    return EDGE if hand_m == stage_m else DRY


def depth_block(hand_m: Any, source_valid: Any, supported: Any, stage_m: float) -> Any:
    """The same rule over one aligned NumPy block: depth with NaN for unknown cells.

    Imported lazily so the API never loads NumPy; the worker uses this for raster windows.
    """

    import numpy as np

    stage_m = check_stage(stage_m)
    hand = np.asarray(hand_m, dtype=np.float64)
    valid = (
        np.asarray(source_valid, dtype=bool)
        & np.asarray(supported, dtype=bool)
        & np.isfinite(hand)
        & (hand >= 0)
    )
    depth = np.full(hand.shape, np.nan, dtype=np.float32)
    depth[valid] = np.maximum(stage_m - hand[valid], 0.0)
    return depth


# ---------- the practice grid ----------

ROWS = 12
COLS = 20
# A made-up valley: a river channel down the middle, a side channel joining it, banks rising
# away from it, a higher patch, one block with missing data, and a corner outside the area.
_CHANNEL_COL = 9


def _practice_hand(row: int, col: int) -> float | None:
    if 4 <= row <= 5 and 14 <= col <= 15:
        return None  # missing data
    distance = abs(col - _CHANNEL_COL)
    hand = 0.45 * distance + 0.08 * ((row * 7 + col * 3) % 5)
    if col == _CHANNEL_COL:
        hand = 0.0
    # A side channel coming in from the left on rows 7-8.
    if 7 <= row <= 8 and col < _CHANNEL_COL:
        hand = min(hand, 0.25 * (_CHANNEL_COL - col) * 0.6 + 0.3)
    # A higher mound on the right bank.
    if 1 <= row <= 3 and 11 <= col <= 13:
        hand += 1.6
    return round(hand, 1)


def _practice_supported(row: int, col: int) -> bool:
    return not (row >= 10 and col >= 16)


def practice_grid() -> tuple[list[list[float | None]], list[list[bool]]]:
    hand = [[_practice_hand(r, c) for c in range(COLS)] for r in range(ROWS)]
    supported = [[_practice_supported(r, c) for c in range(COLS)] for r in range(ROWS)]
    return hand, supported


EXAMPLE_STAGE_M = 3.0
EXAMPLE_ROWS: tuple[tuple[str, float | None, bool], ...] = (
    ("River channel", 0.0, True),
    ("Low bank", 1.0, True),
    ("Gentle slope", 2.5, True),
    ("Exactly at the water height", 3.0, True),
    ("Just above the water height", 3.2, True),
    ("Missing ground height", None, True),
    ("Outside the area the model covers", 1.0, False),
)


def example_table() -> list[dict[str, Any]]:
    """The plan's H = 3 m worked example, calculated by the same rule."""

    return [
        {
            "place": place,
            "hand_m": hand,
            "depth_m": cell_depth(hand, EXAMPLE_STAGE_M, supported),
            "state": cell_state(hand, EXAMPLE_STAGE_M, supported),
        }
        for place, hand, supported in EXAMPLE_ROWS
    ]


def practice(stage_m: float) -> dict[str, Any]:
    stage_m = check_stage(stage_m)
    if stage_m > MAX_DEMO_STAGE_M:
        raise StageError(f"The practice example goes up to {MAX_DEMO_STAGE_M:g} metres.")
    hand, supported = practice_grid()
    depth = [
        [cell_depth(hand[r][c], stage_m, supported[r][c]) for c in range(COLS)]
        for r in range(ROWS)
    ]
    state = [
        [cell_state(hand[r][c], stage_m, supported[r][c]) for c in range(COLS)]
        for r in range(ROWS)
    ]
    flat_states = [s for row in state for s in row]
    wet_depths = [d for row in depth for d in row if d is not None and d > 0]
    return {
        "mode": MODE,
        "label": LABEL,
        "stage_m": stage_m,
        "rows": ROWS,
        "cols": COLS,
        "channel_col": _CHANNEL_COL,
        "shallow_limit_m": SHALLOW_LIMIT_M,
        "hand_m": hand,
        "depth_m": depth,
        "state": state,
        "counts": {
            key: flat_states.count(key) for key in (WET, EDGE, DRY, UNKNOWN, OUTSIDE)
        },
        "deep_cells": sum(1 for d in wet_depths if d > SHALLOW_LIMIT_M),
        "deepest_m": max(wet_depths, default=0.0),
        "example": {"stage_m": EXAMPLE_STAGE_M, "rows": example_table()},
        "validation": {"software": "practice only", "hydraulic": "not applicable: made-up data"},
    }
