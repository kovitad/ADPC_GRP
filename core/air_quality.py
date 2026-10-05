"""Southeast Asia PM2.5 from SERVIR-SEA's AQ Tracker, republished for Global Risk (ADR-0061).

AQ Tracker (SERVIR Southeast Asia / ADPC, from NASA GEOS-CF, bias-corrected) has a public feed
that needs no key: ``https://api-aq-servir.adpc.net/api/public/pm25/latest/``. It returns every
province (351 in 11 countries) at the 3-hourly step closest to now, highest PM2.5 first, with
the run and step times at the top level only.

Global Risk's ``generic_json`` reader keeps the *last* records and sorts only on a time inside
each record. Read directly, a default query would return the cleanest provinces. So GRP
republishes it:

- every record carries ``forecast_time``, ``init_date`` and ``valid_until``;
- records are ordered least concern first, so the worst provinces are the ones returned;
- an indicative US EPA category (2024 PM2.5 breakpoints) is added. The breakpoints are for
  24-hour averages, so one 3-hour step is only an indication.

The source reports a missing value as 0 on its keyed routes, so an average of exactly 0 is
treated as no data. A changed shape fails closed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

SOURCE_URL = "https://api-aq-servir.adpc.net/api/public/pm25/latest/"
FEED_VERSION = "sea-pm25-feed v1"
STEP = timedelta(hours=3)
# US EPA PM2.5 AQI categories, 2024 update (24-hour average, µg/m³): upper bounds.
CATEGORIES = (
    (9.0, "good"),
    (35.4, "moderate"),
    (55.4, "unhealthy_for_sensitive_groups"),
    (125.4, "unhealthy"),
    (225.4, "very_unhealthy"),
    (float("inf"), "hazardous"),
)
ROW_KEYS = ("area_id", "area_name", "country", "pm25_avg")
LIMITS = [
    "A model forecast (NASA GEOS-CF, bias-corrected by SERVIR-SEA), not a station measurement.",
    "The category is indicative: US EPA categories are for 24-hour averages, and this is one "
    "3-hour step.",
    "If a new run is late, the source keeps serving the last one: check forecast_time and "
    "valid_until.",
]


class AirQualityUnavailable(Exception):
    """The source could not be read, or its shape changed."""


def category(pm25: float | None) -> str | None:
    if pm25 is None:
        return None
    return next(name for upper, name in CATEGORIES if pm25 <= upper)


def _value(raw: Any) -> float | None:
    if raw is None:
        return None
    value = float(raw)
    return None if value == 0 else round(value, 2)  # 0 means no data at the source


def fetch_latest(client: httpx.Client | None = None) -> dict[str, Any]:
    own = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(20.0, connect=10.0))
    try:
        response = client.get(SOURCE_URL, headers={"Accept": "application/json"})
        if response.status_code != 200:
            raise AirQualityUnavailable(f"AQ Tracker answered HTTP {response.status_code}")
        return response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise AirQualityUnavailable(
            f"AQ Tracker could not be read ({type(error).__name__})"
        ) from error
    finally:
        if own:
            client.close()


def build_feed(source: dict[str, Any], retrieved_at: datetime) -> dict[str, Any]:
    """The republished document, or ``AirQualityUnavailable`` when the shape is not as known."""

    rows = source.get("data") if isinstance(source, dict) else None
    if not isinstance(rows, list) or not rows or source.get("adm_lvl") != "province":
        raise AirQualityUnavailable("AQ Tracker returned no province rows")
    try:
        step = datetime.fromisoformat(str(source["forecast_time"]).replace("Z", "+00:00"))
        init_date = str(source["init_date"])
    except (KeyError, ValueError) as error:
        raise AirQualityUnavailable("AQ Tracker's run or step time is missing") from error
    forecast_time = step.astimezone(UTC).isoformat().replace("+00:00", "Z")
    valid_until = (step + STEP).astimezone(UTC).isoformat().replace("+00:00", "Z")
    records = []
    for row in rows:
        if not isinstance(row, dict) or any(key not in row for key in ROW_KEYS):
            raise AirQualityUnavailable("AQ Tracker's row shape changed")
        average = _value(row.get("pm25_avg"))
        records.append({
            "area_id": row["area_id"],
            "province": row["area_name"],
            "country": row["country"],
            "lat": row.get("lat"),
            "lon": row.get("lon"),
            "pm25_avg": average,
            "pm25_min": _value(row.get("pm25_min")),
            "pm25_max": _value(row.get("pm25_max")),
            "category": category(average),
            "category_basis": "indicative: one 3-hour step against 24-hour US EPA breakpoints",
            "forecast_time": forecast_time,
            "init_date": init_date,
            "valid_until": valid_until,
        })
    # Least concern first (no data first), so Global Risk's default tail is the worst provinces.
    records.sort(key=lambda r: (r["pm25_avg"] is not None, r["pm25_avg"] or 0, str(r["area_id"])))
    return {
        "feed_version": FEED_VERSION,
        "source": "SERVIR Southeast Asia / ADPC AQ Tracker, from NASA GEOS-CF (bias-corrected)",
        "source_url": SOURCE_URL,
        "units": "µg/m³",
        "init_date": init_date,
        "forecast_time": forecast_time,
        "valid_until": valid_until,
        "retrieved_at": retrieved_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "count": len(records),
        "limits": LIMITS,
        "records": records,
    }
