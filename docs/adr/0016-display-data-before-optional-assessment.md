# ADR-0016: Display available data before optional assessment

**Status:** Accepted by the Product Owner for MVP 1  
**Date:** 22 September 2026

## Context

The Planning map loaded the Thailand baseline but hid current flood, district and evacuation-centre
layers until the person enabled them or completed an assessment. District and SIG panels also led
with messages about assessment availability and safety. This did not match the MVP 1 requirement:
the first outcome is to let a person see the available data.

## Decision

1. Show the available district boundaries, RP100 flood layer and evacuation-centre locations when
   Planning opens. Their visibility does not depend on an assessment.
2. Selecting or locating a district focuses the map and keeps the available layers visible. The UI
   must not ask the person to run an assessment before showing them.
3. Lead SIG summaries with returned hazard, exposure, risk and population information. Keep source,
   recipe and receipt context, but do not lead with “safe/not safe” or assessment-availability text.
4. Keep the queued GRP assessment as an optional explicit action. Only show its classification
   legend and result language after a person explicitly requests an assessment.
5. Continue prohibiting invented values and safety claims internally; this control does not need to
   dominate the normal data-browsing interface.

## Consequences

- The initial map is useful without AI, SIG or a worker job.
- Assessment readiness cannot make an otherwise available source layer disappear.
- “Show” and “assess” are separate actions: display preserves source data, while assessment creates
  a version-pinned derived result.

## Verification

- Frontend contract tests assert that flood, district and centre layers default on.
- Chat tests assert display-first SIG and deterministic-summary wording.
- Existing assessment and golden-result tests continue to cover the optional derived workflow.
