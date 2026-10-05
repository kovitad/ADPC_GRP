# ThaiWater and HII integration research and plan

**Checked:** 5 October 2026

**Scope:** Bangkok and Nonthaburi flood pilot

**Decision record:** [ADR-0064](../adr/0064-thaiwater-requires-provider-approved-server-access.md)

## Executive finding

ThaiWater is technically relevant but is **not ready for a GRP server integration**.

- The current public application is `https://twa.thaiwater.net/th`; its API host is
  `https://twa-api-public.thaiwater.net`.
- The API publishes Swagger UI at `/api-docs`. The documented contracts cover rainfall, river and
  canal levels, discharge, reservoirs, gates/weirs, Bangkok road-flood sensors, Bangkok flow
  sensors, CCTV, flood products and agency metadata.
- Calls without credentials return `401 Unauthorized`. The website sends an `x-api-key`, but a key
  embedded for the website's own client is not permission for GRP to copy or reuse it.
- The Swagger contract lists `x-api-key` on many operations but does not state an external-use
  process, licence, attribution, retention permission, quota, service level or rate limits.
- HII's separate open-data catalogue is reachable without credentials and lists 36 datasets. Its
  water-level and rainfall archives are useful for historical analysis and replay, but they are
  not a live-feed substitute: on 5 October the newest non-empty monthly folders found were July
  2026.
- Every catalogue package is labelled “Creative Commons Attribution Non-Commercial”, but the
  package metadata gives no licence URL or version. That ambiguity, and the non-commercial
  restriction, require owner/legal confirmation before GRP redistributes or operationally uses
  the files.

**Recommendation:** approve a no-credential catalogue spike only. Do not enable TWA polling or
reuse any observed website key. Ask HII for written server-to-server access, exact terms and an
issued GRP credential. If approved, start with a small, stored-evidence pilot for selected water
level and rainfall stations; promote no data to operational flood evidence until field meaning,
quality, station identity and warning rules are reviewed.

## Authoritative sources checked

| Source | What was established | Checked |
| --- | --- | --- |
| `https://twa.thaiwater.net/th` | Current national water-information application and public map categories | 5 Oct 2026 |
| `https://twa-api-public.thaiwater.net/api-docs` | Public Swagger UI, OpenAPI 3.0.1, 531 paths/602 operations in the generated contract | 5 Oct 2026 |
| Unauthenticated API requests | `/v2/waterlevel` and `/v2/waterlevel/canal` return 401 without a credential | 5 Oct 2026 |
| `https://standard.thaiwater.net` | Official exchange schemas, API security options, quality flags, station references and warning guidance | 5 Oct 2026 |
| `https://data.hii.or.th/api/3/action/package_list` | HII CKAN catalogue contains 36 packages | 5 Oct 2026 |
| CKAN `package_show` and actual resource URLs | Dataset descriptions, contacts, licences, formats, archive structure and sample bytes | 5 Oct 2026 |
| `https://tiservice.hii.or.th/opendata/data_catalog/` | Open browsable rainfall and water-level archives and station metadata | 5 Oct 2026 |
| `https://standard.thaiwater.net/contact/` | HII contact form, `Contact@hii.or.th`, and telephone contact | 5 Oct 2026 |

The Swagger UI is useful technical documentation, not an access grant or data licence. The
ThaiWater Standard describes how providers can secure exchange APIs; it does not itself authorize
access to the TWA API.

## What the TWA contract contains

The generated Swagger document was inspected without invoking protected data operations. The
relevant documented groups are:

