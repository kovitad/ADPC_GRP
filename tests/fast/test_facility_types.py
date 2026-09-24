"""The facility type is read from the delivered Thai name, and never guessed."""

from core.facility_types import (
    PREFIX_RULES,
    SUBSTRING_RULES,
    TYPE_LABELS,
    UNCLASSIFIED,
    classify_facility,
    count_facility_types,
)


def test_a_school_named_after_a_temple_is_a_school() -> None:
    # The decisive case: the name contains วัด but leads with โรงเรียน.
    assert classify_facility("โรงเรียนวัดโพธิ์ลังกามิตรภาพที่ 171") == "school"
    assert classify_facility("วัดย่านซื่อ") == "temple"


def test_the_common_delivered_kinds_are_recognised() -> None:
    assert classify_facility("ศาลาประชาคมหมู่บ้าน") == "community_hall"
    assert classify_facility("สนามกีฬาเทศบาล") == "sports_ground"
    assert classify_facility("อบต.นายายอาม") == "government_office"
    assert classify_facility("โรงพยาบาลส่งเสริมสุขภาพตำบลตกพรม") == "health_facility"
    assert classify_facility("มัสยิดกลาง") == "mosque"


def test_a_name_leading_with_a_donor_still_matches_on_a_substring() -> None:
    assert classify_facility("อาคารเรียน โรงเรียนบ้านหนองแวง") == "school"


def test_an_unrecognised_name_is_not_forced_into_a_type() -> None:
    assert classify_facility("บ้านนายสมชาย") is None
    assert classify_facility("") is None
    assert classify_facility("   ") is None


def test_counts_report_unrecognised_names_rather_than_dropping_them() -> None:
    counts = count_facility_types(
        ["โรงเรียนบ้านโนนสูง", "วัดป่า", "วัดใหม่", "บ้านนายสมชาย"]
    )

    assert counts == {"school": 1, "temple": 2, UNCLASSIFIED: 1}
    # The breakdown must add up to what a planner is also told the total is.
    assert sum(counts.values()) == 4


def test_every_rule_has_an_english_label() -> None:
    # A type with no label would reach a brief as a raw snake_case key.
    for _, facility_type in PREFIX_RULES + SUBSTRING_RULES:
        assert facility_type in TYPE_LABELS
    assert UNCLASSIFIED in TYPE_LABELS


def test_both_thai_spellings_of_multi_purpose_building_are_recognised() -> None:
    # The delivery carries อเนก and เอนก; missing one silently under-counts community halls.
    assert classify_facility("อาคารอเนกประสงค์หมู่บ้าน") == "community_hall"
    assert classify_facility("อาคารเอนกประสงค์หมู่บ้าน") == "community_hall"


def test_the_kinds_of_place_that_are_not_buildings_are_recognised() -> None:
    assert classify_facility("จุดอพยพชั่วคราว") == "temporary_evacuation_point"
    assert classify_facility("พื้นที่สูงในหมู่บ้าน") == "high_ground"
    assert classify_facility("บนถนนหลวง42") == "road_or_embankment"
    assert classify_facility("คันคลองชลประทาน") == "road_or_embankment"
    assert classify_facility("ค่ายสิรินธร") == "military_site"
    assert classify_facility("ศูนย์พักพิงพระราชทานฯ") == "shelter_centre"


def test_a_school_on_a_road_is_still_a_school() -> None:
    # The road rules must not outrank a leading kind of place.
    assert classify_facility("โรงเรียนบ้านถนนใหญ่") == "school"


def test_a_count_agrees_in_number_with_its_label() -> None:
    from core.facility_types import TYPE_LABELS_PLURAL, counted_label

    assert counted_label("school", 1) == "school"
    assert counted_label("school", 2) == "schools"
    # The cases naive pluralisation gets wrong.
    assert counted_label("college", 3) == "colleges or universities"
    assert counted_label("health_facility", 4) == "health facilities"
    assert counted_label("church", 2) == "churches"
    # Every label needs a plural, or a brief prints a singular beside a plural count.
    assert set(TYPE_LABELS_PLURAL) == set(TYPE_LABELS)
