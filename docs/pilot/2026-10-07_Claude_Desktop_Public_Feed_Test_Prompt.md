# Claude Desktop prompt: test the ThaiWater and PM2.5 public feeds

**Date:** 7 October 2026  
**Pilot host:** `https://servir-risk.kovitad.com`  
**Purpose:** copy-ready prompts for the SERVIR Global Risk connector in Claude Desktop.

## Important warning

The connected Global Risk deployment previously **auto-approved** a test feed. A successful
`contribute_submit` may therefore make a feed public immediately, and contributors may be unable
to withdraw it. These prompts authorize one submission attempt for each named pilot feed and one
separately named direct-upstream PM2.5 diagnostic. They do not authorize retries, renamed
duplicates, public answer receipts or changes to the manifests.

A failed attempt is a useful test result. If a call fails or times out, Claude must inspect
`contribute_status` before doing anything else and must not retry automatically.

## Public URLs to check first

- GRP-normalized PM2.5: <https://servir-risk.kovitad.com/api/v1/public/aq/sea/feed.json>
- Direct upstream PM2.5 diagnostic: <https://api-aq-servir.adpc.net/api/public/pm25/latest/?format=json>
- ThaiWater: <https://servir-risk.kovitad.com/api/v1/public/flood/bangkok/government-observations/feed.json>

All three should return HTTP 200 without signing in. PM2.5 currently has province forecast
records; ThaiWater has the latest valid water-level and 24-hour-rainfall observation per pilot
station.

A fourth dataset, `bangkok_flood_districts_live`, was submitted on 5 October as contribution
`47b51ee65c4659f9` and auto-approved, but it points to an expired temporary Cloudflare tunnel. Its
intended permanent route is
`https://servir-risk.kovitad.com/api/v1/public/flood/bangkok/feed.json`, which remains disabled
until regular Floodboard pulls and `FLOOD_FEED_PUBLIC` are deliberately enabled. Do not submit a
renamed duplicate and do not report the old contribution as current merely because Global Risk
still has a cached copy.

## Cadence and cache expectations

The `cadence` text sent in each contribution manifest describes when the underlying product should
change. It is not a promise that Global Risk will fetch that often.

| Feed | Cadence declared to Global Risk | Source/GRP endpoint cache | Timestamp to inspect | Current caveat |
| --- | --- | --- | --- | --- |
| Bangkok flood districts (`bangkok_flood_districts_live`) | Floodboard roads checked every 10 minutes; incidents recomputed whenever the export changes | GRP public response permits 1 minute when enabled | Each district record has `as_of` and `valid_until` | Previously auto-approved contribution `47b51ee65c4659f9` points to an expired temporary Cloudflare tunnel. The permanent Lightsail flood route and regular Floodboard pulls are not enabled; do not treat an old cached result as current. |
| GRP-normalized PM2.5 | New 3-hourly forecast step every 3 hours; new runs daily | GRP caches its upstream read for 10 minutes; its public response permits 5 minutes | Each record has `forecast_time` and `valid_until` | Province-level model forecast, not a station measurement. |
| Direct upstream PM2.5 diagnostic | New 3-hourly forecast step every 3 hours; source cache 15 minutes | Upstream HTTP response permits 15 minutes | `forecast_time` exists only at the top level, which is the diagnostic mismatch | Diagnostic representation of the same AQ Tracker/GEOS-CF product, not independent evidence. |
| ThaiWater pilot observations | Source checked every 15 minutes; latest valid value retained per station/product | GRP public response permits 5 minutes | Each record has `observed_at`, `retrieved_at` and `valid_until` | Pilot-wide station observations; current contribution mapping may not support a defensible district subset. |

Previous live-feed testing found that Global Risk may cache a fetched feed for up to **six hours**.
Consequently, `feeds_query` can return an older platform copy even while the source URL has newer
data. Every test must record the source timestamp, Global Risk pulled-at time, `stale_data` state and
warnings. Do not describe a record as current from cadence alone. For the direct upstream diagnostic,
do not invent per-record `forecast_time` or `valid_until` values that the source does not provide.

