# ADR-0060: one map dock replaces the Planner's floating cards

## Status

Accepted on 4 October 2026 by the Product Owner, with the recommended answers to
[`docs/pilot/2026-10-04_Planner_Map_Panels_UX_Design.md`](../pilot/2026-10-04_Planner_Map_Panels_UX_Design.md):

- the dock sits on the right;
- points on top of each other get a pick list;
- the district profile opens in the dock.

It amends ADR-0058 (cards) and ADR-0056 (W7b, phone sheet).

## Context

With the Live layer on, cards floated over the points they described, piled on each other and
on the district popup, and the Layers panel could not fold. Two click bugs had the same root:
- live points on a second canvas were covered by the centres' canvas;
- the selected district's filled shape covered any canvas.

## Decision

1. **One dock** (`[data-dock]`) on the right of the map, with three tabs on a rail: Layers,
   Details and Run.
   - Clicking the active tab, `»` or Esc folds it.
   - The browser remembers whether Layers was left open.
   - The old "Data & run" and "Layers" buttons are gone; `data-layers-toggle` and
     `data-run-toggle` now sit on the rail tabs.
   - On phones (600 px or narrower), the rail sits under the search box and the panel becomes a
     bottom sheet. This replaces the separate live sheet.
2. **Details** (`showDetails`) holds one card at a time:
   - the chosen point gets a blue ring;
   - the map moves only if the point would sit under the dock;
   - Esc, `»` or a click on empty map closes it;
   - a new card replaces the old one, and camera pictures stop when their card closes.
3. **`bindDetails(layer, item)`** replaces every Leaflet popup in `planning.js`: live roads,
   reports, facilities and cameras, evacuation centres and supporting points.
   - A click that touches more than one point within 12 px shows a pick list ("4 here:
     4 cameras").
   - Choosing a row opens its card, with "Back to 4 here".
4. **The district profile** opens in Details. Clicking the selected district again closes an
   open card, or shows the profile. The profile's text values are now escaped, and the HTML is
   parsed with `DOMParser` (no `innerHTML`).
5. **Points above shapes:**
   - live points are SVG in `grpLiveFlood` (z 430);
   - centres and supporting points are SVG in a new `grpPoints` pane (z 420);
   - SVG passes clicks on empty space through to the district shape below.
6. **Layers** fold into four sections that remember their state: base map and boundaries,
   assessment, Live layer, and Global Risk and vulnerability.
   - A legend shows only while its layer is on.
   - "Live now" becomes a button that opens the list in Details.
7. **Place messages** become a toast at the bottom of the map. It can be closed and hides after
   eight seconds. Hover shows a name only, and never on touch screens.

## Consequences

- Checked in the headless harness with recorded real data:
  - a single camera under a district shape opens its card;
  - four stacked cameras show a pick list, and Back works;
  - an empty click and Esc close the card;
  - Layers sections fold;
  - phone width shows the rail and the bottom sheet.
- Not yet checked by a signed-in planner. The district profile path and the Run tab were not
  exercised in the harness.
- Drawing the live points as SVG costs more than canvas when every switch is on (about 3,000
  points).
