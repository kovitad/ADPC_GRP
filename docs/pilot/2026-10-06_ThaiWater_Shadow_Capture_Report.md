# ThaiWater shadow capture report — 6 October 2026

## Decision summary

The confirmed public website key was configured only in the ignored local `.env`, copied by the
Desktop launcher into its local secret file and successfully used against both approved endpoints.
The key value is not recorded here, in Git, in logs or in an API response.

Three controlled captures over about 48 minutes passed authentication, transport, whole-response
parsing, immutable raw storage, pilot placement and canonical storage. Continued shadow collection
is reasonable.
Publishing station measurements or adding a user-facing layer is **not yet approved** because this
is only a short sample, water-level coverage is sparse, provider quality flags are absent for every
placed observation, Bang Bua Thong has no placed station in either product, and sensor-origin
overlap with Floodboard cannot yet be resolved.

## Environment and run

- Local Docker Desktop only; ThaiWater remained separate from public feeds and incidents.
- Database migration: `20261005_0028` (head).
- Retrieval times: `2026-10-06T02:17:31.898551Z`, `2026-10-06T02:22:48.587229Z` and
  `2026-10-06T03:05:11.517191Z`.
- Both product health states after capture: `ok`; `publication_approved=false`.
- The first two pulls used a deliberately enabled worker window. The third was a bounded one-shot
  worker invocation after validation. The persistent capture switch remains false and cadence is
  15 minutes. Stored results remain available; overall readiness therefore reports
  `capture_disabled`.
- API and worker were healthy after rebuild.
- A logging-only `DetachedInstanceError` occurred after both product commits had succeeded. The
  worker attempted to log expired ORM rows after closing their session. Storage was unaffected;
  the worker now snapshots log fields while the session remains open.

## Live schema finding

Both live v2 endpoints returned HTTP 200. Their current envelope is `{meta, data}`, with
`meta.updatedDate=null`; it does not contain the older `result="OK"` member used by recorded
examples. Inside `data`, every member was a GeoJSON `FeatureCollection` with point features. The
station, agency, geography, basin, observation-time and value fields expected by the adapter were
present.

The strict parser now accepts exactly two recognized success envelopes:

1. the older `{result: "OK", data}` form; or
2. the current `{meta, data}` form, validating a non-null `meta.updatedDate` as a zoned timestamp.

An object with only `data`, a non-OK `result`, or an invalid metadata timestamp still fails closed.
The first two captures retain adapter lineage `ThaiWaterShadow v0.1`; the reviewed envelope change
was used by the third capture as `ThaiWaterShadow v0.2`.

## Capture results

First pull:

| Product | Provider features | Pilot stations | Observation states | Districts | Sub-districts | Raw bytes | Gzip bytes |
|---|---:|---:|---:|---:|---:|---:|---:|
| Water level | 798 | 12 | 12 | 10 | 12 | 844,551 | 89,668 |
| Rainfall, previous 24 hours | 2,944 | 125 | 125 | 52 | 93 | 2,497,324 | 209,227 |

Second pull, about five minutes later:

- Water level contained 800 provider features and created 10 new pilot observation states. The
  latest pilot observation advanced from `02:00Z` to `02:10Z`; 2 of the 12 pilot stations did not
  produce a new state in that interval.
- Rainfall contained the same 2,944 features, identical raw SHA-256 and created zero new states,
  proving idempotence for the unchanged response.
Third pull, about 42 minutes later:

- Water level contained 799 provider features and created 11 new pilot states. The latest pilot
  observation advanced to `02:50Z`; the same 12 pilot station identities and metadata versions
  remained present.
- Rainfall contained 2,963 provider features and created 118 new pilot states. One additional
  Department of Bangkok station appeared inside the pilot, taking coverage to 126 stations and 94
  sub-districts. This is a new identity, not a metadata version of an existing identity.
- Every feature in all three national responses had a parseable measurement; no configured null or
  numeric missing sentinel occurred. There were no corrected duplicate station/time states.

Totals after three pulls were 33 water-level states and 243 rainfall states. All placed observations
had `clock_status=valid`; none was more than five minutes in the future. All had an unreported/null
provider quality flag. That is not interpreted as good quality.

### Water level

- Latest observation advanced to `2026-10-06T02:50:00Z` on the third pull.
- Coverage: 7 Bangkok districts and 3 Nonthaburi districts.
- Originating agencies: 11 stations delivered for HII and 1 for the Royal Irrigation Department.
- All 12 identities used provider IDs.

### Rainfall

- Latest observation after the third pull: `2026-10-06T02:00:00Z`, about 65 minutes before
  retrieval. This is a 24-hour accumulation product; it remains rain context and is not proof of
  flooding.
- Coverage: 49 Bangkok districts and 3 Nonthaburi districts.
- Originating agencies: 111 stations labelled by the provider as Department of Bangkok, 11 HII and
  4 Thai Meteorological Department.
- All 126 identities used provider IDs.

### Bang Bua Thong

Neither product placed a station in district `1204` (Bang Bua Thong). The endpoint must therefore
show no local station coverage rather than infer, interpolate or apportion evidence from adjacent
Nonthaburi districts. Rainfall and water-level values must not be promoted as Bang Bua Thong values.

## Origin-sensor overlap

The current database contains Floodboard states tagged `bma_sensor` or `bma_dds`, but their
normalized state exposes road-impact fields rather than originating station codes. ThaiWater has
provider station IDs/codes. Consequently, an exact cross-provider origin join cannot currently be
proved from normalized records.

Until a reviewed mapping is available:

- ThaiWater and Floodboard are separate delivered layers;
- a BMA-tagged Floodboard state and a ThaiWater station are not counted as independent
  corroboration merely because both exist nearby; and
- no watch or confidence rule may combine them as two sensors.

## Gate assessment

Passed:

- key accepted without entering logs or Git;
- both endpoint responses below byte caps;
- recognized and strictly parsed current schema;
- immutable raw hashes and compressed objects recorded;
- pilot-only placement and source-agency lineage recorded;
- no future-clock observations;
- protected health/coverage read model reports both products as healthy.

Still required before a measurement layer:

1. collect multiple intervals to observe corrections, station-version changes, outages and cadence;
2. quantify missing sentinels and quality behavior over time;
3. confirm whether the provider's agency labels and datums are sufficient for display;
4. obtain or construct a reviewed BMA/Floodboard origin mapping;
5. define stale/current display bands separately for water level and 24-hour rainfall;
6. review retention and redistribution terms; and
7. repeat coverage checks before assuming station continuity.

Still required before any watch:

- hydrologist-approved station/datum thresholds or rate-of-rise method;
- exact target, action, expiry, labels and acceptance measures;
- event-based retrospective validation; and
- explicit confirmation that GRP remains an operator watch rather than an authoritative public
  warning issuer.
