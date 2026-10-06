# ADR-0066: Government-observation readiness is a protected health contract

## Status

Accepted on 5 October 2026 as the next read-side slice after ThaiWater Stage 0 shadow storage.

This decision does not approve measurement display, a map layer, warning logic, incident-confidence
changes, model training, a public feed or redistribution.

## Context

ADR-0065 deliberately withheld an operator API until ThaiWater captures could be assessed. A live
capture still requires a privately configured key, but the assessment needs a stable way to inspect
capture readiness, fetch outcomes, lineage, pilot coverage, source agencies, quality reporting and
clock anomalies without querying the provider or exposing measurements.

Reading tables ad hoc would make acceptance checks inconsistent. Treating the stored water level or
rain as an incident would collapse distinct evidence roles before sensor-origin overlap and
scientific thresholds have been reviewed.

## Decision

1. Add the protected endpoint
   `/api/v1/pilot/flood/{pilot_id}/government-observations/status` for authorized pilot members and
   Platform Admins through the existing `FloodPilot` access dependency.
2. The endpoint reads stored database rows only. It never calls ThaiWater, starts a capture or
   performs spatial processing.
3. Return one status for each approved shadow product: water level and 24-hour rainfall. Status
   includes the latest attempt/success, outcome, raw SHA-256 lineage, provider feature count,
   immutable observation-state count, clock/quality counts and latest observation/retrieval times.
4. Coverage is based on each provider station identity's latest stored metadata version. Return
   station counts by worker-derived district/sub-district, originating agency and identity basis.
   Do not return measurement values or calculate area averages.
5. Distinguish capture disabled, credential file missing, awaiting first fetch, healthy, degraded
   and offline states. Credential status is a boolean only; key content, paths and request headers
   are never returned.
6. The response always states `publication_approved=false`. Government observations remain shadow
   evidence and separate from Floodboard impacts, GEOGLOWS forecasts, Longdo rain context,
   incidents, confidence and warnings.
7. Replay requests report `not_available_in_replay` and never substitute current live observations.

## Consequences

- Operators and developers gain one bounded acceptance contract for a controlled live run without
  prematurely publishing ThaiWater data.
- A deployment with capture disabled can report that explicit state while preserving all prior UI
  behavior.
- The contract may report multiple immutable states for a corrected station/time; it labels these
  as stored observation states rather than pretending they are independent measurements.
- A separate reviewed decision is still required before returning station measurements or adding a
  **Government observations** map layer.
- Live-data acceptance remains blocked until the key is placed in ignored configuration and the
  controlled capture report is reviewed for schema, coverage, freshness, quality and sensor-origin
  overlap.
