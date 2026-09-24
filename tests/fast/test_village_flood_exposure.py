"""Flood exposure counts what it measured, and admits what it could not."""

import pytest

from core.hazard_overlay import DEPTH_CLASSES
from core.village_flood_exposure import (
    VillagePoint,
    aggregate_exposure,
    depth_band,
)


def _village(
    *,
    district="3303",
    subdistrict="330301",
    people=100,
    households=25,
    lon=104.0,
    lat=15.0,
) -> VillagePoint:
    return VillagePoint(
        lon=lon,
        lat=lat,
        district_code=district,
        subdistrict_code=subdistrict,
        total_population=people,
        households=households,
    )


def test_dry_and_nodata_are_not_the_same_thing() -> None:
    assert depth_band(0.0) is None
    assert depth_band(-1.0) is None
    assert depth_band(0.2) == "0–0.5 m"


def test_every_band_boundary_lands_in_exactly_one_band() -> None:
    # A depth exactly on a boundary belongs to the lower band, matching the map legend.
    assert depth_band(0.5) == "0–0.5 m"
    assert depth_band(0.51) == "0.5–1 m"
    assert depth_band(2.0) == "1.5–2 m"
    assert depth_band(2.01) == "> 2 m"
    assert depth_band(50.0) == "> 2 m"


def test_bands_come_from_the_map_legend_so_they_cannot_drift() -> None:
    labels = {str(item["label"]) for item in DEPTH_CLASSES}
    assert depth_band(0.2) in labels
    assert depth_band(3.0) in labels


def test_a_village_is_counted_for_its_district_and_its_subdistrict() -> None:
    areas = aggregate_exposure([_village(people=100)], [1.2])

    by_level = {area.admin_level: area for area in areas}
    assert set(by_level) == {"district", "subdistrict"}
    assert by_level["district"].people_in_zone == 100
    assert by_level["subdistrict"].people_in_zone == 100
    assert by_level["district"].depth_bands == {"1–1.5 m": {"villages": 1, "people": 100}}


def test_an_unmeasured_village_is_neither_exposed_nor_dry() -> None:
    areas = aggregate_exposure([_village(people=100)], [None])

    district = next(area for area in areas if area.admin_level == "district")
    assert district.village_count == 1
    assert district.no_data_village_count == 1
    assert district.measured_village_count == 0
    # The crucial property: an unmeasured village must not read as zero people exposed.
    assert district.villages_in_zone == 0
    assert district.people_in_zone == 0


def test_a_dry_village_is_measured_but_not_in_the_zone() -> None:
    areas = aggregate_exposure([_village()], [0.0])

    district = next(area for area in areas if area.admin_level == "district")
    assert district.measured_village_count == 1
    assert district.no_data_village_count == 0
    assert district.villages_in_zone == 0


def test_an_exposed_village_with_no_population_is_counted_separately() -> None:
    areas = aggregate_exposure([_village(people=None, households=None)], [1.0])

    district = next(area for area in areas if area.admin_level == "district")
    assert district.villages_in_zone == 1
    # people_in_zone understates the exposure, so the shortfall is stated rather than hidden.
    assert district.people_in_zone == 0
    assert district.villages_in_zone_without_population == 1
    assert district.households_in_zone == 0


def test_a_village_with_no_area_code_moves_nobody_between_districts() -> None:
    areas = aggregate_exposure([_village(district=None, subdistrict=None)], [1.5])

    assert areas == []


def test_a_village_known_only_at_district_level_still_counts_there() -> None:
    areas = aggregate_exposure([_village(subdistrict=None, people=40)], [1.5])

    assert [area.admin_level for area in areas] == ["district"]
    assert areas[0].people_in_zone == 40


def test_totals_add_up_across_a_mixed_district() -> None:
    villages = [
        _village(people=100),
        _village(people=200),
        _village(people=300),
        _village(people=400),
    ]
    depths = [1.2, 0.0, None, 3.0]

    district = next(
        area for area in aggregate_exposure(villages, depths) if area.admin_level == "district"
    )

    assert district.village_count == 4
    assert district.measured_village_count == 3
    assert district.no_data_village_count == 1
    assert district.villages_in_zone == 2
    assert district.people_in_zone == 500
    # Every village is in exactly one of the three outcomes.
    assert (
        district.no_data_village_count
        + district.villages_in_zone
        + (district.measured_village_count - district.villages_in_zone)
        == district.village_count
    )
    assert sum(band["villages"] for band in district.depth_bands.values()) == 2
    assert sum(band["people"] for band in district.depth_bands.values()) == 500


def test_a_missing_depth_for_a_village_is_a_programming_error() -> None:
    with pytest.raises(ValueError):
        aggregate_exposure([_village(), _village()], [1.0])