| Product | Representative paths (the live site uses a `/v2` prefix) | Important fields or behavior |
| --- | --- | --- |
| Rainfall | `/rainfall/{rainfall_type}`, `/list`, station detail and history graphs | Observation time/value, quality-flag source ID, station code/location, geography, agency and basin. Types include 24 h, today, daily, monthly, yearly, 3/5/7/15 day accumulations. |
| River level | `/waterlevel`, `/waterlevel/list`, station detail and graphs | Observation time, MSL level, percentage, bank difference/status, river, station thresholds, geography, agency and basin. |
| Canal level | `/waterlevel/canal`, `/list`, detail and graph | Time, inside/outside values, percentage/storage fields, station code/location, district/sub-district, agency and basin. |
| Discharge | `/waterlevel-discharge`, forecast/list/detail/table | Water level, discharge and forecast products. Forecasts must remain distinct from observations. |
| Gates and weirs | `/watergate`, `/list`, detail and graph | Inside/outside levels, pump and gate-opening fields, often nullable. |
| Reservoirs | `/large-dam/...`, `/medium-dam/...`, summary endpoints | Daily/hourly storage and provider summaries. |
| Bangkok flood products | `/flood/flood-bangkok`, `/flood/floodroad-bangkok`, `/flood/flow-measurement-bangkok` and lists/details | Catchment polygons; road-flood and flow station measurements; source meaning and operational currency still need confirmation. |
| CCTV | `/cctv`, `/list`, detail | Station/location, agency and media fields. Some examples contain legacy Flash/RTMP markup; do not proxy or retain media without permission and security review. |
| Provider judgements | flash-flood, floodplain, drought and ranking/summary endpoints | Derived provider products, not raw observations and not GRP-generated warnings. |
| Lineage | `/agency?dataset=...` | Agency names/codes by dataset. Preserve this alongside HII/TWA as the aggregator. |

The contract has significant warning signs for production consumers:

- `x-api-key` is documented as an optional header on 93 operations, while the gateway rejects
  unauthenticated requests. Security requirements in the OpenAPI document do not accurately
  describe that gateway behavior.
- No `429` response, quota, retry policy or rate-limit header is documented.
- Many schemas expose only a `200` response and examples rather than a complete failure contract.
- Example observations range from 2015 to 2025 and must not be mistaken for current coverage.
- Similar concepts use inconsistent names and shapes (`measureAt`, `waterlevelDatetime`,
  `waterlevel_datetime`; camelCase and snake_case; numbers and nullable fields).
- Administrative `districtCode` and `subdistrictCode` values in examples are local components,
  not guaranteed full Thai administrative codes. GRP must spatially place station coordinates
  against its version-pinned boundaries rather than concatenate or trust them blindly.

## The HII open-data catalogue

### Complete catalogue review

The 36 packages present on 5 October were:

`6months-forecast-rainfall`, `bathymetry`, `daily-report`, `dem-reservoir`,
`drought-risk-area`, `dsl`, `dsl-dry`, `flood-area`, `flood-mark`, `flood-risk-area`,
`forecast-rainfall`, `hii-rain-station-clustering`, `hii-rainfall`, `humid-mou`,
`hydro-historical-report`, `hydro-monthly-report`, `hydro-weekly-report`,
`map-pressure0dot6`, `map-pressure1dot5`, `performance-report`, `pressure`, `pressure-mou`,
`r35mm`, `rainfall-mou`, `ratingcurve`, `relative-humidity`, `road-level`, `spatial-rain`,
`swan-model`, `temperature`, `temperature-mou`, `terrain`, `tmax-tmin`, `water-level`,
`water_level-mou`, and `wrf-rom`.

All 36 carry the same human-readable non-commercial licence label. The catalogue is broader than
this pilot; the following resources received resource-level review.

### Resource findings relevant to GRP

