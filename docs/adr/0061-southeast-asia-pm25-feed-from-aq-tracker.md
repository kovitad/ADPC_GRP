# ADR-0061: republish SERVIR-SEA's public PM2.5 feed for Global Risk

## Status

Accepted on 5 October 2026. It follows the owner's request to try the ADPC air-quality API (AQ
Tracker) as the next live feed, and section C of
[`docs/pilot/2026-10-05_Navigation_Live_Feeds_and_Air_Quality_Plan.md`](../pilot/2026-10-05_Navigation_Live_Feeds_and_Air_Quality_Plan.md).

## Context

- **No key needed.** The keyed AQ Tracker API answered 403 without a key. Its reference
  (`https://api-aq-servir.adpc.net/api/docs/`) also documents a **public feed that needs no
  key**: `https://api-aq-servir.adpc.net/api/public/pm25/latest/`.
- **What the public feed returns:**
  - named fields;
  - every province (351 in 11 countries) at the 3-hourly step closest to now;
  - highest PM2.5 first;
  - the run and step times at the top level only;
  - a 15-minute cache, and 60 requests a minute.
- **Why it cannot go to Global Risk as it is.** Global Risk's `generic_json` keeps the last
  records and sorts only on a time inside each record. Read directly, a default query returned the
  cleanest provinces (about 2 µg/m³, such as Mountain Province), which would mislead a planner.

## Decision

1. **`core/air_quality.py` republishes the public feed:**
   - every record carries `forecast_time`, `init_date` and `valid_until` (the step plus 3 hours);
   - records are least concern first, so the worst provinces are returned by default;
   - each record gets an indicative US EPA category (2024 PM2.5 breakpoints), labelled
     indicative because the categories are for 24-hour averages;
   - an average of exactly 0 is no data;
   - a changed shape fails closed.
2. **Routes:**
   - `GET /api/v1/air-quality/sea/latest` is protected (any signed-in member);
   - `GET /api/v1/public/aq/sea/feed.json` is public, and **404 unless
     `AIR_QUALITY_FEED_PUBLIC=true`**.
   - GRP keeps its own copy for 10 minutes, so pages and Global Risk add at most one read of
     AQ Tracker per 10 minutes.
3. **Manifest** `sea_pm25_province_forecast` (`core/data/live_feeds/`), listed in Share data
   under "From this platform": pack `risk`, hazards `air_quality` and `pm25`, 11 countries,
   `as_of_field: forecast_time`.
4. **Not submitted to Global Risk.** That deployment approves contributions at once and they
   cannot be withdrawn, so the feed waits for a permanent public address
   (`GRP_PUBLIC_FEED_BASE_URL`).

## Consequences

- **Real data, 5 October 2026** (run 4 October, step 04:30 UTC): Global Risk's own validator
  passes the manifest, and its reader returns, sorted by `forecast_time`:
  - Nonthaburi 94.7 µg/m³;
  - Bangkok Metropolis 83.1;
  - Pathum Thani 65.3;
  - Ba Ria–Vung Tau 61.3;
  - Ho Chi Minh 59.6.

  All are "unhealthy", as an indication.
- **The better fix belongs at the source.** If SERVIR-SEA adds the step time to each row and a
  lowest-first sort option, Global Risk can read their public feed directly, and GRP's copy can
  go.
- **The licence is unstated.** Confirm redistribution and the credit line with the AQ Tracker
  team before sending.
- **Global Risk's risk pack has no air-quality hazard raster.** So `feeds_query` will work, but
  `assemble_pack(risk, hazard="air_quality")` gives no exposure counts. That needs a maintainer
  question.
