# ADR-0062: the Planner map uses the GRP map icon system

## Status

Accepted on 5 October 2026. It implements
[`docs/enhancement/GRP_Map_Icon_UX_Pack_v1.0/GRP_Map_Icon_UX_Revamp_Spec.md`](../enhancement/GRP_Map_Icon_UX_Pack_v1.0/GRP_Map_Icon_UX_Revamp_Spec.md)
on the Planner map. It amends ADR-0058 (legend rows) and ADR-0060 (markers and selection).

## Decision

1. **Three visual channels.** The pack's 17 SVGs are copied to `web/assets/map-icons/` and loaded
   as images, so their filter IDs never clash.
   - **Shape is the feature type:**
     - reports, sensors, agency reports and news;
     - schools, hospitals or clinics (by record type);
     - evacuation centres and villages;
     - traffic and flood cameras;
     - roads and outlines, which stay lines.
   - **Colour is the source**, as in the pack.
   - **A ring and badge are the assessment status**, on the centres' own symbol:
     - potentially exposed: a solid red ring;
     - not exposed under the selected scenario: a solid green ring;
     - no data: a dashed grey ring.

     They read in grayscale, and status never replaces the feature icon.
2. **Markers:**
   - pins are 34 × 40 px;
   - every marker is keyboard-focusable, with `role=button` and an `aria-label`;
   - the tooltip shows type, name, source, time and status, on hover and on focus;
   - the selected marker grows by a quarter, with a blue halo;
   - news and cleared reports are muted ("Not counted in assessment");
   - facilities with flooding reported nearby keep their orange halo, which is live context and
     not an assessment status;
   - cameras with a live picture keep their green dot.
3. **Clustering.** One `leaflet.markercluster` group (1.5.3, from unpkg like Leaflet) holds every
   live point layer.
   - A cluster shows its count and its dominant symbol, when one symbol is at least 75 % of its
     points; otherwise it shows a neutral stacked symbol.
   - Clustering stops at zoom 17, and points on one spot spread out (spiderfy).
   - Each switch still adds and removes only its own points.
4. **Legend rows**, under four group headings: Flood observations, Facilities and communities,
   Cameras, and Boundaries.
   - Each row has a checkbox, the map's own symbol (or a line sample for roads and outlines), a
     short name with the source below, the count, and an "i" button.
   - The "i" button opens source, date and limits in Details.
   - The Assessment section's status legend uses the same symbols and rings.
5. **Unchanged:** layer toggles, counts, data loading, cards, the pick list, the dock, and every
   analytical result and classification.

## Wording kept from earlier owner decisions

- **"N/A — no data", not "Unable to assess".** The owner asked on 25 September 2026 for N/A
  instead, and `tests/fast/test_auth_entry.py` enforces it. The pack's symbol (dashed ring,
  question badge) is used with that label.
- **Popups still say "Lower mapped flood exposure"** for `not_exposed_under_scenario`. The legend
  uses the pack's "Not exposed under the selected scenario". Neither says "safe".

## Consequences

- **Checked in the headless browser** with recorded live data:
  - 13 legend rows in four groups;
  - at city zoom, mixed and dominant clusters with counts;
  - at street zoom, single pins;
  - clicking a pin selects it (halo) and opens Details;
  - the focused marker's accessible name reads, for example, "Hospital · … · OpenStreetMap · no
    flooding reported nearby".
- **Not yet done:**
  - the Bangkok flood pilot page (`web/flood.js`) still uses its own markers;
  - volunteer centres and early-warning resources have no symbol in the pack, so they stay dots;
  - a satellite basemap check, because the Planner has no satellite layer.
- **Not yet checked** by a signed-in planner.
