"""ThaiWater Stage 0: strict parsing, immutable lineage and pilot-only shadow storage."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from core.db import Base
from core.flood_evidence.config import pilot_config
from core.flood_evidence.government_observations import government_observation_status
from core.flood_evidence.ingest import Pulled
from core.flood_evidence.models import (
    FETCH_FORMAT_ERROR,
    FETCH_HTTP_ERROR,
    FETCH_OK,
    FloodSourceFetch,
    HydroObservation,
    HydroStationVersion,
)
from core.flood_evidence.observation import SourceFormatError
from core.flood_evidence.thaiwater import (
    PRODUCTS,
    ThaiWaterClient,
    ingest_product,
    parse_product,
    run_shadow,
    sources,
)
from core.storage import LocalStorage

CONFIG = pilot_config("bangkok")
AT = datetime(2026, 10, 5, 12, tzinfo=UTC)


def _feature(
    *,
    product: str = "waterlevel",
    station_id: str = "318",
    code: str = "C00000002-WL.TEST.01",
    name: str = "คลองทดสอบ",
    lon: float = 100.562164,
    lat: float = 13.74325,
    observed_at: str = "2026-10-05T18:50:00+07:00",
    value: float | None = 0.75,
) -> dict:
    station = {
        "id": station_id,
        "stationCode": code,
        "station": name,
        "stationType": "m_canal_station" if product == "waterlevel" else "m_tele_station",
    }
    properties = {
        "id": f"observation-{station_id}",
        "type": product,
        "station": station,
        "geoCode": {
            "province": "กรุงเทพมหานคร",
            "provinceCode": "10",
            "district": "วัฒนา",
            "districtCode": "39",
            "subdistrict": "คลองเตยเหนือ",
            "subdistrictCode": "01",
        },
        "agency": {
            "id": 10,
            "agency": "สำนักการระบายน้ำ กรุงเทพมหานคร",
            "agencyCode": "C00000002",
        },
        "basin": {"basin": "ลุ่มน้ำเจ้าพระยา", "basinCode": "10"},
    }
    if value is not None:
        if product == "waterlevel":
            properties.update(
                waterlevelDatetime=observed_at,
                waterlevelMsl=value,
                diffWlBank=1.2,
                diffWlBankText="normal",
            )
        else:
            properties.update(
                measureAt=observed_at,
                measureValue=value,
                valueQualityFlagIdSource=1,
            )
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": properties,
    }


def _body(*features: dict) -> bytes:
    return json.dumps(
        {
            "result": "OK",
            "data": {"10": {"type": "FeatureCollection", "features": list(features)}},
        },
        ensure_ascii=False,
    ).encode()


WATER = _body(
    _feature(),
    # A station outside the pilot is valid source data but is not normalized in this slice.
    _feature(station_id="north", code="NORTH", name="เชียงใหม่", lon=98.98, lat=18.79),
)
RAIN = _body(_feature(product="rainfall", station_id="rain-1", code="RF.TEST.01", value=14.2))


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "storage")


def test_waterlevel_and_rain_are_distinct_observation_products() -> None:
    water = parse_product(WATER, PRODUCTS[0])
    rain = parse_product(RAIN, PRODUCTS[1])
    assert water.feature_count == 2 and len(water.values) == 2
    assert rain.feature_count == 1 and rain.values[0].value == 14.2
    assert water.values[0].observed_at == datetime(2026, 10, 5, 11, 50, tzinfo=UTC)
    assert water.stations[0].agency_code == "C00000002"


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        json.dumps({"result": "ERROR", "data": {}}).encode(),
        _body({**_feature(), "geometry": {"type": "LineString", "coordinates": []}}),
        _body(_feature(observed_at="2026-10-05 18:50:00", value=1.0)),
        _body(_feature(product="rainfall", value=-1.0)),
    ],
)
def test_a_malformed_response_fails_closed(body: bytes) -> None:
    product = PRODUCTS[1] if b"measureValue" in body else PRODUCTS[0]
    with pytest.raises(SourceFormatError):
        parse_product(body, product)


@pytest.mark.parametrize("missing", [None, -999, 9999, 999999, "-"])
def test_missing_measurement_keeps_station_coverage_without_inventing_zero(missing) -> None:
    feature = _feature(value=None)
    feature["properties"].update(
        waterlevelDatetime="2026-10-05T18:50:00+07:00", waterlevelMsl=missing
    )
    parsed = parse_product(_body(feature), PRODUCTS[0])
    assert len(parsed.stations) == 1
    assert parsed.values == ()


def test_shadow_storage_is_pilot_only_idempotent_and_correction_preserving(
    session: Session, storage: LocalStorage
) -> None:
    source = sources()[0]
    first = ingest_product(
        session, storage, CONFIG, source, PRODUCTS[0], Pulled(200, WATER, FETCH_OK), AT
    )
    session.commit()
    assert first.record_count == 2 and first.new_states == 1
    assert first.storage_key and first.sha256
    assert session.scalar(select(func.count()).select_from(HydroStationVersion)) == 1
    station = session.scalars(select(HydroStationVersion)).one()
    assert station.district_codes and station.subdistrict_codes
    assert station.source_admin["districtCode"] == "39"
    assert station.originating_agency_code == "C00000002"

    repeated = ingest_product(
        session,
        storage,
        CONFIG,
        source,
        PRODUCTS[0],
        Pulled(200, WATER, FETCH_OK),
        AT + timedelta(minutes=15),
    )
    session.commit()
    assert repeated.new_states == 0
    assert session.scalar(select(func.count()).select_from(HydroObservation)) == 1

    changed = _body(_feature(value=0.91))
    corrected = ingest_product(
        session,
        storage,
        CONFIG,
        source,
        PRODUCTS[0],
        Pulled(200, changed, FETCH_OK),
        AT + timedelta(minutes=30),
    )
    session.commit()
    assert corrected.new_states == 1
    values = session.scalars(select(HydroObservation.value).order_by(HydroObservation.value)).all()
    assert values == [0.75, 0.91]


def test_station_metadata_change_creates_a_new_version(
    session: Session, storage: LocalStorage
) -> None:
    source = sources()[0]
    ingest_product(session, storage, CONFIG, source, PRODUCTS[0], Pulled(200, WATER, FETCH_OK), AT)
    renamed = _body(_feature(name="คลองทดสอบ ชื่อแก้ไข"))
    fetch = ingest_product(
        session,
        storage,
        CONFIG,
        source,
        PRODUCTS[0],
        Pulled(200, renamed, FETCH_OK),
        AT + timedelta(minutes=15),
    )
    session.commit()
    assert fetch.new_states == 1
    assert session.scalar(select(func.count()).select_from(HydroStationVersion)) == 2
    assert session.scalar(select(func.count()).select_from(HydroObservation)) == 2


def test_future_observation_is_retained_but_marked_clock_invalid(
    session: Session, storage: LocalStorage
) -> None:
    future = _body(_feature(observed_at="2026-10-05T19:30:00+07:00"))
    ingest_product(
        session,
        storage,
        CONFIG,
        sources()[0],
        PRODUCTS[0],
        Pulled(200, future, FETCH_OK),
        AT,
    )
    session.commit()
    assert session.scalars(select(HydroObservation.clock_status)).one() == "future"


def test_format_failure_keeps_raw_lineage_and_no_normalized_rows(
    session: Session, storage: LocalStorage
) -> None:
    fetch = ingest_product(
        session,
        storage,
        CONFIG,
        sources()[0],
        PRODUCTS[0],
        Pulled(200, b"{}", FETCH_OK),
        AT,
    )
    session.commit()
    assert fetch.outcome == FETCH_FORMAT_ERROR and fetch.storage_key
    assert session.scalar(select(func.count()).select_from(HydroObservation)) == 0


def test_shadow_schedule_records_both_products_and_respects_interval(
    session: Session, storage: LocalStorage
) -> None:
    calls: list[str] = []

    def fetcher(source):
        calls.append(source.source_id)
        body = WATER if source.adapter == "waterlevel" else RAIN
        return Pulled(200, body, FETCH_OK)

    client = ThaiWaterClient("public-test-value")
    first = run_shadow(session, storage, CONFIG, client, AT, fetcher=fetcher)
    second = run_shadow(
        session, storage, CONFIG, client, AT + timedelta(minutes=14), fetcher=fetcher
    )
    third = run_shadow(
        session, storage, CONFIG, client, AT + timedelta(minutes=15), fetcher=fetcher
    )
    assert len(first) == 2 and second == [] and len(third) == 2
    assert calls == [
        "thaiwater_waterlevel",
        "thaiwater_rainfall_24h",
        "thaiwater_waterlevel",
        "thaiwater_rainfall_24h",
    ]
    assert session.scalar(select(func.count()).select_from(FloodSourceFetch)) == 4


def test_failed_pull_records_health_attempt_without_data(
    session: Session, storage: LocalStorage
) -> None:
    fetch = ingest_product(
        session,
        storage,
        CONFIG,
        sources()[0],
        PRODUCTS[0],
        Pulled(401, None, FETCH_HTTP_ERROR, "ThaiWater did not return 200"),
        AT,
    )
    session.commit()
    assert fetch.outcome == FETCH_HTTP_ERROR and fetch.http_status == 401
    assert fetch.storage_key is None
    assert session.scalar(select(func.count()).select_from(HydroObservation)) == 0


def test_protected_read_model_reports_health_and_coverage_without_values(
    session: Session, storage: LocalStorage
) -> None:
    configured = sources(interval_minutes=15)
    ingest_product(
        session, storage, CONFIG, configured[0], PRODUCTS[0], Pulled(200, WATER, FETCH_OK), AT
    )
    ingest_product(
        session, storage, CONFIG, configured[1], PRODUCTS[1], Pulled(200, RAIN, FETCH_OK), AT
    )
    session.commit()

    status = government_observation_status(
        session,
        CONFIG,
        AT + timedelta(minutes=1),
        capture_enabled=True,
        key_configured=True,
        base_url="https://example.invalid",
        interval_minutes=15,
    )
    assert status["state"] == "ok"
    assert status["publication_approved"] is False
    assert [product["product"] for product in status["products"]] == [
        "waterlevel",
        "rainfall_24h",
    ]
    water = status["products"][0]
    assert water["last_success_features"] == 2
    assert water["coverage"]["stations"] == 1
    assert water["coverage"]["districts"]
    assert water["coverage"]["subdistricts"]
    assert water["coverage"]["originating_agencies"] == [
        {"code": "C00000002", "name": "สำนักการระบายน้ำ กรุงเทพมหานคร", "stations": 1}
    ]
    assert water["observations"]["stored_observation_states"] == 1
    assert water["observations"]["clock_status_counts"] == {"valid": 1}
    # The protected health contract contains lineage and counts, never measurement values.
    assert "value" not in water["observations"]
    assert "latest_value" not in water


def test_read_model_distinguishes_disabled_missing_credential_and_failed_attempt(
    session: Session, storage: LocalStorage
) -> None:
    arguments = {
        "session": session,
        "config": CONFIG,
        "as_of": AT,
        "base_url": "https://example.invalid",
        "interval_minutes": 15,
    }
    disabled = government_observation_status(
        **arguments, capture_enabled=False, key_configured=False
    )
    missing = government_observation_status(
        **arguments, capture_enabled=True, key_configured=False
    )
    awaiting = government_observation_status(
        **arguments, capture_enabled=True, key_configured=True
    )
    assert disabled["state"] == "capture_disabled"
    assert missing["state"] == "credential_missing"
    assert awaiting["state"] == "awaiting_first_fetch"

    ingest_product(
        session,
        storage,
        CONFIG,
        sources()[0],
        PRODUCTS[0],
        Pulled(401, None, FETCH_HTTP_ERROR, "ThaiWater did not return 200"),
        AT,
    )
    session.commit()
    failed = government_observation_status(
        **arguments, capture_enabled=True, key_configured=True
    )
    assert failed["state"] == "offline"
    assert failed["products"][0]["last_attempt_outcome"] == FETCH_HTTP_ERROR
