"""Find districts and sub-districts by name or by point (sub-district plan, 5 Oct 2026)."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import api.catalog as routes
from api.sessions import CurrentPrincipal
from core.access_models import Base, uuid7
from core.assessment_models import Boundary
from core.identity import MembershipView

DELIVERY = "ADPC Data Science Thailand hierarchy delivery"


def _principal() -> CurrentPrincipal:
    member = MembershipView(hub_id=uuid7(), hub_code="adpc", hub_name="ADPC", role="planner")
    return CurrentPrincipal(
        user_id=None, email="planner@example.test", display_name="Planner",
        is_platform_admin=False, memberships=(member,), issued_at=0, session_id="test",
    )


def _square(x0, y0, x1, y1):
    ring = [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]
    return {"type": "Polygon", "coordinates": [ring]}


def _area(code, name, name_th, level, geom, supported=True, source=DELIVERY):
    return Boundary(
        admin_code=code, admin_level=level, name=name, name_th=name_th,
        province_name="BANGKOK", province_name_th="กรุงเทพมหานคร", country_name="Thailand",
        geom=geom, source=source, edition="2025-10", geometry_sha256="a" * 64,
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
            _area("1029", "BANG SUE", "บางซื่อ", "district", _square(100.50, 13.80, 100.55, 13.85)),
            _area("102901", "BANG SUE", "บางซื่อ", "subdistrict",
                  _square(100.50, 13.80, 100.52, 13.85)),
            _area("102902", "WONG SAWANG", "วงศ์สว่าง", "subdistrict",
                  _square(100.52, 13.80, 100.55, 13.85)),
            _area("1030", "CHATUCHAK", "จตุจักร", "district", _square(100.55, 13.80, 100.60, 13.85)),
            _area("103001", "LAT YAO", "ลาดยาว", "subdistrict",
                  _square(100.55, 13.80, 100.60, 13.85)),
            # Not supported: never offered.
            _area("10", "BANGKOK", "กรุงเทพมหานคร", "province", _square(100, 13, 101, 14),
                  supported=False),
            # The synthetic test district overlaps on purpose.
            _area("9999", "SYNTHETIC", None, "district", _square(100.50, 13.80, 100.60, 13.85),
                  source="synthetic test data (not a real boundary)"),
        ])
        session.commit()
        yield session


def _search(world, q):
    return routes.search_areas(_principal(), world, q, None, 12)["areas"]


def test_a_sub_district_is_found_by_english_thai_or_squeezed_name(world) -> None:
    for q in ("wong sawang", "Wong Sawang", "wongsawang", "วงศ์สว่าง", "แขวงวงศ์สว่าง",
              "Khwaeng Wong Sawang"):
        names = [a["name"] for a in _search(world, q)]
        assert names[:1] == ["WONG SAWANG"], q
    first = _search(world, "wongsawang")[0]
    assert first["admin_level"] == "subdistrict"
    assert first["district"]["name"] == "BANG SUE"
    assert first["district"]["admin_code"] == "1029"


def test_the_district_comes_before_its_namesake_sub_district(world) -> None:
    areas = _search(world, "bang sue")
    pairs = [(a["admin_level"], a["admin_code"]) for a in areas[:2]]
    assert pairs == [("district", "1029"), ("subdistrict", "102901")]
    assert all(a["admin_level"] in {"district", "subdistrict"} for a in _search(world, "bangkok"))


def test_a_point_gives_its_sub_district_and_district(world) -> None:
    found = routes.area_at(_principal(), world, 13.8265, 100.5284, None)
    assert found["district"]["admin_code"] == "1029"
    assert found["subdistrict"]["admin_code"] == "102902"
    assert found["subdistrict"]["district"]["name"] == "BANG SUE"
    assert found["district"]["geometry"]["type"] == "Polygon"


def test_a_point_outside_every_area_finds_nothing(world) -> None:
    found = routes.area_at(_principal(), world, 15.0, 101.0, None)
    assert found == {"district": None, "subdistrict": None}