## Bangkok flood districts: URL and existing contribution

**Permanent feed URL (currently disabled):**
<https://servir-risk.kovitad.com/api/v1/public/flood/bangkok/feed.json>

The primary dataset was already submitted and auto-approved on 5 October 2026:

- dataset: `bangkok_flood_districts_live`;
- contribution ID: `47b51ee65c4659f9`;
- registered URL: an expired temporary Cloudflare tunnel;
- contributor withdrawal: refused because the contribution is already approved;
- permanent URL today: HTTP 404 because `FLOOD_FEED_PUBLIC=false`;
- regular Floodboard capture today: disabled, so the Lightsail database does not yet contain the
  normal district incident source needed for a meaningful feed.

Do not reuse or replace the primary name: `contribute_submit` cannot update an approved
contribution. The separately named diagnostic below is authorized only to discover how the
platform handles the currently disabled permanent URL. It must never be described as the
production flood feed.

Use this Claude Desktop prompt to inspect the existing registration:

```text
Use the SERVIR Global Risk MCP connector. Call contribute_status and find the exact contribution with dataset bangkok_flood_districts_live or contribution_id 47b51ee65c4659f9. Report its state, registered URL if exposed, contributor/reviewer, auto-approval status and audit warnings. Then call feeds_query for bangkok_flood_districts_live with limit 56. Report fetch success, pulled-at time, cache state, served_stale, stale reason, as_of, valid_until, record count and whether Bang Sue appears. Do not submit, retry, rename, withdraw, publish an answer or create a receipt. Treat any cached result from the expired tunnel as historical, not current.
```

### One-attempt diagnostic submission under a different name

The owner has authorized one diagnostic attempt even if it fails. The expected result while the
permanent endpoint returns 404 is a clear decline. If the platform unexpectedly accepts and
auto-approves it, report that as a platform issue because it accepted an unreachable feed.

```text
Use the SERVIR Global Risk MCP connector. Make exactly one contribute_submit call with kind="feed" and the manifest below. This is a diagnostic of the new Lightsail URL, not a replacement of the existing production dataset.

Do not change the dataset name, retry, create another name, publish an answer or create a receipt. Before submission, note the current HTTP result from the URL if your tools can check it. If contribution validation declines it because the endpoint is disabled, unreachable, empty or malformed, quote the complete safe error and stop; that is a successful diagnostic result. If the call times out or is ambiguous, call contribute_status and search for the exact diagnostic dataset before doing anything else. If it succeeds, immediately call contribute_status and report contribution_id, state, auto-approval, fetch result, record count, warnings and whether contributor withdrawal is possible. Then stop.

Manifest:
{
  "dataset": "bangkok_flood_districts_lightsail_diagnostic_20261007",
  "title": "DIAGNOSTIC: Bangkok and Nonthaburi flood districts from Lightsail",
  "description": "Diagnostic registration of the permanent ADPC GRP Lightsail flood-district endpoint. One record is expected for each of 56 Bangkok and Nonthaburi districts, with active/receding incidents, confidence wording and nearby-facility counts. Zero means no incident was found in available reports, not proof that a district is dry. This diagnostic must not replace or be confused with bangkok_flood_districts_live.",
  "source": "ADPC GRP Bangkok flood pilot, derived from Floodboard public sources and OpenStreetMap facilities",
  "validation": "unvalidated",
  "residency": "external call-out",
  "cadence": "Floodboard roads checked every 10 minutes; incidents recomputed whenever the export changes",
  "adapter": "generic_json",
  "fetch": {
    "url": "https://servir-risk.kovitad.com/api/v1/public/flood/bangkok/feed.json",
    "records_path": "districts",
    "as_of_field": "as_of",
    "fields": {
      "district_code": "district_code",
      "district": "district_name_en",
      "district_th": "district_name_th",
      "province": "province",
      "active": "active_incidents",
      "receding": "receding_incidents",
      "worst_confidence": "worst_confidence",
      "facilities_nearby": "facilities_nearby",
      "as_of": "as_of",
      "valid_until": "valid_until"
    }
  },
  "pack": "risk",
  "hazards": ["flood", "flashflood"],
  "countries": ["Thailand"],
  "license": "CC BY 4.0 derived from Floodboard; facility counts from OpenStreetMap under ODbL",
  "usage_notes": "DIAGNOSTIC FEED for Bangkok and Nonthaburi only. Do not interpret zero incidents as proof that a district is dry. Check as_of, valid_until and stale_data. Credit Floodboard and OpenStreetMap contributors. Do not use this diagnostic alongside bangkok_flood_districts_live as independent evidence."
}
```

