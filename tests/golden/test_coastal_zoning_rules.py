"""Approved 22 October coastal-zoning reference runs from the restricted starter kit.

The source fixtures are intentionally not copied into Git while their DEM licence and vintage are
unconfirmed. CI may provide GRP_COASTAL_ZONING_FIXTURES; a developer may retain the supplied kit at
its documented local path. Missing restricted fixtures skip these goldens rather than fabricating
replacement scientific expectations.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pytest
import rasterio

from core.coastal_zoning.rules import make_zones_winwin

_REPOSITORY = Path(__file__).resolve().parents[2]
_DEFAULT_FIXTURES = (
    _REPOSITORY / "docs" / "adhoc" / "mangrove360-zoning-starter-kit" / "tests" / "fixtures"
)
FIXTURES = Path(os.environ.get("GRP_COASTAL_ZONING_FIXTURES", _DEFAULT_FIXTURES))
REQUIRED_FILES = {
    f"{site}_{suffix}"
    for site in ("southsumatra", "lamu")
    for suffix in ("inputs.npz", "params.json", "zoning_v2.tif")
}

if not FIXTURES.is_dir() or not REQUIRED_FILES.issubset({path.name for path in FIXTURES.iterdir()}):
    pytest.skip(
        "Restricted coastal-zoning goldens are not configured; set "
        "GRP_COASTAL_ZONING_FIXTURES after licence approval.",
        allow_module_level=True,
    )


@pytest.mark.golden
@pytest.mark.parametrize("site", ["southsumatra", "lamu"])
def test_rules_reproduce_approved_reference(site: str) -> None:
    params = json.loads((FIXTURES / f"{site}_params.json").read_text(encoding="utf-8"))
    with np.load(FIXTURES / f"{site}_inputs.npz", allow_pickle=False) as loaded:
        arrays = {key: loaded[key] for key in loaded.files}
    kwargs = {
        key: params[key]
        for key in (
            "reserve_m",
            "mangrove_buffer_m",
            "coast_band_m",
            "inland_max_mangrove_m",
            "plant_within_m",
        )
        if key in params
    }

    zones, _distances = make_zones_winwin(cell_m=tuple(params["cell_m"]), **arrays, **kwargs)
    with rasterio.open(FIXTURES / f"{site}_zoning_v2.tif") as dataset:
        reference = dataset.read(1)

    assert zones.shape == reference.shape
    assert (zones == reference).mean() >= params["min_agreement"]


@pytest.mark.golden
def test_missing_land_cover_is_unknown_not_a_zero_layer() -> None:
    with np.load(FIXTURES / "lamu_inputs.npz", allow_pickle=False) as loaded:
        arrays = {key: loaded[key] for key in loaded.files if key != "open_land"}

    zones, _distances = make_zones_winwin(cell_m=(83.0, 83.0), **arrays, coast_band_m=1000)

    assert (zones == 12).sum() > 0
