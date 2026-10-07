"""HAND depth rule and the Pilot practice example (Phase B1): edges, unknowns, one rule."""

from __future__ import annotations

import math

import numpy as np
import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.permissions import admin_user
from core.hand_depth import (
    DRY,
    EDGE,
    LABEL,
    MODE,
    OUTSIDE,
    UNKNOWN,
    WET,
    StageError,
    cell_depth,
    cell_state,
    depth_block,
    example_table,
    practice,
    practice_grid,
)


@pytest.mark.fast
def test_the_plans_three_metre_example_is_reproduced() -> None:
    rows = {row["place"]: (row["depth_m"], row["state"]) for row in example_table()}
    assert rows == {
        "River channel": (3.0, WET),
        "Low bank": (2.0, WET),
        "Gentle slope": (0.5, WET),
        "Exactly at the water height": (0.0, EDGE),
        "Just above the water height": (0.0, DRY),
        "Missing ground height": (None, UNKNOWN),
        "Outside the area the model covers": (None, OUTSIDE),
    }


@pytest.mark.fast
@pytest.mark.parametrize("hand", [-0.5, math.nan, math.inf])
def test_invalid_ground_height_is_unknown_not_dry(hand: float) -> None:
    assert cell_depth(hand, 3.0) is None
    assert cell_state(hand, 3.0) == UNKNOWN


@pytest.mark.fast
@pytest.mark.parametrize("stage", [-0.1, math.nan, math.inf, True, "3"])
def test_an_unusable_water_height_is_refused(stage) -> None:
    with pytest.raises(StageError):
        cell_depth(1.0, stage)


@pytest.mark.fast
def test_zero_water_height_floods_nothing() -> None:
    result = practice(0.0)
    assert result["counts"][WET] == 0
    assert result["deepest_m"] == 0.0


@pytest.mark.fast
def test_depth_stays_between_zero_and_the_water_height_and_grows_with_it() -> None:
    hand, supported = practice_grid()
    previous_wet = -1
    for stage in (0.5, 1.0, 2.0, 3.0, 5.0):
        depths = [
            cell_depth(h, stage, s)
            for row_h, row_s in zip(hand, supported, strict=True)
            for h, s in zip(row_h, row_s, strict=True)
        ]
        known = [d for d in depths if d is not None]
        assert all(0.0 <= d <= stage for d in known)
        wet = sum(1 for d in known if d > 0)
        assert wet >= previous_wet
        previous_wet = wet


@pytest.mark.fast
def test_the_numpy_block_matches_the_cell_rule_and_ignores_block_size() -> None:
    hand, supported = practice_grid()
    array = np.array([[np.nan if h is None else h for h in row] for row in hand])
    valid = ~np.isnan(array)
    mask = np.array(supported)
    whole = depth_block(array, valid, mask, 2.4)

    def one(h, s):
        d = cell_depth(h, 2.4, s)
        return np.nan if d is None else d

    expected = np.array(
        [
            [one(h, s) for h, s in zip(rh, rs, strict=True)]
            for rh, rs in zip(hand, supported, strict=True)
        ],
        dtype=np.float32,
    )
    np.testing.assert_array_equal(np.isnan(whole), np.isnan(expected))
    np.testing.assert_allclose(whole[~np.isnan(whole)], expected[~np.isnan(expected)], atol=1e-6)

    for size in (1, 3, 5, 7):
        pieces = np.full(array.shape, np.nan, dtype=np.float32)
        for top in range(0, array.shape[0], size):
            for left in range(0, array.shape[1], size):
                window = (slice(top, top + size), slice(left, left + size))
                pieces[window] = depth_block(array[window], valid[window], mask[window], 2.4)
        np.testing.assert_array_equal(np.isnan(pieces), np.isnan(whole))
        np.testing.assert_allclose(pieces[~np.isnan(pieces)], whole[~np.isnan(whole)])


@pytest.mark.fast
def test_a_true_channel_zero_is_not_confused_with_unknown() -> None:
    depth = depth_block(np.array([[0.0, np.nan]]), np.array([[True, False]]), np.ones((1, 2)), 1.5)
    assert depth[0, 0] == pytest.approx(1.5)
    assert math.isnan(depth[0, 1])


@pytest.mark.fast
def test_the_practice_grid_has_every_kind_of_cell_and_is_labelled_made_up() -> None:
    result = practice(2.0)
    assert result["mode"] == MODE
    assert result["label"] == LABEL
    assert all(result["counts"][key] > 0 for key in (WET, DRY, UNKNOWN, OUTSIDE))
    assert sum(result["counts"].values()) == result["rows"] * result["cols"]


@pytest.mark.fast
def test_the_practice_api_needs_a_sensible_height() -> None:
    app.dependency_overrides[admin_user] = lambda: object()
    try:
        client = TestClient(app)
        ok = client.get("/api/v1/pilot/hand-demo", params={"stage_m": 1.5})
        assert ok.status_code == 200
        assert ok.json()["stage_m"] == 1.5
        for bad in ("-1", "5.5", "nan"):
            response = client.get("/api/v1/pilot/hand-demo", params={"stage_m": bad})
            assert response.status_code == 422, bad
    finally:
        app.dependency_overrides.pop(admin_user, None)
