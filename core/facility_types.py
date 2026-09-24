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
    ("อาคารอเนกประสงค์", "community_hall"),
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
    UNCLASSIFIED: "Type not recognised in the source name",
}


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
