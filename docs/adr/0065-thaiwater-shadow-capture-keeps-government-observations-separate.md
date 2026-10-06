# ADR-0065: ThaiWater shadow capture keeps government observations separate

## Status

Accepted on 5 October 2026 for Stage 0 of the multi-source early-warning proposal. The Product
Owner asked to begin implementation after confirming with HII that the website API key is public
and available for everyone.

This decision approves shadow capture only. It does not approve a GRP warning, a public layer,
incident-confidence changes, model training exports or downstream redistribution.

## Context

- Floodboard already represents road impacts and reports; GEOGLOWS represents forecast river
  discharge; Longdo represents rain/radar context; RP100 is a static scenario.
- ThaiWater aggregates observations from government agencies. The same BMA sensor can reach GRP
  through ThaiWater and Floodboard, so delivery through two systems is not automatically two
  independent observations.
- TWA map responses provide station, coordinate, source agency, source administrative fields,
  observation time/value and some provider quality/status fields, but their schemas vary by
  product.
- Before warning design, GRP needs immutable captures, source health, pilot coverage, station
  identity/versioning, quality/clock checks and overlap analysis.

Architecture proposal:
[`docs/pilot/2026-10-05_Thailand_Multi_Source_Early_Warning_Architecture_Proposal.md`](../pilot/2026-10-05_Thailand_Multi_Source_Early_Warning_Architecture_Proposal.md).

## Decision

1. **Off by default.** `THAIWATER_SHADOW_ENABLED` controls the feature. The worker reads the
   confirmed public key from `THAIWATER_API_KEY_FILE`; the value is never in Git, fixtures, URLs,
   logs or API responses.
2. **Worker-only bounded polling.** Web requests never call TWA. Initial products are the map
   endpoints for water level and 24-hour rainfall, with a configurable interval no shorter than
   five minutes, bounded timeout and 20 MB response cap.
3. **Reuse the immutable source-fetch ledger.** Every attempt records status and retrieval time.
   Successful bytes are hashed and stored before normalization. A malformed response stores no
   station or observation from that response.
4. **New canonical tables.** `hydro_station_version` stores provider/product identity, identity
   basis, coordinates, originating agency, source geography/basin, worker-derived area codes and a
   metadata version hash. `hydro_observation` stores measurement, unit/datum, observation and
   retrieval times, provider quality, clock status, raw-fetch lineage and adapter version.
5. **Pilot placement is computed by the worker.** Only stations inside captured Bangkok or
   Nonthaburi pilot outlines are normalized in this slice. Source district/sub-district labels are
   retained but not trusted as GRP codes. Point placement never creates an area average.
6. **Corrections are retained.** Repeating the same state is idempotent. A changed value or quality
   at the same station/time has a different state hash and remains explainable rather than
   overwriting history. Station metadata changes create a new station version.
7. **Clock anomalies remain data, not current evidence.** Observations more than five minutes
   ahead of retrieval are stored with `clock_status=future`. No read-side current-state use is
   approved yet.
8. **Source roles remain separate.** These records do not become Floodboard observations,
   GEOGLOWS forecasts, incidents, confidence or warnings. Rain remains context. Water level is
   evidence only of that station's measured level.
9. **No operator API/UI in Stage 0.** The first outputs are database/raw evidence for coverage,
   freshness, quality and overlap analysis. A later reviewed slice adds source-health and map
   reads.

## Consequences

- A deployment with no key or disabled switch behaves exactly as before.
- The Desktop launcher can copy `THAIWATER_API_KEY` from ignored `.env` into the local secret file,
  but Compose still leaves shadow capture off unless explicitly enabled.
- The first live run requires migration `20261005_0028`; applications still never migrate at
  startup.
- TWA schema drift, invalid coordinates, non-ISO or timezone-less observation times, negative
  rainfall and conflicting duplicate station metadata fail closed for the whole response. The
  first live run found the current v2 success envelope is `{meta, data}` rather than the older
  `{result: "OK", data}` form; both recognized forms are validated explicitly.
- Follow-up work must add controlled read models/source health, origin-sensor overlap mapping,
  research-archive export, retention terms and one scientifically reviewed deterministic watch.
