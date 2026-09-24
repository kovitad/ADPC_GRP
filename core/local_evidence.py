"""GRP's own numbers, phrased as citations a brief can quote (ADR-0028).

The Planner chat used to send SIG evidence alone, so the figures GRP itself had imported were
invisible to the brief. This module reads them for one already-verified area and returns citation
records in the same shape SIG uses, so the existing rule that every paragraph ends in a numeric
citation covers GRP data unchanged.

Two deliberate constraints:

* Reads only. Every number here was computed at import time into an indexed row, because a web
  request must never aggregate village points.
* ``retrieval`` must not begin with "computed". ``_deterministic_evidence_summary`` prefers
  pack-time computations and would otherwise show GRP's records to the exclusion of SIG's.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.assessment_models import Boundary, Dataset, DatasetVersion, Feature
from core.data_library_models import AreaPopulationSummary

RETRIEVAL = "grp-baseline"
POPULATION_CAVEAT = (
    "Source columns are not yet confirmed by the data owner (ADR-0027). This is not a count of "
    "vulnerable people."
)


def _current_version(session: Session, dataset_type: str) -> DatasetVersion | None:
    return session.scalar(
        select(DatasetVersion)
        .join(Dataset, Dataset.id == DatasetVersion.dataset_id)
        .where(Dataset.type == dataset_type, DatasetVersion.is_current)
        .order_by(DatasetVersion.created_at.desc())
    )


def _area_label(boundary: Boundary) -> str:
    level = "sub-district" if boundary.admin_level == "subdistrict" else boundary.admin_level
    parts = [boundary.name]
    if boundary.province_name:
        parts.append(boundary.province_name)
    return f"{', '.join(parts)} ({level})"


def _population_citation(session: Session, boundary: Boundary) -> dict[str, Any] | None:
    version = _current_version(session, "village_locations")
    if version is None:
        return None
    summary = session.scalar(
        select(AreaPopulationSummary).where(
            AreaPopulationSummary.dataset_version_id == version.id,
            AreaPopulationSummary.admin_code == boundary.admin_code,
            AreaPopulationSummary.admin_level == boundary.admin_level,
        )
    )
    if summary is None:
        # Fail closed: no row means no record, which is not the same as nobody living there.
        return None
    sentences = [
        f"{summary.total_population:,} registered residents live in "
        f"{summary.village_count:,} villages of {_area_label(boundary)}: "
        f"{summary.male:,} male, {summary.female:,} female, in "
        f"{summary.households:,} households.",
    ]
    if summary.excluded_village_count:
        excluded = summary.excluded_village_count
        sentences.append(
            f"{excluded:,} of those villages {'is' if excluded == 1 else 'are'} excluded from "
            "the totals because their source figures do not add up or are implausible, so the "
            f"totals cover {summary.counted_village_count:,} villages."
        )
    sentences.append(POPULATION_CAVEAT)
    return {
        "title": f"Registered village population, {boundary.name}",
        "text": " ".join(sentences),
        "source": "GRP data library: registered village population",
        "retrieval": RETRIEVAL,
        "validation": "Aggregated at import time from the delivered village points.",
        "kind": "grp_population",
    }


def _shelter_citation(session: Session, boundary: Boundary) -> dict[str, Any] | None:
    version = _current_version(session, "evacuation_centers")
    if version is None:
        return None
    total = session.scalar(
        select(func.count(Feature.id)).where(
            Feature.dataset_version_id == version.id,
            Feature.boundary_id == boundary.id,
        )
    )
    if total is None:
        return None
    if not total:
        # Say zero explicitly. A brief that omits this reads as though centres were never checked.
        text = (
            f"The current DDPM evacuation-centre release records no centres in "
            f"{_area_label(boundary)}. This means none were delivered for this area, not that "
            "the area has none."
        )
    else:
        text = (
            f"The current DDPM evacuation-centre release records {total:,} evacuation centres in "
            f"{_area_label(boundary)}. Centre capacity, building condition and route safety are "
            "not assessed, so this is a count of recorded centres and not a list of safe places."
        )
    return {
        "title": f"Recorded evacuation centres, {boundary.name}",
        "text": text,
        "source": "GRP data library: DDPM evacuation centres",
        "retrieval": RETRIEVAL,
        "validation": "Counted from the current release assigned to this area.",
        "kind": "grp_evacuation_centers",
    }


def local_area_citations(session: Session, boundary: Boundary) -> list[dict[str, Any]]:
    """Citation records for one verified area, in SIG's citation shape but unnumbered.

    The caller numbers them, because numbers must continue the SIG sequence already shown to the
    Planner. An empty list means GRP holds nothing for this area and the brief stays SIG-only.
    """

    builders = (_population_citation, _shelter_citation)
    return [record for builder in builders if (record := builder(session, boundary)) is not None]


def attach_local_citations(
    pack: dict[str, Any], records: list[dict[str, Any]]
) -> dict[str, Any]:
    """Append GRP citations after SIG's, numbered to continue its sequence."""

    if not records:
        return pack
    citations = [item for item in pack.get("citations", []) if isinstance(item, dict)]
    next_n = max(
        (int(item["n"]) for item in citations if isinstance(item.get("n"), int)),
        default=0,
    )
    numbered = []
    for offset, record in enumerate(records, start=1):
        numbered.append({**record, "n": next_n + offset})
    return {
        **pack,
        "citations": citations + numbered,
        "_grp_local_citation_numbers": [item["n"] for item in numbered],
    }
