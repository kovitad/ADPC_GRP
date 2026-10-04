# ADR-0056: live flood evidence reaches the Planner for Bangkok

## Status

Step 1 accepted and built on 4 October 2026 at the Product Owner's request ("go ahead with step
1"). Steps 2-4 are planned in
[`docs/pilot/2026-10-04_Planner_Live_Flood_Integration_Plan.md`](../pilot/2026-10-04_Planner_Live_Flood_Integration_Plan.md).
They will amend this record once decisions D2, D7 and D8 are made.

## Context

- The Planner works on GRP boundaries: districts such as `1030` and sub-districts such as
  `103005`. The flood pilot uses the same district codes.
- Incidents carried no district. The research archive approximated districts from each incident's
  box. The feed plan would have computed them per request, which is spatial work in a web request.

## Decision

1. **District codes are computed once, in the worker.**
   - `update_incidents` stores `district_codes` in each incident's summary. These are every demo
     district that any vertex of the incident's roads falls in, checked box-first
     (`geo.district_codes`).
   - The Planner filter, the feed and the archive read them. None of them computes geometry in a
     request.
   - Incidents processed before this change get codes at their next snapshot. Until then the
     archive marks its box approximation with `district_codes_basis: box_approx`.
2. **Rules for the later steps** (from the plan):
   - live data never enters a stored assessment or its receipt;
   - the map layer is "Reported flooding on roads (live, not a flood map)";
   - a sub-district shows its parent district's live facts, and says so;
   - answers never issue warnings;
   - a cached Planner answer that includes live facts is keyed by the incident run's
     `snapshot_at`.

## Consequences

- Each roads snapshot does one more box-first vertex check per incident, which is small next to
  grouping (0.8 s for 44 incidents across the city).
- An incident that crosses a district border appears in both districts' counts. District sums
  can therefore exceed the city total, and reports must say so.