### Observed diagnostic result, 7 October 2026

The test was run once and stopped as instructed:

- preflight at 05:19:56 UTC: HTTP 404 in 60 ms, no redirect and no `Cache-Control` header;
- body: `{"error":{"code":"NOT_FOUND","message":"We could not find this item.","support_ref":"GRP-64JL-33"}}`;
- one `contribute_submit` call sent at 05:20:01 UTC and answered in about 9.9 seconds;
- platform result: `declined`;
- exact problem: `the feed did not answer through generic_json: feed unavailable: HTTPError: 404 Client Error: Not Found for url: https://servir-risk.kovitad.com/api/v1/public/flood/bangkok/feed.json`;
- no `contribution_id`, approval, stored records, retry, alternate name, public answer or receipt;
- the existing `bangkok_flood_districts_live` contribution was untouched.

This confirms that the deployed platform performs a test pull through `generic_json` and refuses an
unreachable feed before storing the contribution. Because the result was an unambiguous decline,
no status lookup or withdrawal was necessary. The diagnostic name should remain unused; verify with
`contribute_status` before any future reuse if there is uncertainty. The support reference may help
correlate API logs but is not itself evidence that a server-side log entry exists.

If a later diagnostic is accepted, test it once:

```text
Use feeds_query for bangkok_flood_districts_lightsail_diagnostic_20261007 with limit 56. Report record count, whether all records have district_code, as_of and valid_until, whether Bang Sue is present, pulled-at/cache/stale state, and every warning. Do not treat it as independent from bangkok_flood_districts_live, publish an answer or create a receipt.
```

### Replacement after the Lightsail feed is genuinely ready

Because the old contribution cannot be updated by its contributor, a future replacement may use
`bangkok_flood_districts_live_v2`. Do not submit that production-style replacement until all of
these are true:

1. the Lightsail URL returns HTTP 200 anonymously;
2. regular Floodboard pulls are enabled and healthy;
3. the response contains all 56 district records;
4. every record has current `as_of` and `valid_until` values;
5. the diagnostic has been withdrawn or a maintainer confirms it will not be double-counted;
6. the Global Risk team agrees how to retire or exclude the broken original feed.

After the permanent endpoint is enabled and verified with 56 fresh district records, the safer
option is still to send this request to a Global Risk maintainer; it is not an MCP
`contribute_submit` call:

```text
Please repoint the already approved Global Risk feed bangkok_flood_districts_live, contribution ID 47b51ee65c4659f9, from its expired temporary Cloudflare tunnel to:
https://servir-risk.kovitad.com/api/v1/public/flood/bangkok/feed.json

Before changing it, please fetch and validate the endpoint, confirm it contains 56 district records under districts, confirm each record has as_of and valid_until, and preserve the existing dataset name and provenance. Please do not create a duplicate contribution. After repointing, please report the fetch time, record count, cache state and audit result.
```

For reference only, the original manifest uses `records_path="districts"`,
`as_of_field="as_of"`, cadence "Floodboard roads checked every 10 minutes", pack `risk`, hazards
`flood` and `flashflood`, and countries `["Thailand"]`. Do not send it again while contribution
`47b51ee65c4659f9` exists.

