# ADR-0067: Live shows ThaiWater shadow health, not measurements

## Status

Accepted on 6 October 2026 as the next read-side step after ADR-0066.

This decision does not approve station measurements, a map layer, area averages, incident evidence,
confidence changes, watches, warnings, public feeds or redistribution.

## Context

ADR-0066 provides a protected, database-only readiness contract for ThaiWater shadow capture. The
contract has now been exercised against three controlled pulls, but its health and coverage can
only be inspected through an API or CLI. A Hub Admin using Live needs to see whether the shadow
capture exists and what its pilot coverage is without mistaking the source for flood evidence.

The short observation window, absent provider quality flags, incomplete water-level coverage,
unknown Floodboard/BMA origin overlap and unresolved licence/retention questions still block a
measurement display.

## Decision

1. Add one row to Live's existing **What this view is built from** table. Label it **ThaiWater
   government observations (shadow)** rather than adding a map layer or headline card.
2. Read `/api/v1/pilot/flood/{pilot_id}/government-observations/status` alongside the existing
   stored Live data. The browser never calls ThaiWater.
3. Show only overall capture state and, for each product, station count, count of covered pilot
   districts and age of the last stored successful pull.
4. Always state that the information is pilot-wide health/coverage only, contains no measurement
   values or district averages, has no incident-confidence or warning effect, and is not approved
   for publication.
5. Keep the Live page usable if this optional status request fails. Replays do not borrow current
   ThaiWater status.
6. Provide equivalent English and Thai labels and preserve the existing pilot membership rules.

## Consequences

- Hub users can tell the difference between capture being disabled, missing credentials, waiting,
  healthy, degraded and offline without reading logs or exposing secrets.
- Station and district counts describe coverage, not conditions. A count of zero never means no
  rain or no flooding.
- No additional API, database, worker or provider request is introduced.
- A separate approved ADR is still required for station measurements or a Government observations
  map layer after freshness, quality, datum, origin mapping, licence and retention gates pass.
