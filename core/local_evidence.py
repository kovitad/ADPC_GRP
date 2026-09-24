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
from core.data_library_models import AreaFloodExposure, AreaPopulationSummary
from core.facility_types import TYPE_LABELS, UNCLASSIFIED

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


def facility_type_counts(
    session: Session, version_id: Any, boundary_id: Any
) -> dict[str, int]:
    """Count recorded centres by derived facility type for one area.

    One indexed GROUP BY over a few hundred rows, so it stays inside the request budget without a
    summary table. NULL is reported as ``unclassified`` rather than dropped, because a breakdown
    that silently omits rows would not add up to the total a Planner is also shown.
    """

    rows = session.execute(
        select(Feature.facility_type, func.count(Feature.id))
        .where(
            Feature.dataset_version_id == version_id,
            Feature.boundary_id == boundary_id,
        )
        .group_by(Feature.facility_type)
    ).all()
    return {(facility_type or UNCLASSIFIED): int(count) for facility_type, count in rows}


def _facility_breakdown_sentence(counts: dict[str, int]) -> str:
    """Describe the mix, largest first, naming the unclassified remainder explicitly."""

    known = {key: value for key, value in counts.items() if key != UNCLASSIFIED}
    if not known:
        return (
            "The delivered names do not identify what kind of place any of these centres are, so "
            "no breakdown by school, temple or sports ground is available."
        )
    ordered = sorted(known.items(), key=lambda item: (-item[1], item[0]))
    described = ", ".join(
        f"{count:,} {TYPE_LABELS.get(key, key).lower()}" for key, count in ordered
    )
    sentence = f"By kind of place, as read from the delivered Thai names: {described}."
    unclassified = counts.get(UNCLASSIFIED, 0)
    if unclassified:
        sentence += (
            f" A further {unclassified:,} could not be classified from their delivered name and "
            "are not counted in any of those kinds."
        )
    return sentence


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
        counts = facility_type_counts(session, version.id, boundary.id)
        text = " ".join(
            [
                f"The current DDPM evacuation-centre release records {total:,} evacuation centres "
                f"in {_area_label(boundary)}.",
                _facility_breakdown_sentence(counts),
                "Centre capacity, building condition and route safety are not assessed, so this "
                "is a count of recorded centres and not a list of safe places.",
            ]
        )
    return {
        "title": f"Recorded evacuation centres, {boundary.name}",
        "text": text,
        "source": "GRP data library: DDPM evacuation centres",
        "retrieval": RETRIEVAL,
        "validation": "Counted from the current release assigned to this area.",
        "kind": "grp_evacuation_centers",
    }


def _exposure_citation(session: Session, boundary: Boundary) -> dict[str, Any] | None:
    """State how many people the exposure job measured inside the flood extent.

    Reads one stored row. The wording separates three things a single number would blur: people in
    the zone, villages that could not be measured at all, and in-zone villages whose population was
    unusable. Without that, a low figure reads as safety rather than as missing data.
    """

    hazard = _current_version(session, "hazard")
    village = _current_version(session, "village_locations")
    if hazard is None or village is None:
        return None
    row = session.scalar(
        select(AreaFloodExposure).where(
            AreaFloodExposure.hazard_version_id == hazard.id,
            AreaFloodExposure.village_version_id == village.id,
            AreaFloodExposure.admin_code == boundary.admin_code,
            AreaFloodExposure.admin_level == boundary.admin_level,
        )
    )
    if row is None:
        # No stored row means the exposure job has not run for this pair of versions. Stay silent:
        # an absent figure is not a zero, and the request must not compute one.
        return None
    sentences = [
        f"Under the {row.return_period_years}-year flood scenario, {row.people_in_zone:,} "
        f"registered residents live in the {row.villages_in_zone:,} villages of "
        f"{_area_label(boundary)} that fall inside the modelled flood extent, in "
        f"{row.households_in_zone:,} households.",
    ]
    bands = row.depth_bands if isinstance(row.depth_bands, dict) else {}
    if bands:
        described = ", ".join(
            f"{str(label)}: {int(value.get('villages', 0)):,} villages"
            for label, value in bands.items()
            if isinstance(value, dict)
        )
        sentences.append(f"By modelled water depth at the village point: {described}.")
    if row.no_data_village_count:
        sentences.append(
            f"{row.no_data_village_count:,} of this area's {row.village_count:,} villages could "
            "not be measured because they fall outside the flood layer's coverage or on a cell "
            "with no value, so they count as neither exposed nor dry."
        )
    if row.villages_in_zone_without_population:
        sentences.append(
            f"{row.villages_in_zone_without_population:,} villages inside the extent have no "
            "usable population figure, so the number of residents above is an undercount."
        )
    sentences.append(
        "A village is a point, so this counts villages whose recorded location falls in the "
        "extent; it does not model which part of a village floods."
    )
    return {
        "title": f"People inside the modelled flood extent, {boundary.name}",
        "text": " ".join(sentences),
        "source": "GRP data library: village points sampled against the flood layer",
        "retrieval": RETRIEVAL,
        "validation": "Computed outside the request from the current hazard and village versions.",
        "kind": "grp_flood_exposure",
    }


def local_area_citations(session: Session, boundary: Boundary) -> list[dict[str, Any]]:
    """Citation records for one verified area, in SIG's citation shape but unnumbered.

    The caller numbers them, because numbers must continue the SIG sequence already shown to the
    Planner. An empty list means GRP holds nothing for this area and the brief stays SIG-only.
    """

    builders = (_population_citation, _exposure_citation, _shelter_citation)
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
