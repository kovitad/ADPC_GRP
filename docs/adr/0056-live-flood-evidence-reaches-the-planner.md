# ADR-0056: live flood evidence reaches the Planner for Bangkok

## Status

Steps 1 and 2 accepted and built on 4 October 2026 at the Product Owner's request ("go ahead
with step 1", "go ahead with step 2"). Steps 3 and 4 are planned in
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
2. **The live layer on the Planner map** (step 2).
   - `GET /api/v1/maps/live-flood?boundary_id=&hub_code=` is `protected` and needs a planning
     role (`planner_membership`). It reads `core/flood_evidence/planner_layer.py`.
   - It returns the stored open incidents whose `district_codes` include the area's district,
     their roads from the latest snapshot, the snapshot time, a note and the Floodboard credit.
   - It does no spatial work.
   - It answers `available: false` with a plain reason outside Bangkok, for a Hub the pilot does
     not include, or for a district outside the demo area.
   - A sub-district rolls up to its district (`rolled_up_from`). Officer checks and verification
     fields are never returned (D2 is open).
   - On the page, the switch "Reported flooding on roads (live, not a flood map)" appears only
     for Bangkok areas. Roads are coloured by confidence word, receding ones are dashed, and the
     legend is separate from the flood scenario. It refreshes every five minutes while on.
3. **Rules for the later steps** (from the plan):
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
