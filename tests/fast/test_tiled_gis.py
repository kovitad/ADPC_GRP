"""The six-tile Thailand hazard behaves as one pinned assessment input."""

from collections import namedtuple
from types import SimpleNamespace
from uuid import uuid4

import numpy as np

from core.gis import CenterInput, run_center_flood_overlay_tiles


class FakeRaster:
    crs = SimpleNamespace(to_epsg=lambda: 4326)
    count = 1

    def __init__(self, bounds, value):
        box = namedtuple("Bounds", "left bottom right top")
        self.bounds = box(*bounds)
        self.value = value

    def index(self, lon, lat):
        del lon, lat
        return 0, 0

    def read(self, band, *, window, masked):
        del band, window, masked
        if self.value is None:
            return np.ma.array([[0.0]], mask=[[True]])
        return np.ma.array([[self.value]], mask=[[False]])


def test_centres_are_sampled_from_the_tile_that_contains_each_point() -> None:
    boundary = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [3, 0], [3, 1], [0, 1], [0, 0]]],
    }
    centers = [
        CenterInput(uuid4(), "Flooded", 0.5, 0.5),
        CenterInput(uuid4(), "Dry", 1.5, 0.5),
        CenterInput(uuid4(), "No data", 2.5, 0.5),
    ]
    rasters = [
        FakeRaster((0, 0, 1, 1), 1.2),
        FakeRaster((1, 0, 2, 1), 0.0),
        FakeRaster((2, 0, 3, 1), None),
    ]

    in_scope, results = run_center_flood_overlay_tiles(boundary, centers, rasters)

    assert len(in_scope) == 3
    assert [result.status for result in results] == [
        "potentially_exposed",
        "not_exposed_under_scenario",
        "unable_to_assess",
    ]
    assert results[-1].reason_code == "NO_FLOOD_DATA"
