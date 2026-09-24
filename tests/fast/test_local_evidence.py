"""GRP's own figures reach the brief as citations, and never borrow another area's numbers."""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from core.access_models import Base
from core.assessment_models import Boundary, Dataset, DatasetVersion, Feature
from core.data_library_models import AreaFloodExposure, AreaPopulationSummary
from core.local_evidence import (
    RETRIEVAL,
    attach_local_citations,
    local_area_citations,
)


def _boundary(code: str, name: str) -> Boundary:
    return Boundary(
        admin_code=code,
        admin_level="district",
        name=name,
        province_name="SI SA KET",
        country_name="Thailand",
        geom={"type": "Polygon", "coordinates": []},
        source="ADPC Data Science Thailand hierarchy delivery",
        edition="2025-10",
        geometry_sha256="a" * 64,
        is_supported=True,
    )


@pytest.fixture
def world():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        kanthararom = _boundary("3303", "KANTHARAROM")
        elsewhere = _boundary("3304", "KHUKHAN")
        villages = Dataset(
            type="village_locations", owner_kind="platform", title="Villages", provider="ADPC"
        )
        centers = Dataset(
            type="evacuation_centers", owner_kind="platform", title="DDPM", provider="DDPM"
        )
        session.add_all([kanthararom, elsewhere, villages, centers])
        session.flush()
        village_version = DatasetVersion(dataset_id=villages.id, sha256="b" * 64, is_current=True)
        center_version = DatasetVersion(dataset_id=centers.id, sha256="c" * 64, is_current=True)
        session.add_all([village_version, center_version])
        session.flush()
        session.add(
            AreaPopulationSummary(
                dataset_version_id=village_version.id,
                admin_code="3303",
                admin_level="district",
                village_count=175,
                counted_village_count=174,
                excluded_village_count=1,
                male=43309,
                female=42259,
                total_population=85568,
                households=23594,
            )
        )
        for index, (label, facility_type) in enumerate(
            [
                ("Centre 0", "school"),
                ("Centre 1", "school"),
                ("Centre 2", "temple"),
                ("Centre 3", None),
            ]
        ):
            session.add(
                Feature(
                    dataset_version_id=center_version.id,
                    boundary_id=kanthararom.id,
                    name=label,
                    facility_type=facility_type,
                    lon=104.0 + index / 100,
                    lat=15.0,
                )
            )
        session.commit()
        yield {"session": session, "area": kanthararom, "elsewhere": elsewhere}


def test_population_and_centre_counts_become_citations(world) -> None:
    records = local_area_citations(world["session"], world["area"])

    kinds = [item["kind"] for item in records]
    assert kinds == ["grp_population", "grp_evacuation_centers"]
    population = records[0]
    assert "85,568 registered residents" in population["text"]
    assert "175 villages" in population["text"]
    # The unconfirmed-source caveat must travel with the number into the brief.
    assert "not a count of vulnerable people" in population["text"]
    assert "1 of those villages is excluded" in population["text"]
    assert "4 evacuation centres" in records[1]["text"]
    # Largest kind first, and the unrecognised one admitted rather than folded into a kind.
    assert "2 school, 1 buddhist temple" in records[1]["text"]
    assert "A further 1 could not be classified" in records[1]["text"]
    # Capacity is not assessed, so the count must not read as a list of safe places.
    assert "not a list of safe places" in records[1]["text"]


def test_retrieval_is_not_marked_computed_so_sig_findings_are_not_suppressed(world) -> None:
    # _deterministic_evidence_summary prefers records whose retrieval starts with "computed" and
    # would otherwise drop every SIG finding in favour of GRP's own.
    for record in local_area_citations(world["session"], world["area"]):
        assert not record["retrieval"].casefold().startswith("computed")
    assert RETRIEVAL == "grp-baseline"


def test_an_area_with_no_rows_contributes_no_citations(world) -> None:
    records = local_area_citations(world["session"], world["elsewhere"])

    # No population row means no population citation: silence, never an implied zero.
    assert [item["kind"] for item in records] == ["grp_evacuation_centers"]
    assert "records no centres" in records[0]["text"]
    assert "not that the area has none" in records[0]["text"]


