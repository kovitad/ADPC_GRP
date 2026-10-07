# ADR-0068: temporary public pilot feeds for ThaiWater and PM2.5

## Status

Accepted on 7 October 2026 for the temporary `servir-risk.kovitad.com` pilot.

## Context

ADR-0065 through ADR-0067 deliberately kept ThaiWater observations in shadow storage while
provider access, data quality and publication permission were assessed. The Product Owner has now
confirmed that publication was discussed with the providers and approved for this temporary pilot.
They also asked to compare the public ThaiWater feed operationally with the existing PM2.5 feed.

The approval does not turn station observations into warnings and does not approve an automatic
Global Risk contribution. Public routes must remain reversible and fail closed by default.

## Decision

1. Add `GET /api/v1/public/flood/{pilot_id}/government-observations/feed.json`, returning only the
   latest valid stored observation for each current ThaiWater station/product in the configured
   pilot boundary.
2. Publish values, units, datum, station location/name, originating agency, observation/retrieval
   times, a derived freshness limit and attribution. Do not publish API credentials, raw provider
   payloads, storage keys, internal hashes or unbounded history.
3. The endpoint reads the database only. It never contacts ThaiWater in a web request and remains
   separate from flood incidents, warnings, confidence and calculations.
4. `THAIWATER_FEED_PUBLIC=false` is the secure default. A disabled or unknown pilot returns 404.
   Anonymous reads are limited to 30 per caller per minute and cached for five minutes.
5. The existing PM2.5 endpoint remains controlled independently by
   `AIR_QUALITY_FEED_PUBLIC=false`. Deployment may deliberately enable both temporary pilot feeds
   with `--enable-public-pilot-feeds`.
6. Enabling the endpoints does not register or approve either feed as a Global Risk contribution.

## Consequences

The pilot can compare availability, coverage, record count and freshness across the two feeds.
Their values are not scientifically comparable: ThaiWater contains rainfall/water-level
observations while PM2.5 contains air-quality forecasts. Both switches can be turned off without
deleting captures or changing stored evidence.