| Package/resource | Finding | Recommended role |
| --- | --- | --- |
| `water-level` | Open monthly station CSVs, nominal 10-minute MSL observations, annual ZIPs and station metadata. Data from Feb 2026 claims ThaiWater Standard formatting. Missing sentinels include `-999`, `999999`, `9999` and `-`. | Historical/replay candidate; selected values may become observed context after validation. |
| `hii-rainfall` | Open hourly and daily archives. Daily accumulation is 07:01 to 07:00, not a calendar day. Missing sentinels are documented. | Rain context only, never direct flooding evidence. |
| `forecast-rainfall` and `6months-forecast-rainfall` | Machine-learning monthly/6-month products; resources are HTML, XLSX and CSV. | Outlook context, never an observation or incident corroboration. |
| `spatial-rain` | Monthly province/district interpolation based on TMD stations using IDW. | Climatological/research context, not live evidence. |
| `flood-area` | Monthly sub-district risk classes derived from 2005–2021 GISTDA satellite flood shapefiles. | Baseline susceptibility context; not a current flood footprint. |
| `flood-risk-area` | Six-month sub-district forecast combining baseline risk maps and forecast rain. Files are on share links rather than a stable machine API. | Provider-derived outlook only. |
| `road-level` | Surveyed road/embankment elevations at roughly 50 m spacing, metres MSL, distributed as Shapefile through a separate GIS file browser. Coverage must be checked per province. | Potential static terrain/defence context after licence, datum and coverage review. |
| `ratingcurve` | Elevation-capacity-area curves for small reservoirs, not river discharge-to-stage curves for Bang Bua Thong. | Not a substitute for the HAND plan's missing river Q-to-H relationship. |
| `daily-report`, `hydro-historical-report` | National reports and summary spreadsheets. | Human-readable context and event research; do not parse as live observations without a contract. |
| `flood-mark` | Catalogue candidate for surveyed flood marks; its sole resource needs local coverage and vertical-reference review. | Potential validation evidence, not live evidence. |

### Archive observations

Actual bytes, not only catalogue metadata, were checked.

- Water-level archive CSV columns are `station_code`, `measure_datetime`, `water_level`, and
  `quality_flag`. A July `BKK001` file had complete 10-minute rows from 1–31 July 2026 and `N`
  flags in the sampled rows.
- Hourly rain columns are `station_code`, `measure_datetime`, `rainfall_1h`, and `quality_flag`.
  A July `BKNH` file had hourly rows and `N` flags in the sampled rows.
- The 2026 directory contains folders through December, but October–December were empty when
  checked. July was the newest non-empty folder found for water level, hourly rain and daily rain.
  Folder existence is therefore not freshness evidence.
- The monthly `0station_metadata.csv` water file has a 12-column header but sampled water-level
  rows contain three additional threshold-like values before station type. This schema/header
  mismatch must be quarantined and reported, not silently shifted into the wrong fields.
- The catalogue's rainfall and water-level “all station metadata” downloads returned the same
  mixed 1,396-station inventory when checked. Filter station type; do not assume every listed
  station belongs to the dataset being downloaded.

### Pilot-area coverage in the open station inventory

The mixed station metadata contained:

- **Bangkok:** 11 stations — 10 labelled water level and one rainfall;
- **Nonthaburi:** three stations — two labelled water level and one rainfall.

The Nonthaburi entries were at Sai Noi and Pak Kret; none was labelled Bang Bua Thong. This is too
sparse to claim pilot-wide or sub-district coverage. It does not describe all stations aggregated
by the live TWA application, whose coverage must be measured under approved access.

## Standards that GRP should adopt

The official ThaiWater Standard separates observation time and system times. Its water-level
observation model includes:

- observing and editing agency codes/names and an originality indicator;
- station code and station-information reference;
- `measureTime`, `resultTime`, `createTime`, and `updateTime`;
- variable, value, unit, quality flag/comment, and quality-control level.

GRP should preserve equivalent concepts even when a provider endpoint omits them. Never collapse
source observation time into retrieval time.

Official quality flags are:

| Flag | Meaning | GRP treatment |
| --- | --- | --- |
| `U` | Unchecked | Display with warning; not sufficient alone for an operational conclusion. |
| `M` | Missing | Store lineage but no numeric observation. |
| `N` | Normal | Eligible after other validation. |
| `E` | Estimated | Label estimated and preserve comment/method. |
| `S` | Suspect | Quarantine from “current evidence”; may be shown as suspect. |
| `I` | Incorrect | Do not use as evidence. |
| `R` | Removed | Tombstone/supersede the value; do not continue serving it as current. |

The standard says `-999` can mark abnormal/missing values even where level-1 data otherwise uses
`U`. The catalogue documents additional sentinels. Validation must happen before decimal parsing
and aggregation.

## Evidence classification

| Product | GRP classification |
| --- | --- |
| Rain observation | Live or historical **context**, not proof of flooding. |
| Rain forecast | Provider forecast context, never an observation. |
| River/canal level | Direct evidence of level at one station. It is not automatically evidence that a road or sub-district is flooded. |
| Bank difference/status | Provider-derived station judgement. Use only after threshold semantics and datum are confirmed. |
| Discharge observation | Hydrological context/evidence at the station; not a flood depth. |
| Discharge forecast | Provider forecast, separate from observations. |
| Gate/pump state | Operational context; nullable/unknown must not become closed/off. |
| Road-flood sensor depth | Potential direct road evidence only after HII confirms units, sensor meaning, QA and licence. |
| Bangkok flood polygon | Provider-derived product; source method, timestamp meaning and coverage must be documented before use. |
| CCTV | Visual verification aid only, with reviewer/time/URL lineage; never machine-inferred flooding in this phase. |
| Flash-flood/flood-risk warning | Provider judgement, attributed to its issuing agency; GRP does not restate it as a GRP warning. |
| Historical flood area/flood mark | Validation or susceptibility evidence at its own vintage, never “live”. |

Nothing may be spatially averaged, inferred or apportioned from a district/station to a
sub-district. A point can be placed into the version-pinned GRP polygon by the worker, but the
measurement remains a point measurement.

## Proposed architecture after approval

### Acquisition boundary

1. A worker scheduler, never a web request, invokes a provider adapter.
2. Configuration uses a provider-issued credential from an `_FILE` secret. The key is never in a
   URL, log, database row, fixture, browser response or Git.
3. Use bounded connect/read timeouts, response byte limits, pagination caps, a descriptive user
   agent, exponential backoff with jitter and a circuit breaker.
4. Respect the written quota. Until HII supplies one, the integration stays disabled.
5. Every attempt creates a source-fetch record with request class (not secret-bearing URL), HTTP
   status, retrieval time, response hash, byte count, adapter version and success/failure reason.
6. Successful raw responses are immutable, encrypted/controlled storage objects with hashes.
   Malformed or over-limit responses are retained only if the approved retention policy permits,
   quarantined, and create no normalized observations.

### Normalized station and observation model

Keep at least:

- provider (`hii_twa` or `hii_open_data`) and dataset/product;
- source agency code/name separately from aggregator;
- provider station ID, station code, station name and station type;
- longitude/latitude as received, plus the boundary-release ID and worker-derived GRP area codes;
- variable, value, unit and datum/reference;
- observation/forecast-valid time, source create/update time and retrieval time as separate fields;
- quality flag, quality-control level, comment and estimated/derived status;
- raw-fetch ID, response hash, schema/adapter version and provider endpoint family;
- correction/supersession relationship rather than destructive overwrite.

Station identity is a mapping table keyed by provider + station code, not station name. Coordinate,
name, agency or type changes create reviewed station-version changes. Never merge similarly named
stations automatically.

### Freshness and clock safety

Freshness is based on **observation time**, never response retrieval time or endpoint-level
`updatedDate`. Initial bands must be empirically set per product after a 30-day approved capture;
they should not be copied from Floodboard blindly.

Until then, use conservative candidate rules:

- 10-minute water/rain feed: current up to 30 min, delayed up to 2 h, stale thereafter;
- hourly feed: current up to 2 h, delayed up to 6 h, stale thereafter;
- monthly archive/forecast: show period/vintage, not “live” freshness.