def test_citations_continue_the_sig_numbering(world) -> None:
    pack = {"citations": [{"n": 1, "text": "SIG one"}, {"n": 2, "text": "SIG two"}]}

    merged = attach_local_citations(pack, local_area_citations(world["session"], world["area"]))

    assert [item["n"] for item in merged["citations"]] == [1, 2, 3, 4]
    assert merged["_grp_local_citation_numbers"] == [3, 4]
    assert merged["citations"][0]["text"] == "SIG one"


def test_no_local_records_leaves_the_pack_untouched(world) -> None:
    pack = {"citations": [{"n": 1, "text": "SIG one"}]}

    assert attach_local_citations(pack, []) is pack


def test_centres_whose_names_say_nothing_get_no_invented_breakdown(world) -> None:
    session = world["session"]
    for feature in session.query(Feature).all():
        feature.facility_type = None
    session.commit()

    records = local_area_citations(session, world["area"])

    text = records[1]["text"]
    assert "4 evacuation centres" in text
    assert "do not identify what kind of place" in text
    # No count may be attached to any kind of place when none was recognised.
    assert "By kind of place" not in text
    assert "could not be classified" not in text


def _with_exposure(session, area, **overrides):
    """Add a current hazard version and one stored exposure row for the area."""
    hazard = Dataset(type="hazard", owner_kind="platform", title="RP100", provider="ADPC")
    session.add(hazard)
    session.flush()
    hazard_version = DatasetVersion(
        dataset_id=hazard.id, sha256="e" * 64, is_current=True, return_period_years=100
    )
    session.add(hazard_version)
    session.flush()
    village_version = session.scalar(
        select(DatasetVersion)
        .join(Dataset, Dataset.id == DatasetVersion.dataset_id)
        .where(Dataset.type == "village_locations")
    )
    row = {
        "village_count": 175,
        "measured_village_count": 170,
        "no_data_village_count": 5,
        "villages_in_zone": 40,
        "people_in_zone": 19500,
        "households_in_zone": 5200,
        "villages_in_zone_without_population": 2,
        "depth_bands": {"0–0.5 m": {"villages": 30, "people": 14000},
                        "1–1.5 m": {"villages": 10, "people": 5500}},
    }
    row.update(overrides)
    session.add(
        AreaFloodExposure(
            hazard_version_id=hazard_version.id,
            village_version_id=village_version.id,
            return_period_years=100,
            admin_code=area.admin_code,
            admin_level=area.admin_level,
            **row,
        )
    )
    session.commit()


def test_flood_exposure_states_the_count_and_what_it_could_not_measure(world) -> None:
    _with_exposure(world["session"], world["area"])

    records = local_area_citations(world["session"], world["area"])

    exposure = next(item for item in records if item["kind"] == "grp_flood_exposure")
    assert "19,500 registered residents" in exposure["text"]
    assert "40 villages" in exposure["text"]
    assert "100-year flood scenario" in exposure["text"]
    # The three honesty clauses, each of which a single number would hide.
    assert "5 of this area's 175 villages could not be measured" in exposure["text"]
    assert "is an undercount" in exposure["text"]
    assert "does not model which part of a village floods" in exposure["text"]
    assert "0–0.5 m: 30 villages" in exposure["text"]


def test_a_complete_sample_makes_no_excuses(world) -> None:
    _with_exposure(
        world["session"],
        world["area"],
        no_data_village_count=0,
        measured_village_count=175,
        villages_in_zone_without_population=0,
    )

    exposure = next(
        item
        for item in local_area_citations(world["session"], world["area"])
        if item["kind"] == "grp_flood_exposure"
    )
    assert "could not be measured" not in exposure["text"]
    assert "undercount" not in exposure["text"]


def test_no_exposure_row_stays_silent_rather_than_reporting_zero_exposed(world) -> None:
    # The job has not run for this pair of versions.
    records = local_area_citations(world["session"], world["area"])

    assert not any(item["kind"] == "grp_flood_exposure" for item in records)
