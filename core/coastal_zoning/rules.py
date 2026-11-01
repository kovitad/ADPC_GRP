"""Mangrove 360 win-win zoning rules.

Ported without semantic changes from starter-kit ``zoning/rules.py`` SHA-256
``a3ec7fbc65190a9b76e4ef1c8a6231f4a9de26108603d6e7ffbdaf770059700d`` and mechanically
formatted for this repository. Scientific behavior is pinned by the restricted golden fixtures.
"""

import numpy as np
from scipy import ndimage

STARTER_RULES_SHA256 = "a3ec7fbc65190a9b76e4ef1c8a6231f4a9de26108603d6e7ffbdaf770059700d"


def dist_m(mask, dy, dx):
    return (
        ndimage.distance_transform_edt(~mask, sampling=(dy, dx))
        if mask.any()
        else np.full(mask.shape, np.inf)
    )


def make_zones_winwin(
    *,
    valid,
    sea,
    mang_now,
    mang_old,
    dem,
    cell_m,
    not_assessed=None,
    wetland=None,
    built=None,
    pop=None,
    open_land=None,
    flood=None,
    fire=None,
    reserve_m=100,
    mangrove_buffer_m=100,
    coast_band_m=1000,
    coast_min_dem=None,
    inland_max_mangrove_m=None,
    plant_within_m=1000,
    min_dem=5,
    settle_pop=5,
):
    """Apply the win-win coastal rules to aligned two-dimensional arrays.

    Codes are: 1 protect, 2 restore, 3 plant/reconnect, 5 no-build, 6 settlement,
    7 inland alternative, 8 conditional, 9 not assessed, 10 sea, 11 reserve,
    12 standard coastal resort, and 13 raised coastal resort. Missing layers are
    ``None``, never zero arrays. NaN hazard is unknown and ineligible for resort zones.
    """
    dy, dx = cell_m
    sh = dem.shape
    F = np.zeros(sh, bool)
    wetland = F if wetland is None else wetland
    built = F if built is None else built
    d_sea = dist_m(sea, dy, dx)
    d_mang = dist_m(mang_now, dy, dx)
    one = 1.1 * max(dy, dx)  # a reserve is never thinner than one grid cell
    lost = mang_old & ~mang_now
    low = dem <= 2
    plant = ~mang_now & ~lost & ~built & ~sea & (wetland | low) & (d_mang <= plant_within_m)
    reserve = (d_sea <= max(reserve_m, one)) | (d_mang <= max(mangrove_buffer_m, one))
    fl = np.nan_to_num(flood, nan=-1) if flood is not None else np.zeros(sh)
    fi = np.nan_to_num(fire, nan=-1) if fire is not None else np.ones(sh)
    nobuild = (fl >= 4) | (fi >= 4) | wetland | low
    fire_ok = np.isin(fi, [1, 2])
    ok = (fl >= 0) & (fl <= 2) & fire_ok  # NaN hazard = unknown = not ok
    settle = built | ((pop >= settle_pop) if pop is not None else F)
    band = d_sea <= coast_band_m
    cmin = coast_min_dem if coast_min_dem is not None else (2 if flood is not None else min_dem)
    land_ok = (open_land if open_land is not None else ~F) & (dem >= cmin)
    coast_std = band & ok & land_ok
    coast_raised = band & (fl == 3) & fire_ok & land_ok if flood is not None else F
    inland = (
        (ok & (dem >= min_dem) & (d_mang <= inland_max_mangrove_m)) if inland_max_mangrove_m else F
    )
    Z = np.zeros(sh, np.int8)
    if not_assessed is not None:
        Z[not_assessed] = 9
    Z[sea] = 10
    nodem = valid & ~sea & np.isnan(dem)
    Z[nodem] = 9  # DEM gap = not assessed
    done = ~valid | sea | nodem
    for code, m in [
        (1, mang_now),
        (2, lost),
        (3, plant),
        (11, reserve),
        (5, nobuild),
        (6, settle),
        (12, coast_std),
        (13, coast_raised),
        (7, inland),
    ]:
        sel = ~done & m
        Z[sel] = code
        done |= sel
    Z[~done] = 8
    return Z, dict(d_sea=d_sea, d_mang=d_mang)
