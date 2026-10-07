# Claude Desktop prompt: test the ThaiWater and PM2.5 public feeds

**Date:** 7 October 2026  
**Pilot host:** `https://servir-risk.kovitad.com`  
**Purpose:** copy-ready prompts for the SERVIR Global Risk connector in Claude Desktop.

## Important warning

The connected Global Risk deployment previously **auto-approved** a test feed. A successful
`contribute_submit` may therefore make a feed public immediately, and contributors may be unable
to withdraw it. These prompts authorize one submission attempt for each named pilot feed. They do
not authorize retries, renamed duplicates, public answer receipts or changes to the manifests.

A failed attempt is a useful test result. If a call fails or times out, Claude must inspect
`contribute_status` before doing anything else and must not retry automatically.

## Public URLs to check first

- PM2.5: <https://servir-risk.kovitad.com/api/v1/public/aq/sea/feed.json>
- ThaiWater: <https://servir-risk.kovitad.com/api/v1/public/flood/bangkok/government-observations/feed.json>

Both should return HTTP 200 without signing in. PM2.5 currently has province forecast records;
ThaiWater has the latest valid water-level and 24-hour-rainfall observation per pilot station.

## Prompt 1: preflight both feeds without submitting

Copy the complete prompt below into Claude Desktop with the **SERVIR Global Risk** connector on.

```text
Use the SERVIR Global Risk MCP connector for this task.

First call platform_capabilities and confirm that contribute_submit, contribute_status and feeds_query are available, and that kind="feed" with adapter="generic_json" is supported.

Then perform a read-only preflight of these two anonymous JSON URLs if your available tools permit it:
1. https://servir-risk.kovitad.com/api/v1/public/aq/sea/feed.json
2. https://servir-risk.kovitad.com/api/v1/public/flood/bangkok/government-observations/feed.json

For each URL report whether it is reachable, whether the top-level records member is an array, the record count, the keys in one sample record, and the newest relevant timestamp. Do not print every record.

Do not call contribute_submit yet. Do not publish an answer or create a receipt. Do not modify either feed.
```

Expected approximate counts at the time this guide was written are 351 PM2.5 province forecasts
and 143 ThaiWater pilot observations. Counts may change legitimately.

## Prompt 2: make one PM2.5 submission attempt

This is a real contribution attempt, not a dry run. Copy the complete prompt below only when you
intend to run it.

```text
Use the SERVIR Global Risk MCP connector. Make exactly one contribution attempt using contribute_submit with kind="feed" and the manifest below.

Do not rename the dataset, alter fields, retry, submit a duplicate, publish an answer, or create a receipt. If validation declines it, show the complete safe validation message and stop. If the call times out or has an uncertain result, call contribute_status before doing anything else and stop after reporting whether this exact dataset appears. If it succeeds, immediately call contribute_status and report the contribution_id, state, reviewer or auto-approval status, record count, fetch time, and any warnings. Clearly warn me if approval is immediate and cannot be withdrawn by the contributor.

Manifest:
{
  "dataset": "sea_pm25_province_forecast",
  "title": "Southeast Asia PM2.5 forecast by province (latest 3-hour step)",
  "description": "One record per province in 11 Southeast Asian countries from SERVIR Southeast Asia / ADPC AQ Tracker: PM2.5 average and maximum at the 3-hour forecast step closest to now, with an indicative US EPA category. This is a NASA GEOS-CF bias-corrected model forecast, not a station measurement. ADPC GRP republishes it with forecast and validity times on every record.",
  "source": "SERVIR Southeast Asia / ADPC AQ Tracker, from NASA GEOS-CF (bias-corrected); republished by ADPC GRP",
  "validation": "single-agency",
  "residency": "external call-out",
  "cadence": "a new 3-hourly forecast step every 3 hours; new runs daily",
  "adapter": "generic_json",
  "fetch": {
    "url": "https://servir-risk.kovitad.com/api/v1/public/aq/sea/feed.json",
    "records_path": "records",
    "as_of_field": "forecast_time",
    "fields": {
      "province": "province",
      "country": "country",
      "area_id": "area_id",
      "pm25_avg": "pm25_avg",
      "pm25_max": "pm25_max",
      "category": "category",
      "lat": "lat",
      "lon": "lon",
      "forecast_time": "forecast_time",
      "init_date": "init_date",
      "valid_until": "valid_until"
    }
  },
  "pack": "risk",
  "hazards": ["air_quality", "pm25"],
  "countries": ["Thailand", "Laos", "Cambodia", "Vietnam", "Myanmar", "Malaysia", "Singapore", "Indonesia", "Philippines", "Brunei", "Timor-Leste"],
  "license": "Provider-approved temporary pilot publication; attribution required",
  "usage_notes": "Southeast Asia only, values in micrograms per cubic metre. The category is indicative because US EPA categories are for 24-hour averages while this is one 3-hour forecast step. This is a forecast, not a measurement. Check forecast_time and valid_until. Credit SERVIR Southeast Asia / ADPC AQ Tracker and NASA GEOS-CF."
}
```

