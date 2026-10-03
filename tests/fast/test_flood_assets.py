"""Facility exposure (ADR-0040): overlay is "potentially exposed", access is never "accessible"."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import core.flood_evidence.exposure as exposure_module
from core.db import Base
from core.flood_evidence.assets import (
    ACCESS_UNDER_REVIEW,
    ACCESS_UNKNOWN,
    NO_REPORT_NEARBY,
    POTENTIALLY_EXPOSED,
    AssetRegistryError,
    FloodedRoad,
    assess,
    asset_registry,
    distance_to_line_m,
    flooded_now,
    parse_assets,
)
from core.flood_evidence.config import pilot_config
from core.flood_evidence.exposure import latest_exposure
from core.flood_evidence.ingest import Pulled, ingest_body
from core.flood_evidence.models import FETCH_OK
from core.storage import LocalStorage

CONFIG = pilot_config("bangkok")
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "floodboard"
# An east-west road at latitude 13.8400.
ROAD = {"type": "LineString", "coordinates": [[100.5400, 13.8400], [100.5420, 13.8400]]}


def _asset(asset_id="osm:node/1", lat=13.8405, lon=100.5410, kind="hospital"):
    return {"asset_id": asset_id, "asset_type": kind, "name": "Test", "lat": lat, "lon": lon,
            "district_code": "1029", "source": "OpenStreetMap"}


def _road(closed=False, truck="caution", freshness="current", key="a" * 16):
    return FloodedRoad(road_key=key, geometry=ROAD, closed_all=closed, truck_verdict=truck,
                       freshness=freshness)


def test_shipped_facilities_are_osm_in_the_demo_corridor() -> None:
    assets, source = asset_registry("bangkok")
    assert len(assets) >= 20
    assert {a.district_code for a in assets} <= set(CONFIG.demo_corridor["areas"])
    assert {a.source for a in assets} == {"OpenStreetMap"}
    assert {a.asset_type for a in assets} <= {"hospital", "clinic", "school"}
    assert source["license"] == "ODbL 1.0" and source["osm_timestamp"]


@pytest.mark.parametrize(
    "item",
    [
        {**_asset(), "asset_type": "mall"},
        {**_asset(), "lat": 48.8},
        {k: v for k, v in _asset().items() if k != "lat"},
    ],
)
def test_bad_facility_entries_are_refused(item) -> None:
    with pytest.raises(AssetRegistryError):
        parse_assets({"assets": [item]})


def test_repeated_facility_ids_are_refused() -> None:
    with pytest.raises(AssetRegistryError):
        parse_assets({"assets": [_asset(), _asset()]})


def test_distance_to_a_line_is_measured_to_its_nearest_part() -> None:
    assert distance_to_line_m(100.5410, 13.8405, ROAD) == pytest.approx(55, abs=2)
    # Past the end of the line, the distance is to the end point.
    assert distance_to_line_m(100.5430, 13.8400, ROAD) == pytest.approx(108, abs=3)


def test_a_flooded_road_nearby_makes_a_facility_potentially_exposed_only() -> None:
    [record] = assess(parse_assets({"assets": [_asset()]}), [_road()], 150, 30)
    assert record["exposure_state"] == POTENTIALLY_EXPOSED
    assert record["access_state"] == ACCESS_UNKNOWN
    assert record["nearest_distance_m"] == pytest.approx(55, abs=2)
    assert record["road_keys"] == ["a" * 16]


def test_a_closed_or_truck_risky_road_at_the_door_puts_access_under_review() -> None:
    asset = parse_assets({"assets": [_asset(lat=13.8402)]})
    closed = assess(asset, [_road(closed=True)], 150, 60)[0]
    risky = assess(asset, [_road(truck="blocked")], 150, 60)[0]
    caution = assess(asset, [_road(truck="caution")], 150, 60)[0]
    assert closed["access_state"] == ACCESS_UNDER_REVIEW
    assert "frontage_road_closed" in closed["reasons"]
    assert risky["access_state"] == ACCESS_UNDER_REVIEW
    assert caution["access_state"] == ACCESS_UNKNOWN


def test_no_road_network_means_access_unknown_never_accessible() -> None:
    # Tweak scenario 8: with no flooding and no road graph, access is still unknown.
    [record] = assess(parse_assets({"assets": [_asset(lat=13.85)]}), [], 150, 60)
    assert record["exposure_state"] == NO_REPORT_NEARBY
    assert record["access_state"] == ACCESS_UNKNOWN
    assert "no_road_network" in record["reasons"]
    assert "accessible" not in json.dumps(record).replace("access_", "")


def test_only_current_uncleared_roads_count_as_flooding_now() -> None:
    def feature(**props):
        base = {"id": "b" * 16, "cleared": False, "freshness": "current", "closed_all": False,
                "provider_verdict": {"truck": "risky"}}
        return {"geometry": ROAD, "properties": {**base, **props}}

    roads = [feature(), feature(cleared=True), feature(freshness="stale"),
             feature(freshness="expired", provider_verdict=None)]
    assert len(flooded_now(roads)) == 1


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db


def test_the_worker_stores_exposure_with_each_snapshot(session, tmp_path, monkeypatch) -> None:
    body = (FIXTURES / "roads_20261003.geojson").read_bytes()
    features = json.loads(body)["features"]
    flooded = next(f for f in features if not f["properties"]["cleared"]
                   and f["properties"]["hw"] != "zone")
    lon, lat = flooded["geometry"]["coordinates"][0][0]
    registry = parse_assets({"assets": [_asset(lat=lat, lon=lon), _asset("osm:node/2", 13.95)]})
    monkeypatch.setattr(exposure_module, "asset_registry", lambda _pilot: (registry, {}))
    at = datetime.fromtimestamp(flooded["properties"]["updated"] / 1000, UTC)
    source = CONFIG.source("floodboard_roads")
    assert latest_exposure(session, CONFIG, at)["snapshot_retrieved_at"] is None
    ingest_body(session, LocalStorage(tmp_path), CONFIG, source, Pulled(200, body, FETCH_OK), at)
    session.commit()
    states = {a["asset_id"]: a for a in latest_exposure(session, CONFIG, at)["assets"]}
    assert states["osm:node/1"]["exposure_state"] == POTENTIALLY_EXPOSED
    assert states["osm:node/1"]["nearest_distance_m"] == 0
    assert states["osm:node/2"]["exposure_state"] == NO_REPORT_NEARBY
    assert {a["access_state"] for a in states.values()} <= {ACCESS_UNKNOWN, ACCESS_UNDER_REVIEW}
