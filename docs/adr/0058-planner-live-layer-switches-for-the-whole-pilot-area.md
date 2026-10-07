# ADR-0058: the Planner's Live layer has one switch per source, for the whole pilot area

## Status

Accepted on 4 October 2026 by the Product Owner, with the recommended answers to the plan in
[`docs/pilot/2026-10-04_Planner_Live_Layer_Switches_and_River_Outlook_Plan.md`](../pilot/2026-10-04_Planner_Live_Layer_Switches_and_River_Outlook_Plan.md):

- the whole of Bangkok and Nonthaburi, not only the selected district;
- replace the district-focused live group;
- every switch off by default.

It amends ADR-0056 (steps 2 and W7b).

## Decision

1. **Routes** (`api/maps.py`, `protected`, needing a planning role):
   - `GET /api/v1/maps/live-flood/summary` returns the count for every switch and the snapshot
     time;
   - `GET /api/v1/maps/live-flood/sources/{roads|reports|facilities|cameras|outlines}` returns one
     source.
   - Both are read from stored data by `core/flood_evidence/planner_sources.py`, and both answer
     `available: false` for a Hub the pilot does not include.
2. **The Planner gets its own trimmed copy.** The pilot's own routes carry officer checks, so the
   Planner reads its own copy (D2 open):
   - no verification or officer fields;
   - no officer-confirmed access (the computed state is shown instead);
   - no Floodboard per-vehicle verdicts;
   - no report IDs, links or text.
3. **The page.** Layers panel → "Live layer (Bangkok, Nonthaburi)", with the snapshot time and
   one switch per source, each with a swatch and a count:
   - roads with flooding reported;
   - five report kinds;
   - OSM facilities and DDPM evacuation centres;
   - four camera providers;
   - district outlines.

   **All switches start off**, and ticks are remembered in the browser. A source loads when its
   switch is first ticked. Points are drawn on a canvas layer. With no district selected, the
   first roads or outlines layer brings the pilot area into view.
4. **Cards.**
   - A road in an incident opens the incident card. Its nearby cameras (within 400 m) are found
     in the browser from the loaded cameras.
   - An older or cleared road, a report, a facility and a camera each get their own card.
   - Camera pictures come through the relay for relayed providers (bmatraffic, Pak Kret).
5. The **"Live now" list** shows active incidents and facilities with flooding reported nearby.
   Everything refreshes every five minutes.

## Consequences

- At 20:30 on 4 October 2026 the switches counted:
  - 1,642 roads;
  - reports: 456 public, 230 Traffy, 29 BMA sensors, 5 Longdo/iTIC, 19 other;
  - 1,067 OSM facilities and 64 DDPM centres;
  - cameras: 520 BMA Traffic, 872 BMA flood, 21 iTIC/Longdo, 52 Pak Kret;
  - 56 districts.
- Each source is under 1 MB.
- Checked in a headless browser with real data and no sign-in (a test server serving the page
  and recorded API answers): no errors, 13 switches unticked at start, the layers draw when
  ticked, and the map fits to the pilot area. Not yet checked by a signed-in planner.
- The district-focused route `GET /api/v1/maps/live-flood` stays for the chat and summary code.
