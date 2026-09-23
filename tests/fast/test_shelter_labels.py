"""Planner-facing centre labels come from the facility name, not the responsible unit.

Measured over the delivered 10,303 records: the facility name is never blank and leaves 2,522
records ambiguous inside their district, while the supporting unit is blank 792 times and
leaves 8,344 ambiguous. See ADR-0020.
"""

from core.shelter_labels import ShelterLabelInput, compose_labels


def _record(index, facility="", unit="", village="", district="D1"):
    return ShelterLabelInput(
        source_index=index,
        facility_name=facility,
        supporting_unit=unit,
        village=village,
        district_key=district,
    )


def test_a_distinct_facility_name_is_the_label_unchanged() -> None:
    labels, report = compose_labels(
        [
            _record(0, facility="วัดทุ่งตาอิน", unit="วัดทุ่งตาอิน", village="3"),
            _record(1, facility="สำนักงานเทศบาลตำบลพลวง", unit="ทต.พลวง", village="2"),
        ]
    )

    assert labels == {0: "วัดทุ่งตาอิน", 1: "สำนักงานเทศบาลตำบลพลวง"}
    assert report.from_facility_name == 2
    assert report.qualified_by_village == 0 and report.unresolved == 0


def test_the_responsible_unit_never_replaces_a_facility_name() -> None:
    """Eleven temples in นายายอาม share one อบต.; using it would collapse them into one row."""

    labels, _ = compose_labels(
        [
            _record(0, facility="วัดย่านซื่อ", unit="อบต.นายายอาม", village="4"),
            _record(1, facility="วัดเขามะปริง", unit="อบต.นายายอาม", village="5"),
            _record(2, facility="วัดคลองชาก", unit="อบต.นายายอาม", village="14"),
        ]
    )

    assert set(labels.values()) == {"วัดย่านซื่อ", "วัดเขามะปริง", "วัดคลองชาก"}


def test_a_repeated_facility_name_gains_its_village() -> None:
    """`ศาลาประชาคมหมู่บ้าน` is a village hall; ตกพรม records eight of them."""

    labels, report = compose_labels(
        [
            _record(0, facility="ศาลาประชาคมหมู่บ้าน", village="ตกซี"),
            _record(1, facility="ศาลาประชาคมหมู่บ้าน", village="สีเสียด"),
            _record(2, facility="วัดตกพรม", village="ตกพรม"),
        ]
    )

    assert labels[0] == "ศาลาประชาคมหมู่บ้าน · ตกซี"
    assert labels[1] == "ศาลาประชาคมหมู่บ้าน · สีเสียด"
    assert labels[2] == "วัดตกพรม"
    assert report.qualified_by_village == 2


def test_the_same_label_in_another_district_is_left_alone() -> None:
    """Two districts may each have a village hall; a planner works inside one district."""

    labels, report = compose_labels(
        [
            _record(0, facility="ศาลาหมู่บ้าน", village="1", district="Khao Khitchakut"),
            _record(1, facility="ศาลาหมู่บ้าน", village="1", district="Pak Phanang"),
        ]
    )

    assert labels == {0: "ศาลาหมู่บ้าน", 1: "ศาลาหมู่บ้าน"}
    assert report.qualified_by_village == 0


def test_identical_name_and_village_still_yields_distinct_rows() -> None:
    """โรงเรียนและวัดนางลือ is recorded three times at one coordinate in ชัยนาท."""

    labels, report = compose_labels(
        [
            _record(0, facility="โรงเรียนและวัดนางลือ", village="2"),
            _record(1, facility="โรงเรียนและวัดนางลือ", village="2"),
        ]
    )

    assert labels[0] != labels[1]
    assert labels[0].endswith("· 1") and labels[1].endswith("· 2")
    assert report.unresolved == 2


def test_a_blank_facility_name_falls_back_to_the_responsible_unit() -> None:
    """41 records carry no facility name; the unit beats a bare number for those."""

    labels, report = compose_labels([_record(4, facility="", unit="ทต.ฉมัน", village="5")])

    assert labels == {4: "ทต.ฉมัน"}
    assert report.from_supporting_unit == 1 and report.from_facility_name == 0


def test_nothing_usable_keeps_a_numbered_label_and_is_counted() -> None:
    """No source value is ever invented; the count tells a reviewer how many are unnamed."""

    labels, report = compose_labels(
        [_record(11, facility="  ", unit=""), _record(0, facility="วัด")]
    )

    assert labels[11] == "Evacuation centre 12"
    assert report.numbered == 1 and report.total == 2


def test_whitespace_does_not_create_a_false_difference() -> None:
    """Delivered names can carry an embedded newline, as `สนามกีฬา\\nเทศบาลเมืองพนัสนิคม`."""

    labels, _ = compose_labels(
        [_record(0, facility=" ศาลา\n หมู่บ้าน "), _record(1, facility="ศาลา หมู่บ้าน")]
    )

    assert labels[0].startswith("ศาลา หมู่บ้าน")
    assert labels[0] != labels[1]
