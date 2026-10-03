"""Critical facilities near reported flooding: slice 4 of the Bangkok pilot (ADR-0040).

Two separate answers per facility, following the integration tweak:

- **exposure**: ``potentially_exposed`` when a road with flooding reported now lies within
  ``near_m`` of the facility. This is an overlay, never "the building is flooded".
  Otherwise ``no_report_nearby``, which means no report, not dry.
- **access**: ``access_under_review`` when a road right at the facility (within ``frontage_m``)
  is reported closed, or Floodboard rates it risky or impassable for a truck; an officer should
  check. Otherwise ``access_unknown``. GRP has no road network yet, so it never says a facility
  is accessible, and only an officer can record ``access_disrupted_confirmed`` (slice 5).

Only roads with current evidence count: expired, stale or cleared segments are ignored.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from core.flood_evidence.config import DATA
from core.flood_evidence.freshness import counts_as_current
from core.flood_evidence.geo import point_to_geometry_m

ASSET_TYPES = ("hospital", "clinic", "school")
POTENTIALLY_EXPOSED = "potentially_exposed"
NO_REPORT_NEARBY = "no_report_nearby"
ACCESS_UNDER_REVIEW = "access_under_review"
ACCESS_UNKNOWN = "access_unknown"
RULE_VERSION = "FacilityExposure v0.1"
REGION = (99.0, 12.5, 102.0, 15.5)


class AssetRegistryError(ValueError):
    """The facility file breaks a rule. The whole file is refused (fail closed)."""


@dataclass(frozen=True)
class Asset:
    asset_id: str
    asset_type: str
    name: str
    name_en: str
    lat: float
    lon: float
    district_code: str
    source: str

    def public(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "asset_type": self.asset_type,
            "name": self.name,
            "name_en": self.name_en,
            "lat": self.lat,
            "lon": self.lon,
            "district_code": self.district_code,
            "source": self.source,
        }


def parse_assets(raw: dict[str, Any]) -> tuple[Asset, ...]:
    assets = []
    for item in raw.get("assets", []):
        try:
            asset = Asset(
                asset_id=str(item["asset_id"]),
                asset_type=str(item["asset_type"]),
                name=str(item.get("name") or ""),
                name_en=str(item.get("name_en") or ""),
                lat=float(item["lat"]),
                lon=float(item["lon"]),
                district_code=str(item["district_code"]),
                source=str(item["source"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise AssetRegistryError("A facility is missing a required field") from error
        west, south, east, north = REGION
        if asset.asset_type not in ASSET_TYPES:
            raise AssetRegistryError(f"Unknown facility type {asset.asset_type!r}")
        if not (west <= asset.lon <= east and south <= asset.lat <= north):
            raise AssetRegistryError("A facility is outside the pilot region")
        assets.append(asset)
    if len({a.asset_id for a in assets}) != len(assets):
        raise AssetRegistryError("Facility IDs repeat")
    return tuple(assets)


@lru_cache
def asset_registry(pilot_id: str) -> tuple[tuple[Asset, ...], dict[str, Any]]:
    path = DATA / f"flood_pilot_{pilot_id}_assets.json"
    if not Path(path).exists():
        return (), {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return parse_assets(raw), dict(raw.get("_source") or {})


def distance_to_line_m(lon: float, lat: float, geometry: dict[str, Any]) -> float:
    """Metres from a point to the nearest part of a line (see ``core.flood_evidence.geo``)."""

    return point_to_geometry_m(lon, lat, geometry)


@dataclass(frozen=True)
class FloodedRoad:
    """A road with flooding reported now, as exposure sees it."""

    road_key: str
    geometry: dict[str, Any]
    closed_all: bool
    truck_verdict: str | None
    freshness: str


def flooded_now(roads: list[dict[str, Any]]) -> list[FloodedRoad]:
    """Road features (as the situation module serves them) that count as flooding now."""

    out = []
    for feature in roads:
        p = feature["properties"]
        if p.get("cleared") or not counts_as_current(p.get("freshness", "expired")):
            continue
        verdict = p.get("provider_verdict") or {}
        out.append(
            FloodedRoad(
                road_key=p["id"],
                geometry=feature["geometry"],
                closed_all=bool(p.get("closed_all")),
                truck_verdict=verdict.get("truck"),
                freshness=p["freshness"],
            )
        )
    return out


def assess(
    assets: tuple[Asset, ...], roads: list[FloodedRoad], near_m: float, frontage_m: float
) -> list[dict[str, Any]]:
    """One exposure record per facility, with the roads and distances behind it."""

    records = []
    for asset in assets:
        nearby = []
        for road in roads:
            distance = distance_to_line_m(asset.lon, asset.lat, road.geometry)
            if distance <= near_m:
                nearby.append((distance, road))
        nearby.sort(key=lambda item: item[0])
        frontage = [
            (d, r) for d, r in nearby
            if d <= frontage_m and (r.closed_all or r.truck_verdict in {"risky", "blocked"})
        ]
        reasons = []
        if frontage:
            reasons.append("frontage_road_closed" if frontage[0][1].closed_all
                           else "frontage_road_risky_for_trucks")
        if not nearby:
            reasons.append("no_flood_report_within_near_m")
        reasons.append("no_road_network")
        records.append(
            {
                "asset_id": asset.asset_id,
                "exposure_state": POTENTIALLY_EXPOSED if nearby else NO_REPORT_NEARBY,
                "access_state": ACCESS_UNDER_REVIEW if frontage else ACCESS_UNKNOWN,
                "nearest_road_key": nearby[0][1].road_key if nearby else None,
                "nearest_distance_m": round(nearby[0][0]) if nearby else None,
                "road_keys": [r.road_key for _, r in nearby[:10]],
                "reasons": reasons,
                "rule_version": RULE_VERSION,
            }
        )
    return records
