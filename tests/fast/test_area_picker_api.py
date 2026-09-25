"""A picker can be built without shipping every district outline to the browser (backlog U2)."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import api.catalog as routes
from api.sessions import CurrentPrincipal
from core.access_models import Base, uuid7
from core.assessment_models import Boundary
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


def _area(code, name, level, province, province_th=None, supported=True) -> Boundary:
    return Boundary(
        admin_code=code,
        admin_level=level,
        name=name,
        province_name=province,
        province_name_th=province_th,
        country_name="Thailand",
        geom={"type": "Polygon", "coordinates": [[[100.0, 15.0]]]},
        source="ADPC Data Science Thailand hierarchy delivery",
        edition="2025-10",
        geometry_sha256="a" * 64,
        is_supported=supported,
    )


@pytest.fixture
def world():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([
            _area("3303", "KANTHARAROM", "district", "SI SA KET", "ศรีสะเกษ"),
            _area("3304", "KHUKHAN", "district", "SI SA KET", "ศรีสะเกษ"),
            _area("4405", "CHIANG YUEN", "district", "MAHA SARAKHAM", "มหาสารคาม"),
            _area("330301", "DUM YAI", "subdistrict", "SI SA KET", "ศรีสะเกษ"),
            # A province row exists in the delivery but is not a supported area.
            _area("33", "SI SA KET", "province", None, supported=False),
            # An unsupported district must not create a province entry of its own.
            _area("5001", "MUEANG CHIANG MAI", "district", "CHIANG MAI", supported=False),
        ])
        session.commit()
        yield session


def test_provinces_come_from_supported_districts_only(world) -> None:
    payload = routes.provinces(_principal(), world, None)

    names = [item["name"] for item in payload["provinces"]]
    # CHIANG MAI has only an unsupported district, so offering it would be a dead end.
    assert names == ["MAHA SARAKHAM", "SI SA KET"]
    by_name = {item["name"]: item for item in payload["provinces"]}
    assert by_name["SI SA KET"]["code"] == "33"
    assert by_name["SI SA KET"]["district_count"] == 2
    assert by_name["SI SA KET"]["name_th"] == "ศรีสะเกษ"


def test_a_province_is_never_offered_as_a_selectable_area(world) -> None:
    payload = routes.boundaries(_principal(), world, None, "district", None, None, True)

    levels = {item["admin_level"] for item in payload["boundaries"]}
    assert levels == {"district"}


def test_districts_can_be_narrowed_to_one_province(world) -> None:
    payload = routes.boundaries(_principal(), world, None, "district", None, "33", True)

    assert [item["name"] for item in payload["boundaries"]] == ["KANTHARAROM", "KHUKHAN"]


def test_geometry_can_be_left_out_so_a_dropdown_is_cheap(world) -> None:
    light = routes.boundaries(_principal(), world, None, "district", None, None, False)
    full = routes.boundaries(_principal(), world, None, "district", None, None, True)

    assert all("geometry" not in item for item in light["boundaries"])
    assert all("geometry" in item for item in full["boundaries"])
    # Everything a picker needs to label and group an option is still present.
    for item in light["boundaries"]:
        assert item["name"] and item["admin_code"] and item["id"]
        assert "province_name" in item and "name_th" in item


def test_subdistricts_still_narrow_by_their_parent_district(world) -> None:
    payload = routes.boundaries(_principal(), world, None, "subdistrict", "3303", None, False)

    assert [item["name"] for item in payload["boundaries"]] == ["DUM YAI"]
