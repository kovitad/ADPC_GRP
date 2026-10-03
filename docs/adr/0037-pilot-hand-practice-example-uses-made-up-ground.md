# ADR-0037: The Pilot HAND practice example uses made-up ground and a chosen water height

## Status

Accepted on 2 October 2026. The Product Owner asked to "build the practice demo slider too". This
is step B1 of [`docs/pilot/2026-10-02_Pilot_Tab_Phase_B_HAND_Plan.md`](../pilot/2026-10-02_Pilot_Tab_Phase_B_HAND_Plan.md).

## Context

Version 2.1 of the owner's pilot plan adds a HAND flood-depth experiment. Real Q-derived depth is
blocked on:
- a reviewed reach;
- suitable terrain;
- a Q-to-H curve on a common vertical reference;
- a hydraulic reviewer;
- validation evidence.

The plan allows a synthetic method demonstration first, labelled so that it cannot be mistaken
for Bang Bua Thong.

## Decision

1. **One depth rule in `core/hand_depth.py`.** `depth = max(H - HAND, 0)` inside the supported
   area.
   - Equal values are the water's edge, with zero depth, and are not counted as wet.
   - A higher cell is dry with depth 0.
   - Missing, non-finite or negative HAND, or a cell outside the area, is unknown, never dry.
   - A negative or non-finite H is refused.
   - The pure-Python cell rule serves the demo. A lazily imported NumPy `depth_block` serves later
     raster windows. Tests prove the two agree and that the result does not depend on block size.
2. **A fixed practice grid.** It is 12 × 20, made up:
   - a channel and a side channel;
   - rising banks and a higher mound;
   - a patch with missing heights;
   - a corner outside the area.

   The H = 3 m worked example from the plan is computed by the same rule.
3. **A new route.** `GET /api/v1/pilot/hand-demo?stage_m=` (`protected`, `AdminUser`, like the
   rest of the Pilot tab).
   - It accepts 0 to 5 m and returns 422 otherwise.
   - The arithmetic is tiny pure Python, so it runs in the request with no GIS and no NumPy.
   - Nothing is stored or sent.
4. **The person chooses H with a slider.** It is never set from the forecast, a rating curve or
   an LLM.
5. **The page** shows:
   - a dashed, separately framed section with "Practice example · made-up ground · not Bang Bua
     Thong";
   - a plain-language answer and a colour grid with counts;
   - a side view, and the worked rule;
   - a "Why there is no real Bang Bua Thong map yet" box.

## Options considered

- **Compute in the browser.** Rejected: there would be a second copy of the rule that tests do
  not cover.
- **Use real open terrain now.** Rejected for B1:
  - the key-free Copernicus GLO-30 is a surface model, which is poor in towns;
  - a HAND tool is not installed;
  - without a Q-to-H curve it still cannot use the forecast.

## Consequences

- An Admin can see how stage, ground height, the water's edge and unknown cells interact before
  any real data exists.
- Step B2, the synthetic GeoTIFF pipeline in the worker, reuses `depth_block`.
- A real scenario still needs every prerequisite above. This ADR does not authorise it.

## Action items

- [x] Rule, practice grid, route, page section, tests, permission-matrix entry
- [ ] B2 synthetic raster pipeline in the worker
- [ ] B3 readiness panel
