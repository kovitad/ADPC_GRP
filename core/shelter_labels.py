"""Compose the evacuation-centre label a planner sees, and report where it stays ambiguous.

The delivered data carries two candidates. The facility column names the place — `วัดย่านซื่อ`,
`โรงเรียนวัดโพธิ์ลังกามิตรภาพที่ 171` — while the supporting-unit column names the organisation
responsible for it. The second is far coarser: eleven separate temples and schools in นายายอาม
all record `อบต.นายายอาม`. So the facility names the centre and the supporting unit does not
(ADR-0024).

The facility name is still not unique. Generic ones repeat — `ศาลาประชาคมหมู่บ้าน` appears in
eight villages of ตกพรม alone — and a few records repeat outright at one coordinate. So a label
is composed from the village where it must be, and whatever stays ambiguous is counted rather
than hidden.

Nothing here invents text. A centre with no usable source value keeps a numbered label.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

NUMBERED_LABEL = "Evacuation centre {number}"
QUALIFIER_SEPARATOR = " · "
# Feature.name is VARCHAR(300). A delivered facility name can be long, and qualifiers are
# appended after it, so the name is trimmed rather than the qualifier that makes it unique.
MAX_LABEL = 300


@dataclass(frozen=True)
class ShelterLabelInput:
    source_index: int
    facility_name: str
    supporting_unit: str
    village: str
    district_key: str


@dataclass(frozen=True)
class ShelterLabelReport:
    """What the import must tell a reviewer about the labels it just wrote."""

    total: int
    from_facility_name: int
    from_supporting_unit: int
    numbered: int
    qualified_by_village: int
    numbered_to_stay_distinct: int

    @property
    def unresolved(self) -> int:
        """Labels that only a source index could keep apart — the ones worth reviewing."""

        return self.numbered_to_stay_distinct


def _clean(value: str) -> str:
    return " ".join(str(value or "").split())


def _fit(base: str, qualifier: str = "") -> str:
    """Join a label to its qualifier within the column, shortening the label if it must."""

    if not qualifier:
        return base if len(base) <= MAX_LABEL else base[: MAX_LABEL - 1].rstrip() + "…"
    room = MAX_LABEL - len(qualifier) - len(QUALIFIER_SEPARATOR)
    if len(base) > room:
        base = base[: max(1, room - 1)].rstrip() + "…"
    return f"{base}{QUALIFIER_SEPARATOR}{qualifier}"


def _base_label(record: ShelterLabelInput) -> tuple[str, str]:
    """The label before any qualifier, and which source it came from."""

    facility = _clean(record.facility_name)
    if facility:
        return facility, "facility_name"
    # Only where the facility is blank is the responsible organisation better than a number.
    unit = _clean(record.supporting_unit)
    if unit:
        return unit, "supporting_unit"
    return NUMBERED_LABEL.format(number=record.source_index + 1), "numbered"


def compose_labels(
    records: list[ShelterLabelInput],
) -> tuple[dict[int, str], ShelterLabelReport]:
    """Return one label per source index, unique within its district, plus what it cost.

    A label repeated inside a district gains its village; if that is still not enough, it
    gains its source number. Uniqueness is only ever sought within a district, because two
    districts may legitimately each have a `ศาลาหมู่บ้าน` and a planner works in one district.
    """

    bases: dict[int, tuple[str, str]] = {r.source_index: _base_label(r) for r in records}
    origins = Counter(origin for _, origin in bases.values())

    by_district: dict[str, list[ShelterLabelInput]] = defaultdict(list)
    for record in records:
        by_district[record.district_key].append(record)

    labels: dict[int, str] = {}
    qualified = 0
    numbered_to_stay_distinct = 0

    for group in by_district.values():
        counts = Counter(bases[r.source_index][0] for r in group)
        # A village only disambiguates where the base label repeats, so a good name stays clean.
        with_village: dict[int, str] = {}
        for record in group:
            base = bases[record.source_index][0]
            village = _clean(record.village)
            if counts[base] > 1 and village:
                with_village[record.source_index] = _fit(base, village)
                qualified += 1
            else:
                with_village[record.source_index] = _fit(base)

        still_repeated = Counter(with_village.values())
        for record in group:
            candidate = with_village[record.source_index]
            if still_repeated[candidate] > 1:
                labels[record.source_index] = _fit(candidate, str(record.source_index + 1))
                numbered_to_stay_distinct += 1
            else:
                labels[record.source_index] = candidate

    report = ShelterLabelReport(
        total=len(records),
        from_facility_name=origins["facility_name"],
        from_supporting_unit=origins["supporting_unit"],
        numbered=origins["numbered"],
        qualified_by_village=qualified,
        numbered_to_stay_distinct=numbered_to_stay_distinct,
    )
    return labels, report
