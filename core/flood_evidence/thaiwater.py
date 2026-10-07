"""Bounded ThaiWater shadow capture for government rain and water-level observations.

ADR-0065 keeps these station observations separate from Floodboard impacts, GEOGLOWS forecasts
and official-source warnings. The worker stores immutable raw responses first, validates the whole
response, places stations against pinned pilot outlines and writes only pilot-area observations.
No web request calls ThaiWater and this module emits no warning or incident confidence.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.flood_evidence.areas import pilot_areas, pilot_subdistricts
from core.flood_evidence.config import PilotConfig, SourceConfig
from core.flood_evidence.geo import district_codes
from core.flood_evidence.ingest import (
    FETCH_TIMEOUT_SECONDS,
    IN_CHUNK,
    USER_AGENT,
    Pulled,
    last_attempt,
    record_raw_fetch,
    utc,
)
from core.flood_evidence.models import (
    FETCH_FORMAT_ERROR,
    FETCH_HTTP_ERROR,
    FETCH_NETWORK_ERROR,
    FETCH_OK,
    FETCH_TOO_LARGE,
    FloodSourceFetch,
    HydroObservation,
    HydroStationVersion,
)
from core.flood_evidence.observation import SourceFormatError
from core.storage import LocalStorage

PROVIDER = "thaiwater"
ADAPTER_VERSION = "ThaiWaterShadow v0.2"
FUTURE_TOLERANCE = timedelta(minutes=5)
DEFAULT_BASE_URL = "https://twa-api-public.thaiwater.net"


@dataclass(frozen=True)
class Product:
    source_id: str
    product: str
    path: str
    variable: str
    value_field: str
    time_fields: tuple[str, ...]
    unit: str
    datum: str | None
    interval_minutes: int = 15
    max_bytes: int = 20_000_000


PRODUCTS = (
    Product(
        source_id="thaiwater_waterlevel",
        product="waterlevel",
        path="/v2/waterlevel",
        variable="water_level",
        value_field="waterlevelMsl",
        time_fields=("waterlevelDatetime", "measureAt"),
        unit="m",
        datum="MSL",
    ),
    Product(
        source_id="thaiwater_rainfall_24h",
        product="rainfall_24h",
        path="/v2/rainfall/rainfall_c1440",
        variable="rainfall_24h",
        value_field="measureValue",
        time_fields=("measureAt",),
        unit="mm",
        datum=None,
    ),
)


@dataclass(frozen=True)
class StationDraft:
    provider_station_id: str
    identity_basis: str
    station_code: str | None
    station_name: str
    station_type: str | None
    longitude: float
    latitude: float
    agency_code: str | None
    agency_name: str | None
    source_admin: dict[str, Any]
    basin: dict[str, Any]


@dataclass(frozen=True)
class ValueDraft:
    station_id: str
    observed_at: datetime
    value: float
    quality_flag: str | None
    quality_control_level: str | None
    quality: dict[str, Any]


@dataclass(frozen=True)
class ParsedProduct:
    stations: tuple[StationDraft, ...]
    values: tuple[ValueDraft, ...]
    feature_count: int


def sources(base_url: str = DEFAULT_BASE_URL, interval_minutes: int | None = None) -> tuple[
    SourceConfig, ...
]:
    root = base_url.rstrip("/")
    return tuple(
        SourceConfig(
            source_id=p.source_id,
            adapter=p.product,
            url=f"{root}{p.path}",
            interval_minutes=interval_minutes or p.interval_minutes,
            max_bytes=p.max_bytes,
            registry={
                "provider": "Hydro-Informatics Institute (HII)",
                "delivery_provider": "ThaiWater",
                "product": p.product,
                "purpose": "Shadow government observation; not a GRP warning",
            },
        )
        for p in PRODUCTS
    )


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SourceFormatError(f"ThaiWater {label} must be an object")
    return value


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, (str, int)):
        raise SourceFormatError("ThaiWater identifier/name has the wrong type")
    cleaned = str(value).strip()
    return cleaned or None


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise SourceFormatError(f"ThaiWater {label} is not numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise SourceFormatError(f"ThaiWater {label} is not numeric") from error
    if not math.isfinite(number):
        raise SourceFormatError(f"ThaiWater {label} is not finite")
    return number


def _moment(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise SourceFormatError(f"ThaiWater {label} is not a timestamp")
    try:
        moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as error:
        raise SourceFormatError(f"ThaiWater {label} is not ISO-8601") from error
    if moment.tzinfo is None:
        raise SourceFormatError(f"ThaiWater {label} has no timezone")
    return moment.astimezone(UTC)


def _station_identity(
    station: dict[str, Any], agency: dict[str, Any], lon: float, lat: float
) -> tuple[str, str, str | None]:
    code = _text(station.get("stationCode") or station.get("code"))
    station_id = _text(station.get("id"))
    if station_id:
        return f"id:{station_id}", "provider_id", code
    if code:
        return f"code:{code}", "station_code", code
    name = _text(station.get("station") or station.get("stationName"))
    agency_code = _text(agency.get("agencyCode") or agency.get("id"))
    if not name or not agency_code:
        raise SourceFormatError("ThaiWater station has no stable ID/code fallback")
    fallback = f"{agency_code}|{name}|{lon:.6f}|{lat:.6f}"
    digest = hashlib.sha256(fallback.encode()).hexdigest()
    return f"fallback:{digest}", "agency_name_coordinate", None


def _observation_time(properties: dict[str, Any], product: Product) -> datetime | None:
    for field in product.time_fields:
        if properties.get(field) is not None:
            return _moment(properties[field], field)
    return None


def _missing_measurement(value: Any) -> bool:
    if value is None or (isinstance(value, str) and value.strip() == "-"):
        return True
    if isinstance(value, bool):
        return False
    try:
        return float(value) in {-999.0, 9999.0, 999999.0}
    except (TypeError, ValueError):
        return False


def parse_product(body: bytes, product: Product) -> ParsedProduct:
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SourceFormatError("ThaiWater response is not JSON") from error
    root = _object(payload, "response")
    result = root.get("result")
    if result is not None and result != "OK":
        raise SourceFormatError("ThaiWater result is not OK")
    if result is None:
        # The live v2 map endpoints use {meta, data}; older recorded responses use
        # {result: "OK", data}. Require one recognized success envelope rather than treating an
        # arbitrary object with a data member as successful.
        meta = _object(root.get("meta"), "meta")
        updated_at = meta.get("updatedDate")
        if updated_at is not None:
            _moment(updated_at, "meta.updatedDate")
    grouped = _object(root.get("data"), "data")
    stations: dict[str, StationDraft] = {}
    values: list[ValueDraft] = []
    feature_count = 0
    for collection in grouped.values():
        collection = _object(collection, "feature collection")
        if collection.get("type") != "FeatureCollection":
            raise SourceFormatError("ThaiWater data member is not a FeatureCollection")
        features = collection.get("features")
        if not isinstance(features, list):
            raise SourceFormatError("ThaiWater features must be an array")
        for feature in features:
            feature_count += 1
            feature = _object(feature, "feature")
            geometry = _object(feature.get("geometry"), "geometry")
            coordinates = geometry.get("coordinates")
            if geometry.get("type") != "Point" or not isinstance(coordinates, list) or len(
                coordinates
            ) < 2:
                raise SourceFormatError("ThaiWater station geometry must be a Point")
            lon = _number(coordinates[0], "longitude")
            lat = _number(coordinates[1], "latitude")
            if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                raise SourceFormatError("ThaiWater station coordinate is outside the world")
            properties = _object(feature.get("properties"), "properties")
            station = _object(properties.get("station"), "station")
            agency = _object(properties.get("agency") or {}, "agency")
            station_id, basis, station_code = _station_identity(station, agency, lon, lat)
            station_name = _text(station.get("station") or station.get("stationName"))
            if not station_name:
                raise SourceFormatError("ThaiWater station has no name")
            draft = StationDraft(
                provider_station_id=station_id,
                identity_basis=basis,
                station_code=station_code,
                station_name=station_name,
                station_type=_text(station.get("stationType") or station.get("type")),
                longitude=lon,
                latitude=lat,
                agency_code=_text(agency.get("agencyCode") or agency.get("id")),
                agency_name=_text(agency.get("agency") or agency.get("agencyName")),
                source_admin=dict(_object(properties.get("geoCode") or {}, "geoCode")),
                basin=dict(_object(properties.get("basin") or {}, "basin")),
            )
            previous = stations.get(station_id)
            if previous is not None and previous != draft:
                raise SourceFormatError("ThaiWater repeats a station with conflicting metadata")
            stations[station_id] = draft
            raw_value = properties.get(product.value_field)
            observed_at = _observation_time(properties, product)
            if _missing_measurement(raw_value):
                continue
            if observed_at is None:
                raise SourceFormatError("ThaiWater value has no observation time")
            value = _number(raw_value, product.value_field)
            if product.product == "rainfall_24h" and value < 0:
                raise SourceFormatError("ThaiWater rainfall cannot be negative")
            raw_flag = properties.get("qualityFlag")
            source_flag = properties.get("valueQualityFlagIdSource")
            values.append(
                ValueDraft(
                    station_id=station_id,
                    observed_at=observed_at,
                    value=value,
                    quality_flag=_text(raw_flag),
                    quality_control_level=_text(properties.get("qualityControlLevel")),
                    quality={
                        "provider_quality_flag": raw_flag,
                        "provider_quality_flag_source_id": source_flag,
                        "provider_status": properties.get("diffWlBankText"),
                        "provider_bank_difference": properties.get("diffWlBank"),
                    },
                )
            )
    return ParsedProduct(tuple(stations.values()), tuple(values), feature_count)


def _digest(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def station_version_hash(station: StationDraft) -> str:
    return _digest(
        {
            "name": station.station_name,
            "type": station.station_type,
            "code": station.station_code,
            "lon": station.longitude,
            "lat": station.latitude,
            "agency_code": station.agency_code,
            "agency_name": station.agency_name,
            "admin": station.source_admin,
            "basin": station.basin,
        }
    )


def observation_hash(product: Product, station: StationDraft, value: ValueDraft) -> str:
    return _digest(
        {
            "product": product.product,
            "station": station.provider_station_id,
            "station_version": station_version_hash(station),
            "variable": product.variable,
            "observed_at": value.observed_at.isoformat(),
            "value": value.value,
            "unit": product.unit,
            "datum": product.datum,
            "quality_flag": value.quality_flag,
            "quality_control_level": value.quality_control_level,
            "quality": value.quality,
        }
    )


def _chunks(values: Iterable[str]) -> Iterable[list[str]]:
    ordered = sorted(set(values))
    for start in range(0, len(ordered), IN_CHUNK):
        yield ordered[start : start + IN_CHUNK]


def _pilot_placement(
    station: StationDraft,
    areas: list[tuple[str, dict[str, Any]]],
    subdistricts: list[tuple[str, dict[str, Any]]],
) -> tuple[list[str], list[str]]:
    point = {"type": "Point", "coordinates": [station.longitude, station.latitude]}
    return district_codes(point, areas), district_codes(point, subdistricts)


def _store_parsed(
    session: Session,
    config: PilotConfig,
    fetch: FloodSourceFetch,
    product: Product,
    parsed: ParsedProduct,
    retrieved_at: datetime,
) -> tuple[int, int]:
    placed: list[tuple[StationDraft, list[str], list[str], str]] = []
    areas = [(a["admin_code"], a["outline"]) for a in pilot_areas(config)]
    subdistrict_areas = [
        (a["admin_code"], a["outline"]) for a in pilot_subdistricts(config)
    ]
    for station in parsed.stations:
        districts, subdistricts = _pilot_placement(station, areas, subdistrict_areas)
        if districts:
            placed.append((station, districts, subdistricts, station_version_hash(station)))

    existing_stations: dict[tuple[str, str], HydroStationVersion] = {}
    identities = [station.provider_station_id for station, _, _, _ in placed]
    for chunk in _chunks(identities):
        rows = session.scalars(
            select(HydroStationVersion).where(
                HydroStationVersion.pilot_id == config.pilot_id,
                HydroStationVersion.provider == PROVIDER,
                HydroStationVersion.product == product.product,
                HydroStationVersion.provider_station_id.in_(chunk),
            )
        )
        for row in rows:
            existing_stations[(row.provider_station_id, row.version_hash)] = row

    station_rows: dict[str, HydroStationVersion] = {}
    new_stations = 0
    for station, districts, subdistricts, version_hash in placed:
        key = (station.provider_station_id, version_hash)
        row = existing_stations.get(key)
        if row is None:
            new_stations += 1
            row = HydroStationVersion(
                pilot_id=config.pilot_id,
                provider=PROVIDER,
                product=product.product,
                provider_station_id=station.provider_station_id,
                identity_basis=station.identity_basis,
                station_code=station.station_code,
                station_name=station.station_name,
                station_type=station.station_type,
                longitude=station.longitude,
                latitude=station.latitude,
                geometry={"type": "Point", "coordinates": [station.longitude, station.latitude]},
                originating_agency_code=station.agency_code,
                originating_agency_name=station.agency_name,
                source_admin=station.source_admin,
                basin=station.basin,
                district_codes=districts,
                subdistrict_codes=subdistricts,
                version_hash=version_hash,
                first_seen_at=retrieved_at,
                last_seen_at=retrieved_at,
                first_fetch_id=fetch.id,
                last_fetch_id=fetch.id,
            )
            session.add(row)
            session.flush()
            existing_stations[key] = row
        elif retrieved_at >= utc(row.last_seen_at):
            row.last_seen_at = retrieved_at
            row.last_fetch_id = fetch.id
        station_rows[station.provider_station_id] = row

    stations_by_id = {station.provider_station_id: station for station, _, _, _ in placed}
    candidates: list[tuple[str, ValueDraft, StationDraft, HydroStationVersion]] = []
    for value in parsed.values:
        row = station_rows.get(value.station_id)
        station = stations_by_id.get(value.station_id)
        if row is not None and station is not None:
            candidates.append((observation_hash(product, station, value), value, station, row))

    existing_hashes: set[str] = set()
    for chunk in _chunks(digest for digest, _, _, _ in candidates):
        existing_hashes.update(
            session.scalars(
                select(HydroObservation.state_hash).where(
                    HydroObservation.pilot_id == config.pilot_id,
                    HydroObservation.provider == PROVIDER,
                    HydroObservation.product == product.product,
                    HydroObservation.state_hash.in_(chunk),
                )
            )
        )
    new_observations = 0
    for digest, value, station, station_row in candidates:
        if digest in existing_hashes:
            continue
        new_observations += 1
        session.add(
            HydroObservation(
                pilot_id=config.pilot_id,
                provider=PROVIDER,
                product=product.product,
                station_version_id=station_row.id,
                variable=product.variable,
                value=value.value,
                unit=product.unit,
                datum=product.datum,
                observed_at=value.observed_at,
                source_created_at=None,
                source_updated_at=None,
                retrieved_at=retrieved_at,
                quality_flag=value.quality_flag,
                quality_control_level=value.quality_control_level,
                quality=value.quality,
                clock_status=(
                    "future" if value.observed_at > retrieved_at + FUTURE_TOLERANCE else "valid"
                ),
                originating_agency_code=station.agency_code,
                originating_agency_name=station.agency_name,
                delivery_provider=PROVIDER,
                raw_fetch_id=fetch.id,
                state_hash=digest,
                adapter_version=ADAPTER_VERSION,
            )
        )
    return new_stations, new_observations


def ingest_product(
    session: Session,
    storage: LocalStorage,
    config: PilotConfig,
    source: SourceConfig,
    product: Product,
    pulled: Pulled,
    retrieved_at: datetime,
) -> FloodSourceFetch:
    fetch = record_raw_fetch(session, storage, config, source, pulled, retrieved_at)
    if pulled.outcome != FETCH_OK or pulled.body is None:
        return fetch
    try:
        parsed = parse_product(pulled.body, product)
        _new_stations, new_observations = _store_parsed(
            session, config, fetch, product, parsed, retrieved_at
        )
    except SourceFormatError as error:
        fetch.outcome = FETCH_FORMAT_ERROR
        fetch.error = str(error)[:500]
        session.flush()
        return fetch
    fetch.record_count = parsed.feature_count
    fetch.new_states = new_observations
    session.flush()
    return fetch


class ThaiWaterClient:
    def __init__(self, key: str) -> None:
        if not key.strip():
            raise ValueError("ThaiWater key is empty")
        self._key = key.strip()

    def fetch(self, source: SourceConfig) -> Pulled:
        try:
            headers = {
                "User-Agent": USER_AGENT,
                "Accept-Language": "en",
                "x-api-key": self._key,
            }
            with httpx.Client(
                timeout=FETCH_TIMEOUT_SECONDS, headers=headers, follow_redirects=True
            ) as client, client.stream("GET", source.url) as response:
                if response.status_code != 200:
                    return Pulled(
                        response.status_code, None, FETCH_HTTP_ERROR, "ThaiWater did not return 200"
                    )
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > source.max_bytes:
                        return Pulled(
                            response.status_code, None, FETCH_TOO_LARGE, "Over the byte cap"
                        )
                    chunks.append(chunk)
                return Pulled(response.status_code, b"".join(chunks), FETCH_OK)
        except httpx.HTTPError as error:
            return Pulled(None, None, FETCH_NETWORK_ERROR, type(error).__name__)


def run_shadow(
    session: Session,
    storage: LocalStorage,
    config: PilotConfig,
    client: ThaiWaterClient,
    now: datetime | None = None,
    base_url: str = DEFAULT_BASE_URL,
    interval_minutes: int = 15,
    fetcher: Callable[[SourceConfig], Pulled] | None = None,
) -> list[FloodSourceFetch]:
    """Capture due products for one live pilot. Replays never invoke this function."""

    if config.is_replay:
        raise ValueError("ThaiWater shadow capture is live-only")
    at = now or datetime.now(UTC)
    configured = sources(base_url, interval_minutes)
    by_product = {product.product: product for product in PRODUCTS}
    results = []
    for source in configured:
        previous = last_attempt(session, config.pilot_id, source.source_id)
        if previous is not None and at - utc(previous.retrieved_at) < timedelta(
            minutes=source.interval_minutes
        ):
            continue
        pulled = (fetcher or client.fetch)(source)
        fetch = ingest_product(
            session, storage, config, source, by_product[source.adapter], pulled, at
        )
        session.commit()
        results.append(fetch)
    return results


__all__ = [
    "ADAPTER_VERSION",
    "PRODUCTS",
    "ParsedProduct",
    "Product",
    "StationDraft",
    "ThaiWaterClient",
    "ValueDraft",
    "ingest_product",
    "parse_product",
    "run_shadow",
    "sources",
]
