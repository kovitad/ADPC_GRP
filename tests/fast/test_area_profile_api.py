"""The area profile reads one stored row and never implies a count it does not have."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import api.catalog as routes
from api.errors import GrpError
from api.sessions import CurrentPrincipal
from core.access_models import Base, uuid7
from core.assessment_models import Boundary, Dataset, DatasetVersion
from core.data_library_models import AreaPopulationSummary
from core.identity import MembershipView


def _principal() -> CurrentPrincipal:
    return CurrentPrincipal(
        user_id=None,
        email="planner@example.test",
        display_name="Planner",
        is_platform_admin=False,
        memberships=(
            MembershipView(hub_id=uuid7(), hub_code="adpc", hub_name="ADPC", role="planner"),
        ),
        issued_at=0,
        session_id="test",
    )


@pytest.fixture
def world():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        boundary = Boundary(
            admin_code="3303",
            admin_level="district",
            name="KANTHARAROM",
            name_th="กันทรารมย์",
            province_name="SI SA KET",
            country_name="Thailand",
            geom={"type": "Polygon", "coordinates": []},
            source="ADPC Data Science Thailand hierarchy delivery",
            edition="2025-10",
            geometry_sha256="a" * 64,
            is_supported=True,
        )
        dataset = Dataset(
            type="village_locations", owner_kind="platform", title="Villages", provider="ADPC"
        )
        session.add_all([boundary, dataset])
        session.flush()
        version = DatasetVersion(
            dataset_id=dataset.id,
            sha256="b" * 64,
            is_current=True,
        )
        session.add(version)
        session.flush()
        session.add(
            AreaPopulationSummary(
                dataset_version_id=version.id,
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
        session.commit()
        yield {"session": session, "boundary_id": boundary.id}


def test_a_planner_sees_the_stored_counts_with_the_unconfirmed_source_named(world) -> None:
    payload = routes.area_profile(world["boundary_id"], _principal(), world["session"], None)

    assert payload["area"]["name_th"] == "กันทรารมย์"
    assert payload["population"]["total_population"] == 85568
    assert payload["population"]["male"] + payload["population"]["female"] == 85568
    assert payload["population"]["village_count"] == 175
    assert payload["population"]["excluded_village_count"] == 1
    # The label must never let a planner read this as a vulnerability count.
    assert payload["source"]["label"] == "Registered village population"
    assert "not a count of vulnerable people" in payload["source"]["caveat"]
    assert "not yet confirmed" in payload["source"]["caveat"]


def test_an_area_with_no_summary_reports_none_rather_than_zero_people(world) -> None:
    session = world["session"]
    session.query(AreaPopulationSummary).delete()
    session.commit()

    payload = routes.area_profile(world["boundary_id"], _principal(), session, None)

    assert payload["population"] is None
    assert payload["source"] is None


def test_an_unsupported_area_is_not_found(world) -> None:
    session = world["session"]
    boundary = session.get(Boundary, world["boundary_id"])
    boundary.is_supported = False
    session.commit()

    with pytest.raises(GrpError) as error:
        routes.area_profile(world["boundary_id"], _principal(), session, None)

    assert error.value.status_code == 404
