# ADR-0012: Open the pinned assessment map when a result completes

**Status:** Accepted for local Docker Desktop validation  
**Date:** 20 September 2026

## Context

The general Planning map correctly requires the person to opt into a flood preview. After the person explicitly runs an assessment, however, leaving flood depth unchecked makes the completed result appear disconnected from its map. The map must show the exact hazard version and all evacuation centres used by that assessment, not whichever preview version happens to be current.

The blue flood palette also competed with SERVIR navigation colours and did not read clearly as hazard depth. A red sequential palette is requested, but red must not be described as vulnerability-weighted risk or as an evacuation decision class.

## Decision

1. A successful assessment result returns display metadata for its pinned hazard version: version ID, return period, stored image URL, bounds and palette.
2. When that result opens, Planning explicitly checks **Flood depth** and **Evacuation centers**, loads the pinned flood picture, draws every assessed centre and fits the selected supported boundary.
3. Centre points come only from `assessment_feature` rows for that immutable result. The browser fetches all pages, up to 1,000 rows per request, rather than drawing the national source layer.
4. The same behavior applies to any supported boundary level, including a future sub-district, because scope comes from the assessment's pinned boundary and worker result.
5. Flood depth uses a light-to-dark sequential red palette. Grey remains NoData; zero depth remains transparent.
6. Red means **greater flood depth only**. It is not a risk class, safety decision, vulnerability score or current-flood report.
7. Existing immutable hazard inputs are not changed. Display products use a new generated key/version and declare `palette=red_depth_v1`.

## Consequences

- Running an assessment is the explicit action that opens its result layers; ordinary map browsing remains checkbox-controlled under ADR-0011.
- Historical results continue to request their pinned hazard version rather than silently switching to a newer scenario.
- The persistent local RP100 baseline needs a new immutable import version to receive the red display PNG. The prior blue display product remains retained for traceability.
- Real district/sub-district assessments remain blocked until scientific readiness gates are satisfied; the current runnable case is synthetic.