## Prompt 1: preflight the three active URLs without submitting

Copy the complete prompt below into Claude Desktop with the **SERVIR Global Risk** connector on.

```text
Use the SERVIR Global Risk MCP connector for this task.

First call platform_capabilities and confirm that contribute_submit, contribute_status and feeds_query are available, and that kind="feed" with adapter="generic_json" is supported.

Then perform a read-only preflight of these three anonymous JSON URLs if your available tools permit it:
1. https://servir-risk.kovitad.com/api/v1/public/aq/sea/feed.json
2. https://api-aq-servir.adpc.net/api/public/pm25/latest/?format=json
3. https://servir-risk.kovitad.com/api/v1/public/flood/bangkok/government-observations/feed.json

For each URL report whether it is reachable, its HTTP Cache-Control value, its records container (`records` or `data`), the record count, the keys in one sample record, and the newest relevant timestamp. Distinguish product cadence, endpoint cache duration and Global Risk's own fetched-copy age. Do not print every record.

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

## Prompt 2A: diagnose the upstream PM2.5 feed directly

This intentionally bypasses the GRP relay and uses a different diagnostic dataset name. The source
returns 351 records under `data`, but `forecast_time` and `init_date` exist only at the top level,
not inside each record. This test discovers whether Global Risk rejects that shape, accepts it with
missing timestamps, or silently orders records by source order. Any of those outcomes is useful to
report. A successful submission may still be auto-approved and permanent.

```text
Use the SERVIR Global Risk MCP connector. This is an authorized diagnostic test of the original upstream PM2.5 JSON, separate from the ADPC GRP relay. First call platform_capabilities and confirm kind="feed" and adapter="generic_json" are supported. Then make exactly one contribute_submit call with kind="feed" and the manifest below.

Keep the dataset name sea_pm25_upstream_direct_diagnostic_20261007 exactly as written so it cannot be confused with the GRP-normalized feed. Do not repair the source shape, copy top-level timestamps into records, rename the dataset, alter fields, retry, or submit a duplicate. Do not publish an answer or create a receipt.

The diagnostic question is whether Global Risk notices that fetch.as_of_field="forecast_time" names a top-level field while individual records under data do not contain forecast_time. If validation declines the contribution, quote the complete safe error and every rejected field, then stop. That declined result is a successful diagnostic outcome. If the call times out or is ambiguous, call contribute_status and search for this exact dataset before doing anything else, then stop. If the contribution succeeds, immediately call contribute_status and report contribution_id, state, reviewer or auto-approval state, fetched record count, sample fields, timestamp/staleness interpretation, warnings, and whether contributor withdrawal remains possible.

