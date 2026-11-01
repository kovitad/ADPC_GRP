"""AOI planning is bounded and never silently repairs ambiguous geometry."""

import pytest

from core.coastal_zoning.aoi import AoiValidationError, plan_aoi


def test_polygon_has_geodesic_area_bbox_and_tile_estimate() -> None:
    plan = plan_aoi(
        {
            "type": "Polygon",
            "coordinates": [[[110.45, -6.95], [110.70, -6.95], [110.70, -6.75], [110.45, -6.95]]],
        }
    )

    assert plan.bbox == (110.45, -6.95, 110.7, -6.75)
    assert 300 < plan.area_km2 < 310
    assert plan.vertices == 4
    assert plan.scale == "local"
    assert plan.estimated_tiles == 63


@pytest.mark.parametrize(
    ("geometry", "message"),
    [
        ({"type": "Point", "coordinates": [1, 2]}, "Polygon"),
        (
            {
                "type": "Polygon",
                "coordinates": [[[1, 1], [2, 1], [2, 2], [1, 2]]],
            },
            "closed",
        ),
        (
            {
                "type": "Polygon",
                "coordinates": [[[181, 1], [182, 1], [182, 2], [181, 1]]],
            },
            "WGS84",
        ),
    ],
)
def test_invalid_or_ambiguous_geometry_is_rejected(geometry, message) -> None:
    with pytest.raises(AoiValidationError, match=message):
        plan_aoi(geometry)