## Prompt 3: make one ThaiWater submission attempt

ThaiWater remains operational observation evidence. Registering this feed must not turn its values
into warnings, incident confidence or a risk calculation.

```text
Use the SERVIR Global Risk MCP connector. Make exactly one contribution attempt using contribute_submit with kind="feed" and the manifest below.

Do not rename the dataset, alter fields, retry, submit a duplicate, publish an answer, or create a receipt. If validation declines it, show the complete safe validation message and stop. If the call times out or has an uncertain result, call contribute_status before doing anything else and stop after reporting whether this exact dataset appears. If it succeeds, immediately call contribute_status and report the contribution_id, state, reviewer or auto-approval status, record count, fetch time, and any warnings. Clearly warn me if approval is immediate and cannot be withdrawn by the contributor.

Manifest:
{
  "dataset": "bangkok_thaiwater_observations_pilot",
  "title": "Bangkok pilot ThaiWater government observations (latest by station)",
  "description": "Latest valid stored observation for each current ThaiWater station and product inside the ADPC GRP Bangkok and Nonthaburi pilot boundary. Products are water level in metres relative to the stated datum and rolling 24-hour rainfall in millimetres. These are government observations delivered by ThaiWater, not GRP warnings and not incident-confidence evidence.",
  "source": "ThaiWater, delivered by Hydro-Informatics Institute (HII); originating government agency stated per record; republished by ADPC GRP",
  "validation": "unvalidated",
  "residency": "external call-out",
  "cadence": "source checked every 15 minutes; latest valid value retained per station and product",
  "adapter": "generic_json",
  "fetch": {
    "url": "https://servir-risk.kovitad.com/api/v1/public/flood/bangkok/government-observations/feed.json",
    "records_path": "records",
    "as_of_field": "observed_at",
    "fields": {
      "product": "product",
      "station_id": "station_id",
      "station_name": "station_name",
      "variable": "variable",
      "value": "value",
      "unit": "unit",
      "longitude": "longitude",
      "latitude": "latitude",
      "observed_at": "observed_at",
      "retrieved_at": "retrieved_at",
      "valid_until": "valid_until",
      "is_stale": "is_stale",
      "delivery_provider": "delivery_provider"
    }
  },
  "pack": "risk",
  "hazards": ["flood", "rainfall"],
  "countries": ["Thailand"],
  "license": "Provider-approved temporary pilot publication; attribution required",
  "usage_notes": "Bangkok and Nonthaburi pilot area only. Water level and rainfall are different variables and must not be compared as one scale. A value is an observation, not a warning or proof of flooding. Check product, unit, observed_at, valid_until and is_stale. Credit ThaiWater, Hydro-Informatics Institute (HII), and the originating agency stated in each record."
}
```

## Test questions after submission

Run these only for a feed that `contribute_status` shows as staged or approved. These are feed
queries; do not ask Claude to call `publish_answer`.

### PM2.5

```text
Use feeds_query for sea_pm25_province_forecast with limit 20. Which returned provinces have the highest pm25_avg and pm25_max? Show country, province, values, category, forecast_time and valid_until. State clearly that this is a model forecast and that the category is indicative. Name the feed you used and report whether Global Risk marked it stale or preview-only. Do not publish an answer or create a receipt.
```

```text
Use feeds_query for sea_pm25_province_forecast with limit 351. Find Bangkok Metropolis, Nonthaburi and Pathum Thani. Compare their pm25_avg and pm25_max for the same forecast_time, and say if any record is missing or expired. Do not infer health advice beyond the feed's indicative category. Do not publish an answer or create a receipt.
```

### ThaiWater

```text
Use feeds_query for bangkok_thaiwater_observations_pilot with limit 50. Summarize how many returned records are water level and how many are 24-hour rainfall, the newest and oldest observed_at, and how many are stale. Keep metres and millimetres separate. Do not create a warning, flood-confidence statement, risk score, public answer or receipt.
```

```text
Use feeds_query for bangkok_thaiwater_observations_pilot. Show five newest records with station name, product, value, unit, observed_at, valid_until and delivery provider. Explain that a station observation alone does not prove flooding. Do not publish an answer or create a receipt.
```

### Operational comparison of both feeds

```text
Use feeds_query separately for sea_pm25_province_forecast and bangkok_thaiwater_observations_pilot. Compare only operational properties: fetch success, record count returned, geographic coverage, newest timestamp, valid_until behavior, staleness and attribution. Do not compare PM2.5 concentration numerically with rainfall or water level, do not combine them into a score, and do not publish an answer or create a receipt.
```

## What to record

For each attempted feed, save:

- UTC attempt time;
- exact dataset name;
- `contribution_id`, if returned;
- state: declined, staged/pending or approved;
- whether auto-approval occurred;
- fetched record count and sample fields;
- full safe warning or validation error;
- `feeds_query` result and staleness indicator;
- whether a duplicate/retry was avoided.

Never record OAuth tokens, cookies, API keys, raw secret files or Claude Desktop browser storage.