Manifest:
{
  "dataset": "sea_pm25_upstream_direct_diagnostic_20261007",
  "title": "DIAGNOSTIC: upstream Southeast Asia PM2.5 feed shape",
  "description": "Diagnostic direct registration of the SERVIR Southeast Asia / ADPC AQ Tracker public PM2.5 endpoint. It contains one province record per area, but forecast_time and init_date are top-level metadata rather than fields in each data record. This test is intended to expose validation, timestamp, ordering and staleness behavior. It is a NASA GEOS-CF bias-corrected model forecast, not a station measurement.",
  "source": "SERVIR Southeast Asia / ADPC AQ Tracker, from NASA GEOS-CF (bias-corrected), direct upstream diagnostic",
  "validation": "single-agency",
  "residency": "external call-out",
  "cadence": "a new 3-hourly forecast step every 3 hours; source cache 15 minutes",
  "adapter": "generic_json",
  "fetch": {
    "url": "https://api-aq-servir.adpc.net/api/public/pm25/latest/?format=json",
    "records_path": "data",
    "as_of_field": "forecast_time",
    "fields": {
      "province": "area_name",
      "country": "country",
      "area_id": "area_id",
      "pm25_avg": "pm25_avg",
      "pm25_min": "pm25_min",
      "pm25_max": "pm25_max",
      "lat": "lat",
      "lon": "lon"
    }
  },
  "pack": "risk",
  "hazards": ["air_quality", "pm25"],
  "countries": ["Thailand", "Laos", "Cambodia", "Vietnam", "Myanmar", "Malaysia", "Singapore", "Indonesia", "Philippines", "Brunei", "Timor-Leste"],
  "license": "Provider-approved temporary pilot publication; attribution required",
  "usage_notes": "DIAGNOSTIC FEED. The source keeps forecast_time and init_date at the top level, not per record. Do not treat missing record timestamps as current data. Values are micrograms per cubic metre from a model forecast, not station measurements. Credit SERVIR Southeast Asia / ADPC AQ Tracker and NASA GEOS-CF."
}
```

If it is accepted, run these read-only diagnostics:

```text
Use feeds_query for sea_pm25_upstream_direct_diagnostic_20261007 with limit 12. Show the returned order, province, country, pm25_avg and pm25_max. Also show the feed-level pulled-at time, record as-of value, stale_data state, record_order explanation and every warning exactly as returned. Determine whether the 12 records are the highest PM2.5 values, the lowest values, source order, or another order. Do not publish an answer or create a receipt.
```

```text
Use feeds_query for sea_pm25_upstream_direct_diagnostic_20261007 with limit 351. Report whether any returned record contains forecast_time, init_date or valid_until. Compare the newest-data/staleness claim made by Global Risk with the top-level forecast_time shown by the source, without inventing a per-record time. Do not publish an answer or create a receipt.
```

If both PM2.5 feeds were accepted, run this comparison:

```text
Query sea_pm25_upstream_direct_diagnostic_20261007 and sea_pm25_province_forecast separately with the same limit of 12. Compare record ordering, timestamp availability, valid_until, stale_data, warnings and the provinces returned. Explain which differences are caused by the upstream timestamps being top-level rather than repeated in every record. Do not combine the feeds, submit anything else, publish an answer or create a receipt.
```

### Short issue report for the team tonight

After the test, ask Claude:

```text
Prepare a concise technical issue report for the Global Risk team. Include UTC test time, MCP tool names, exact diagnostic dataset name, source URL, contribution_id and state if any, whether auto-approval occurred, expected behavior, observed behavior, the complete safe validation or warning text, record count, timestamp location mismatch, record ordering, stale_data behavior, duplicate/retry avoidance, and recommended platform change. Exclude OAuth tokens, cookies, API keys and secret values. Clearly separate facts observed from recommendations.
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

## Comprehensive Bang Sue (บางซื่อ) risk-pack report test

Use this only after checking the contribution names and states. It deliberately separates the
flood risk pack, ThaiWater observations and PM2.5 forecasts because they are different evidence
products. It also tests whether Global Risk can actually localize contributed feed rows to Bang
Sue rather than merely citing a Bangkok-wide or Southeast-Asia-wide feed.

