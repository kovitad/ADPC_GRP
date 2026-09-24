"""Classify a delivered evacuation-centre name into a facility type (ADR-0028 slice 2).

The DDPM delivery carries no type column. The type is in the Thai facility name itself:
`โรงเรียนวัดโพธิ์ลังกามิตรภาพที่ 171` is a school, `วัดย่านซื่อ` is a temple. This module reads
that and nothing else, so a Planner can be told how many recorded centres are schools without
anyone hand-tagging 80,000 rows.

Two rules make the result trustworthy rather than merely plausible:

* **Prefix before substring.** A school named after a temple starts with `โรงเรียน` and contains
  `วัด`. Thai facility names lead with the kind of place, so the leading word decides, and a
  substring is consulted only when no prefix matches.
* **Unknown stays unknown.** A name this module does not recognise classifies as ``None`` and is
  counted as unclassified. It is never forced into the nearest bucket, because an inflated school
  count is worse than an admitted gap.

Adding a prefix changes published counts. Add one only from a name actually present in a
delivery, and keep the more specific prefix above the more general one.
"""

from __future__ import annotations

from collections import Counter

UNCLASSIFIED = "unclassified"

# Ordered: the first matching prefix wins, so a more specific spelling precedes a general one.
PREFIX_RULES: tuple[tuple[str, str], ...] = (
    ("โรงเรียน", "school"),
    ("รร.", "school"),
    ("มหาวิทยาลัย", "college"),
    ("วิทยาลัย", "college"),
    ("วิทยาเขต", "college"),
    ("ศูนย์พัฒนาเด็ก", "childcare_centre"),
    ("วัด", "temple"),
    ("สำนักสงฆ์", "temple"),
    ("ที่พักสงฆ์", "temple"),
    ("มัสยิด", "mosque"),
    ("โบสถ์", "church"),
    ("สนามกีฬา", "sports_ground"),
    ("สนามหน้า", "sports_ground"),
    ("ศาลาประชาคม", "community_hall"),
    ("ศาลากลางบ้าน", "community_hall"),
    ("ศาลาการเปรียญ", "temple"),
    ("ศาลา", "community_hall"),
    ("หอประชุม", "community_hall"),
    # Both Thai spellings of "multi-purpose building" appear in the delivery.
    ("อาคารอเนกประสงค์", "community_hall"),
    ("อาคารเอนกประสงค์", "community_hall"),
    ("ศูนย์พักพิง", "shelter_centre"),
    ("จุดอพยพ", "temporary_evacuation_point"),
    ("จุดรวมพล", "temporary_evacuation_point"),
    ("พื้นที่สูง", "high_ground"),
    ("ที่สูง", "high_ground"),
    ("ค่าย", "military_site"),
    ("ฝูงบิน", "military_site"),
    ("กองพัน", "military_site"),
    ("บนถนน", "road_or_embankment"),
    ("ถนน", "road_or_embankment"),
    ("คันคลอง", "road_or_embankment"),
    ("ที่ว่าการอำเภอ", "government_office"),
    ("องค์การบริหารส่วนตำบล", "government_office"),
    ("อบต.", "government_office"),
    ("เทศบาล", "government_office"),
    ("สำนักงาน", "government_office"),
    ("โรงพยาบาลส่งเสริมสุขภาพ", "health_facility"),
    ("รพ.สต.", "health_facility"),
    ("โรงพยาบาล", "health_facility"),
    ("สถานีอนามัย", "health_facility"),
)

# Consulted only when no prefix matches, for names that lead with a donor or place name.
SUBSTRING_RULES: tuple[tuple[str, str], ...] = (
    ("โรงเรียน", "school"),
    ("วัด", "temple"),
    ("มัสยิด", "mosque"),
    ("สนามกีฬา", "sports_ground"),
    ("ศาลาประชาคม", "community_hall"),
    ("โรงพยาบาล", "health_facility"),
)

# English labels for the Planner-facing brief. Keys must cover every value above.
TYPE_LABELS: dict[str, str] = {
    "school": "School",
    "college": "College or university",
    "childcare_centre": "Childcare centre",
    "temple": "Buddhist temple",
    "mosque": "Mosque",
    "church": "Church",
    "sports_ground": "Sports ground or stadium",
    "community_hall": "Community hall",
    "government_office": "Government office",
    "health_facility": "Health facility",
    "shelter_centre": "Shelter centre",
    "temporary_evacuation_point": "Temporary evacuation point",
    "high_ground": "High ground in the village",
    "military_site": "Military site",
    "road_or_embankment": "Road or embankment",
    UNCLASSIFIED: "Type not recognised in the source name",
}

# Written out rather than derived, because appending "s" mangles "college or university" and
# "health facility". Every value in TYPE_LABELS needs an entry.
TYPE_LABELS_PLURAL: dict[str, str] = {
    "school": "schools",
    "college": "colleges or universities",
    "childcare_centre": "childcare centres",
    "temple": "Buddhist temples",
    "mosque": "mosques",
    "church": "churches",
    "sports_ground": "sports grounds or stadiums",
    "community_hall": "community halls",
    "government_office": "government offices",
    "health_facility": "health facilities",
    "shelter_centre": "shelter centres",
    "temporary_evacuation_point": "temporary evacuation points",
    "high_ground": "areas of high ground in a village",
    "military_site": "military sites",
    "road_or_embankment": "roads or embankments",
    UNCLASSIFIED: "of an unrecognised type",
}


def counted_label(facility_type: str, count: int) -> str:
    """Name a facility type to agree in number with the count beside it."""

    if count == 1:
        return TYPE_LABELS.get(facility_type, facility_type).lower()
    return TYPE_LABELS_PLURAL.get(
        facility_type, TYPE_LABELS.get(facility_type, facility_type).lower()
    )


def classify_facility(name: str) -> str | None:
    """Return the facility type for a delivered name, or None when it is not recognised."""

    text = " ".join(str(name or "").split())
    if not text:
        return None
    for prefix, facility_type in PREFIX_RULES:
        if text.startswith(prefix):
            return facility_type
    for fragment, facility_type in SUBSTRING_RULES:
        if fragment in text:
            return facility_type
    return None


def count_facility_types(names: list[str]) -> dict[str, int]:
    """Tally types across names, reporting unrecognised ones under ``unclassified``."""

    tally: Counter[str] = Counter()
    for name in names:
        tally[classify_facility(name) or UNCLASSIFIED] += 1
    return dict(tally)
