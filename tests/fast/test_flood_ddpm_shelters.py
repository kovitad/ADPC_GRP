"""DDPM evacuation centres in the flood pilot's facility check (ADR-0056, step 4)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from core.access_models import Base
from core.assessment_models import Boundary, Dataset, DatasetVersion, Feature
from core.flood_evidence.assets import FloodedRoad, assess
from core.flood_evidence.config import pilot_config
from core.flood_evidence.ddpm_shelters import ddpm_shelters, pilot_assets

CONFIG = pilot_config("bangkok")


def _boundary(code: str) -> Boundary:
    return Boundary(admin_code=code, admin_level="district", name=f"D{code}", name_th=None,
                    province_name="P", province_name_th=None, country_name="Thailand",
                    geom={"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
                    source="Thailand hierarchy delivery", edition="2025-10",
                    geometry_sha256=code.ljust(64, "0"), is_supported=True)


def _version(session: Session, *, current: bool, hub_id=None) -> DatasetVersion:
    dataset = Dataset(type="evacuation_centers", owner_kind="platform" if hub_id is None
                      else "hub_local", title="Shelters", provider="DDPM", hub_id=hub_id)
    session.add(dataset)
    session.flush()
    version = DatasetVersion(dataset_id=dataset.id, sha256="a" * 64, meta={},
                             is_current=current, readiness="assessment_ready")
    session.add(version)
    session.flush()
    return version


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        lat_krabang, kantharalak = _boundary("1011"), _boundary("3303")
        db.add_all([lat_krabang, kantharalak])
        db.flush()
        current = _version(db, current=True)
        old = _version(db, current=False)
        db.add_all([
            Feature(dataset_version_id=current.id, boundary_id=lat_krabang.id,
                    name="วัดลาดกระบัง", lon=100.75, lat=13.72, facility_type="temple"),
            Feature(dataset_version_id=current.id, boundary_id=kantharalak.id,
                    name="outside Bangkok", lon=104.6, lat=15.1, facility_type="school"),
            Feature(dataset_version_id=old.id, boundary_id=lat_krabang.id,
                    name="old version", lon=100.75, lat=13.72, facility_type="temple"),
        ])
        db.commit()
        yield db


def test_only_current_baseline_shelters_inside_the_demo_area_are_added(session) -> None:
    shelters = ddpm_shelters(session, CONFIG)
    assert [s.name for s in shelters] == ["วัดลาดกระบัง"]
    shelter = shelters[0]
    assert shelter.asset_type == "evacuation_centre" and shelter.district_code == "1011"
    assert shelter.asset_id.startswith("ddpm:")
    assert shelter.source.startswith("DDPM evacuation centre (GRP data library)")


def test_the_combined_list_keeps_osm_and_says_how_many_shelters_it_added(session) -> None:
    assets, source = pilot_assets(session, CONFIG)
    assert source["ddpm_evacuation_centres"] == 1
    assert {a.asset_type for a in assets} >= {"school", "hospital", "evacuation_centre"}


def test_a_shelter_uses_the_same_exposure_rule_as_any_facility(session) -> None:
    [shelter] = ddpm_shelters(session, CONFIG)
    road = FloodedRoad(road_key="r" * 16, closed_all=False, truck_verdict="caution",
                       freshness="current",
                       geometry={"type": "LineString",
                                 "coordinates": [[100.7500, 13.7205], [100.7510, 13.7205]]})
    [record] = assess((shelter,), [road], near_m=150, frontage_m=60)
    assert record["exposure_state"] == "potentially_exposed"
    assert record["access_state"] == "access_unknown"


def test_flagged_and_synthetic_shelters_are_left_out(session) -> None:
    from sqlalchemy import select

    lat_krabang = session.scalar(select(Boundary).where(Boundary.admin_code == "1011"))
    current = session.scalar(select(DatasetVersion).where(DatasetVersion.is_current.is_(True)))
    synthetic = Dataset(type="evacuation_centers", owner_kind="platform", title="Synthetic",
                        provider="GRP synthetic test data")
    session.add(synthetic)
    session.flush()
    fake = DatasetVersion(dataset_id=synthetic.id, sha256="b" * 64, meta={}, is_current=True,
                          readiness="assessment_ready")
    session.add(fake)
    session.flush()
    session.add_all([
        Feature(dataset_version_id=current.id, boundary_id=lat_krabang.id, name="misplaced",
                lon=100.75, lat=13.72, attributes={"district_name_mismatch": True,
                                                   "claimed_province": "เพชรบุรี"}),
        Feature(dataset_version_id=fake.id, boundary_id=lat_krabang.id, name="made up",
                lon=100.75, lat=13.72, attributes={"synthetic": True}),
    ])
    session.commit()
    assert [s.name for s in ddpm_shelters(session, CONFIG)] == ["วัดลาดกระบัง"]
