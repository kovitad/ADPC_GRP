"""Fail-closed unit checks for the imported Mangrove 360 zoning rules."""

import numpy as np
import pytest

from core.coastal_zoning.rules import make_zones_winwin


def _base(shape: tuple[int, int]) -> dict[str, object]:
    return {
        "valid": np.ones(shape, dtype=bool),
        "sea": np.zeros(shape, dtype=bool),
        "mang_now": np.zeros(shape, dtype=bool),
        "mang_old": np.zeros(shape, dtype=bool),
        "dem": np.full(shape, 6.0),
        "cell_m": (1.0, 1.0),
    }


@pytest.mark.fast
def test_sea_reserve_resort_and_dem_gap_follow_rule_priority() -> None:
    inputs = _base((1, 4))
    inputs["sea"] = np.array([[True, False, False, False]])
    inputs["dem"] = np.array([[0.0, 6.0, 6.0, np.nan]])

    zones, distances = make_zones_winwin(
        **inputs, reserve_m=0, mangrove_buffer_m=0, coast_band_m=100
    )

    assert zones.tolist() == [[10, 11, 12, 9]]
    assert distances["d_sea"].tolist() == [[0.0, 1.0, 2.0, 3.0]]


@pytest.mark.fast
def test_nan_hazard_is_unknown_and_never_low_risk() -> None:
    inputs = _base((3, 4))
    inputs["sea"] = np.array(
        [[True, True, True, True], [False, False, False, False], [False, False, False, False]]
    )
    inputs["valid"] = np.array(
        [[True, True, True, True], [False, False, False, False], [True, True, True, True]]
    )
    inputs["flood"] = np.array([[0.0] * 4, [0.0] * 4, [np.nan, 2.0, 3.0, 4.0]])
    inputs["fire"] = np.array([[1.0] * 4, [1.0] * 4, [1.0, np.nan, 2.0, 1.0]])

    zones, _distances = make_zones_winwin(
        **inputs, reserve_m=0, mangrove_buffer_m=0, coast_band_m=10
    )

    assert zones[2].tolist() == [8, 8, 13, 5]


@pytest.mark.fast
def test_missing_land_cover_is_not_treated_as_a_zero_layer() -> None:
    inputs = _base((3, 1))
    inputs["sea"] = np.array([[True], [False], [False]])

    without_layer, _ = make_zones_winwin(
        **inputs, open_land=None, reserve_m=0, mangrove_buffer_m=0, coast_band_m=10
    )
    zero_layer, _ = make_zones_winwin(
        **inputs,
        open_land=np.zeros((3, 1), dtype=bool),
        reserve_m=0,
        mangrove_buffer_m=0,
        coast_band_m=10,
    )

    assert without_layer[2, 0] == 12
    assert zero_layer[2, 0] == 8


@pytest.mark.fast
def test_existing_mangrove_wins_over_overlapping_reserve_and_no_build() -> None:
    inputs = _base((1, 1))
    inputs["mang_now"] = np.ones((1, 1), dtype=bool)
    inputs["wetland"] = np.ones((1, 1), dtype=bool)

    zones, _distances = make_zones_winwin(**inputs)

    assert zones[0, 0] == 1
