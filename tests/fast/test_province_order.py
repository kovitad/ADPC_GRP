"""Provinces are offered by region, Bangkok first, A-Z inside each region."""

import pytest

from api.catalog import REGIONS, province_region


@pytest.mark.parametrize(
    ("code", "region"),
    [
        ("10", "bangkok"),
        ("11", "central"), ("20", "central"), ("27", "central"), ("77", "central"),
        ("50", "north"), ("67", "north"),
        ("30", "northeast"), ("49", "northeast"),
        ("80", "south"), ("96", "south"),
    ],
)
def test_each_official_code_range_maps_to_its_region(code: str, region: str) -> None:
    assert REGIONS[province_region(code)][0] == region


def test_an_unknown_code_sorts_after_every_region() -> None:
    assert province_region("99") == len(REGIONS)
    assert province_region("SY") == len(REGIONS)
