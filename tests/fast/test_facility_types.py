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