Reject from current-state calculations an observation too far in the future (candidate tolerance:
five minutes). Retain it as `clock_invalid`, show source unavailable/suspect, and alert operations.
Also detect backwards time, repeated timestamps with changed values, duplicates, impossible
coordinates, unit changes and stale endpoint-level update stamps.

### Read side and user interface

The API reads only normalized stored data. It never calls TWA.

- Show station, source agency, observed time, retrieved time, unit, quality and freshness.
- Say “Unavailable” or “Stale”, never zero/normal/no rain, after source failure.
- Keep observation, forecast, provider warning and GRP incident evidence visually distinct.
- Parent-area totals and station counts are coverage context, not inferred child-area values.
- Replays read an immutable raw/normalized capture selected by `as_of`; they never call TWA and
  never substitute today's corrected value silently.
- AI summaries receive explicit source type, time, quality and the rule that rain/forecast/level
  does not by itself mean flooding.

### Retention and redistribution

Do not set periods until HII confirms what may be retained and redistributed. The request should
cover raw API bodies, normalized values, screenshots/media URLs, derived summaries, replay and
public/Global Risk outputs.

A proposed operational baseline, subject to approval, is:

- raw successful responses: 90 days online, then controlled archive if permitted;
- normalized observations and lineage: pilot lifetime plus the audit period;
- quarantined/error bodies: 30 days, access restricted;
- CCTV images/video: do not retain in phase 1;
- access logs: follow GRP security retention, with keys redacted;
- deletion/correction notices: durable tombstones so replays remain explainable.

No TWA/HII record enters a public GRP feed or Global Risk contribution under the pilot approval
alone. Redistribution needs explicit written permission and attribution wording.

## Phased delivery plan

### Phase 0 — governance request (go now)

Owner: ADPC product/data owner. Send HII a written request covering:

1. supported external server-to-server API and production/staging base URLs;
2. how a GRP-specific API key is issued, rotated and revoked;
3. allowed client types and whether backend caching/storage/replay are permitted;
4. exact data licence/version, commercial/non-commercial interpretation for ADPC/GRP, attribution
   and whether downstream display/API/feed redistribution is allowed;
5. quotas, burst limits, polling guidance, `429`/retry behavior, fair-use rules and service status;
6. product/station coverage for Bangkok and Nonthaburi, especially canal level, road flood, flow,
   gates/weirs, rain, water level and CCTV;
7. units, vertical datums, timestamp timezone/semantics, quality flags and correction behavior;
8. endpoint lifecycle/versioning and notice period;
9. retention limits and treatment of CCTV/personal or complaint data;
10. operational and licensing contacts and incident/escalation route.

Use the official contact form or `Contact@hii.or.th`. The catalogue gives dataset contacts
`telem@hii.or.th` for telemetry and `hds@hii.or.th` for data-science products; copy them only as
appropriate. Do not send or mention the website's embedded key value.

**Exit gate:** written answers and an issued GRP credential. No answer means no TWA API build.

### Phase 1 — no-credential catalogue spike (approved in principle)

- Build an offline fixture importer for selected open `water-level` and `hii-rainfall` monthly
  CSVs, using small redacted/synthetic contract fixtures in Git.
- Generate a station coverage report for Bangkok and Nonthaburi from downloaded metadata.
- Validate sentinels, quality flags, timezone, exact column counts and monthly completeness.
- Record source URL, CKAN package/resource IDs, resource modified time, download time and SHA-256.
- Do not expose the result as live data or Global Risk evidence.

**Exit gate:** licence interpretation approved and schema anomalies resolved with HII. Otherwise
keep this as research tooling only.

### Phase 2 — approved authenticated shadow capture

