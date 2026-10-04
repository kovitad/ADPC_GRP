# ADR-0056: live flood evidence reaches the Planner for Bangkok

## Status

Steps 1-3 accepted and built on 4 October 2026 at the Product Owner's request ("go ahead with
step 1/2/3"). The owner decided D7 (rain may appear, labelled as context) and D8 (the fixed
no-warnings wording) on 4 October 2026. Step 4 is planned in
[`docs/pilot/2026-10-04_Planner_Live_Flood_Integration_Plan.md`](../pilot/2026-10-04_Planner_Live_Flood_Integration_Plan.md).
Decision D2 (officer checks for Planners) is still open.

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
3. **Live facts in Planner answers** (step 3).
   - The router has a `live_flood` mode for questions about flooding now, reported flooding or
     early warning, for a Bangkok area. Before this, "current conditions" went to `cannot`.
   - The area is the selected Bangkok boundary, or a Bangkok district named in the message.
     Anything else gets `live_flood_unavailable` with a plain reason.
   - Facts come from the pilot's own bundle (`build_facts`) for the district, through
     `core/flood_evidence/planner_answer.py`. Officer checks, officer-confirmed access and the
     officer-check count are removed (D2). Rain stays, labelled as context (D7).
   - AI wording uses the pilot's instructions and gate (ADR-0043). If it fails the gate, the
     computed answer is shown.
   - Every answer, computed or AI, ends with the fixed D8 text. It is appended after the gate and
     never written by the model:
     - EN: "GRP does not issue flood warnings. For official warnings, follow the Thai
       Meteorological Department (TMD), the Department of Disaster Prevention and Mitigation
       (DDPM) and the Bangkok Metropolitan Administration (BMA)."
     - TH: the same in Thai (`NO_WARNINGS["th"]`). Thai questions get Thai text.
   - **Live answers are never cached**, so a repeat question always uses the newest snapshot.
   - A "Show live reported flooding on the map" button turns on the step 2 layer for the same
     district.
   - Known limit: incidents in the "check first" list keep the pilot's order, which ranks
     incidents an officer saw as dry first. The check itself is not shown.
4. **Rules for the later steps** (from the plan):
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
