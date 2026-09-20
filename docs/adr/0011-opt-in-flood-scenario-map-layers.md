# ADR-0011: Make flood map scenarios explicit and opt-in

**Status:** Accepted for local Docker Desktop validation  
**Date:** 20 September 2026

## Context

The Planning map previously chose the first flood layer and could add it programmatically when an area was selected. That made layer state hard to understand and did not show the planned RP20 and RP50 scenarios. Only RP100 has delivered source data today; inventing RP20 or RP50 pictures would violate the scientific guardrails.

The shared navigation also used large non-wrapping tabs. On narrower screens, authorized Admin items could be outside the visible area with no clear indication that the row scrolled.

## Decision

1. Flood depth is never drawn automatically. The person must check **Flood depth**.
2. A separate scenario selector lists RP20, RP50 and RP100.
3. A scenario is enabled only when a managed map layer exists for that exact return period. RP20 and RP50 are visible but disabled and labelled **not imported** until accepted source versions exist.
4. Changing scenario replaces the display overlay; only one flood-depth return period is drawn at once.
5. Selecting a district may show its boundary and evacuation centres, but must not silently enable flood depth.
6. The map-layers API returns explicit `flood_scenarios` availability in addition to immutable layer records.
7. Shared navigation tabs use smaller spacing and type. At 900 px and below, the authorized menu wraps onto visible rows rather than hiding items in an unmarked horizontal overflow area.

## Consequences

- The map starts without a flood picture, matching explicit user control. Evacuation-centre preview points may remain visible.
- RP20 and RP50 configuration is present without pretending data exists.
- Adding a future RP20 or RP50 managed version enables its option without frontend code changes.
- At small widths the sticky header can become taller, but every authorized destination remains visible and keyboard accessible.