- Implement the worker adapter behind `THAIWATER_PULLS_ENABLED=false`.
- Poll only an HII-approved minimal endpoint set and cadence, initially water level and rainfall.
- Capture for 30 days without changing operator-facing incident confidence or warnings.
- Produce daily source-health, latency, station churn, QA-flag, future-time and completeness
  reports. Compare TWA station identity with the archive, not values by station name.

**Exit gate:** ≥99% schema-valid pulls during the agreed service window, no secret leakage, stable
station mapping, reviewed freshness distributions, documented gaps and owner sign-off.

### Phase 3 — limited operator display

- Show selected station observations as attributed context in Live and Planning.
- Rain remains context. Water level remains point evidence unless an approved bank/status rule says
  more. Unknown/stale behavior is mandatory.
- Add source-health and coverage panels and replay from stored captures.

**Exit gate:** browser, permission, accessibility, bilingual, replay and fail-closed acceptance;
HII approves attribution presentation.

### Phase 4 — evidence promotion, one product at a time

Road-flood depth, reviewed station bank exceedance or provider flood polygons may become incident
corroboration only after a product-specific ADR records method, unit/datum, QA, freshness,
licence, false-positive handling and scientific/operational reviewer. No bulk promotion.

CCTV, provider warnings, public feed redistribution and HAND calibration are separate decisions.

## Required tests

- Contract fixtures for every approved endpoint and archive format, including null/type drift.
- Sentinel and quality-flag handling; `S/I/M/R` never become valid zeroes.
- Observation/source/retrieval timestamps remain distinct; timezone and future-clock rejection.
- Station versioning, duplicate names, moved coordinates and agency changes.
- Worker-derived district/sub-district placement against the pinned boundary release.
- Pagination/byte caps, timeouts, `401`, `403`, `429`, `5xx`, malformed JSON/CSV and partial pages.
- Last-good data keeps its true age; failed pulls display unknown/unavailable.
- Secrets absent from logs, errors, database, raw-object names, fixtures and API responses.
- Replays make zero network calls and reproduce the selected captured state.
- Rain and forecasts cannot raise flood confidence.
- Cross-Hub denial and no raw-source download route for ordinary operators.
- Golden values change only with scientific approval, never to match provider drift.

## Operational runbook requirements

Before enabling production polling, document:

- named ADPC service owner, HII contact and after-hours behavior;
- approved endpoint/cadence/quota table;
- key issue, storage, rotation and emergency revocation;
- dashboards for last success, observation lag, error class, station count/churn, schema drift,
  future timestamps, quality flags, bytes and quota headroom;
- alert thresholds and automatic circuit-breaker behavior;
- disable switch and rollback to stored last-good data;
- provider maintenance/licence-change review;
- raw/normalized retention and deletion procedure;
- replay and correction procedure;
- quarterly station/coverage and annual licence review.

## Go/no-go summary

| Question | State on 5 Oct 2026 | Gate |
| --- | --- | --- |
| Is a technically relevant API documented? | Yes | Passed for research only |
| Does it work without credentials? | No; 401 | Blocked |
| May GRP reuse the website key? | No evidence of permission | **No-go** |
| Is a GRP key/application process documented? | Not found | Blocked |
| Are API data licence and attribution explicit? | Not found | Blocked |
| Are quota/rate limits/retention explicit? | Not found | Blocked |
| Is open archive access available? | Yes | Catalogue spike only |
| Is archive licence unambiguous and compatible? | No; BY-NC label lacks version/URL | Legal/owner review |
| Is archive current enough for Live? | No; newest non-empty month found was July | Historical only |
| Is pilot coverage sufficient? | Sparse in open metadata; no Bang Bua Thong station labelled | No coverage claim |
| Can rainfall prove flooding? | No | Context only |
| Can any source calibrate HAND now? | No reviewed river Q-to-H/datum contract | Blocked |

**Current decision: no-go for live TWA ingestion; go for a bounded open-catalogue validation spike
and the provider authorization request.**