```text
Use the SERVIR Global Risk MCP connector to prepare the most complete evidence report currently possible for Bang Sue District (บางซื่อ), Bangkok, Thailand. Do not publish the answer, call publish_answer, create a receipt, or submit any new contribution.

Follow this sequence and show the result of each step:

1. Call contribute_status and find the exact state, contribution_id, reviewer or auto-approval state for these datasets if they exist:
   - bangkok_thaiwater_observations_pilot
   - sea_pm25_province_forecast
   - sea_pm25_upstream_direct_diagnostic_20261007
   - bangkok_flood_districts_live
   Do not assume that a submitted feed is approved, live or current.

2. Call platform_capabilities and state which risk-pack, feed-query, place-resolution and hazard capabilities are actually available in this deployment.

3. Call assemble_pack with pack="risk", place="Bang Sue District, Bangkok, Thailand", hazard="flood". Report the resolved administrative area and polygon source, all flood-hazard layers, return periods or severity classes, and every exposure count returned for schools, hospitals, buildings, roads, population or contributed layers. Name every source and layer exactly. Do not invent a count for a category that the pack does not return.

4. If bangkok_flood_districts_live is visible, call feeds_query with limit 56. Find Bang Sue by the explicit district name/code in the returned records. Report active incidents, receding incidents, confidence wording, nearby facilities, as_of, valid_until, pulled-at/cache state and warnings. If the feed is unavailable, stale, still points to an expired temporary URL, or Bang Sue is absent, say so prominently and do not interpret zero as proof that Bang Sue is dry.

5. If bangkok_thaiwater_observations_pilot is visible, call feeds_query with a limit large enough to retrieve all current records (use 200 unless the tool reports a lower maximum). Keep water_level in metres and rainfall_24h in millimetres separate. Report record count, newest and oldest observed_at, retrieved_at, valid_until, stale records, station names, delivery provider and attribution. Include a Bang Sue-specific station/value section only if the returned fields explicitly establish that the station belongs to Bang Sue through an administrative name/code or a platform-supported point-in-polygon result. Do not infer district membership from a station name or nearby coordinate. If the contributed field mapping does not expose district membership, state that the feed is pilot-wide and cannot yet support a defensible Bang Sue subset.

6. If sea_pm25_province_forecast is visible, call feeds_query with limit 351 and find the explicit province record for Bangkok Metropolis. Report pm25_avg, pm25_max, indicative category, forecast_time, init_date, valid_until, pulled-at/cache state and warnings. Label it Bangkok-province context, not a Bang Sue district measurement and not a station observation. Do not infer a Bang Sue-specific concentration from the province average.

7. If sea_pm25_upstream_direct_diagnostic_20261007 is visible, query it separately. Compare its timestamp, ordering, as_of and stale_data behavior with sea_pm25_province_forecast. Keep it in a diagnostic appendix and do not count it as independent corroboration because both PM2.5 feeds originate from the same AQ Tracker/GEOS-CF product.

8. Produce one structured report with these headings:
   A. Executive summary
   B. Area resolution and administrative boundary
   C. Flood hazard and exposed assets from the risk pack
   D. Reported flood incidents and their freshness
   E. ThaiWater water-level observations
   F. ThaiWater 24-hour rainfall observations
   G. PM2.5 Bangkok-province forecast context
   H. Source lineage, validation and independence
   I. Freshness, cache and stale-data table
   J. Missing evidence and localization limitations
   K. Contradictions or duplicated sources
   L. Recommended verification actions for an operator tonight

For every numerical statement, cite the exact layer/feed, timestamp and unit. Distinguish model forecasts, station observations, reported impacts and static return-period exposure. Never combine PM2.5, rainfall, water level and flood exposure into one score. Never call a place safe, issue a flood or health warning, invent thresholds, or treat two delivery paths for the same underlying source as independent confirmation. Separate facts observed from interpretation.
```

### What a defensible result should say

- The flood risk pack may provide district-polygon hazard/exposure counts, but only for layers that
  the platform actually returns.
- `bangkok_flood_districts_live` can localize by district when reachable, but an old cached zero is
  not evidence that Bang Sue is dry.
- The current ThaiWater contribution mapping is pilot-wide. It does not map `district_codes` into
  Global Risk, so it may be impossible to select Bang Sue defensibly even though GRP's source
  endpoint stores pilot-area codes. The report must expose this gap rather than guess.
- PM2.5 is province-level model context for Bangkok Metropolis, not a Bang Sue measurement.
- The normalized and direct PM2.5 feeds are two representations of the same upstream product, not
  independent evidence.
- `assemble_pack(risk, hazard="air_quality")` may have no air-quality hazard raster or exposure
  calculation; `feeds_query` can still return the PM2.5 forecast.

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
