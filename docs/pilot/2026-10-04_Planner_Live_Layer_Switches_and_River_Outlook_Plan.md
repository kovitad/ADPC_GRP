# Planner: a "Live layer" with per-source switches, and GEOGLOWS in the district summary

Status: decided 4 October 2026 (whole area, replace the old group, GEOGLOWS shown labelled exploratory). A is built (ADR-0058); B follows. Two owner requests from the same session:

- **A.** "Integrate the layer from this one [the pilot page's per-source switches] for Bangkok in
  the Planner map; maybe add a layer called Live layer with these tick boxes; off by default, but
  when ticked I can see where the roads flood, camera points, schools and hospitals."
- **B.** "Where is the GEOGLOWS data for the district in the summary report?" It is not there
  today.

## A. Live layer with per-source switches

### What the pilot page already has

The pilot page (`web/flood.js`) shows each source as its own switch, with a count: Floodboard
road colours; reports by source (Traffy, public, BMA sensors, Longdo/iTIC, news); OSM
facilities; cameras by provider (BMA Traffic, BMA flood cameras, iTIC/Longdo, other); and
district outlines. The data comes from the pilot's protected routes (`/roads`, `/reports`,
`/assets`, `/cameras`, `/areas`), which Planner users in the pilot Hub can already open.

### Proposed Planner design

One group in the Layers panel, replacing today's live group, **all switches off by default**:

```text
LIVE LAYER (Bangkok, Nonthaburi)                     as of 20:10
[ ] Roads with flooding reported (Floodboard)            1,500
[ ] Reports: Traffy Fondue                                 227
[ ] Reports: public, via Floodboard                        340
[ ] Reports: BMA sensors                                    29
[ ] Reports: Longdo and iTIC                                 4
[ ] Reports: news and clusters (not counted as evidence)    16
[ ] Schools, hospitals and clinics (OSM)                 1,131
[ ] DDPM evacuation centres                                 64
[ ] Cameras: BMA Traffic                                   520
[ ] Cameras: BMA flood cameras (via BMA's relay)           872
[ ] Cameras: iTIC and Longdo                                21
[ ] Cameras: Pak Kret municipality                          52
[ ] District outlines                                       56
Legend ▾      Live now ▾
```

- **Scope: the whole pilot area** (Bangkok and Nonthaburi), so it works without selecting a
  district, as the pilot page does. When a district is selected, the map still fits to it.
- **Cards.**
  - Clicking a flooded road opens its incident card (confidence and reasons, depth, reports,
    nearby facilities and cameras), as built in W7b.
  - Facilities and cameras open their cards: distance, access "not confirmed", and live pictures
    where GRP can show them.
- **Performance.** Cameras and reports are drawn on a canvas layer (about 1,500 points), so the
  map stays fast. Each source loads only when its switch is first ticked.
- **Remembered.** Ticks are remembered in the browser, and start off for a new user.
- **Rules kept:**
  - not a flood map, not a warning;
  - never part of an assessment;
  - "reported nearby", never "flooded";
  - no officer checks;
  - credits shown.
- **What replaces what.** Today's live group (one main switch plus two sub-switches, scoped to
  the selected district) becomes this per-source group. The incident, facility and camera cards
  and the "Live now" list stay.

### Steps

1. Planner page: the group, a lazy loader per source, a canvas renderer, counts, remembered
   ticks.
2. Reuse the pilot routes for data. No new API is needed, except that the Planner layer response
   gains the DDPM count.
3. Check in the browser harness (no sign-in) and at desktop and phone widths, then commit.

## B. GEOGLOWS river outlook in the district summary

### What exists

- **River Watch** (ADR-0036) gives each Bangkok district a **main river reach**, chosen by a rule
  ("the segment that drains the most land inside the district"), **not confirmed by a
  hydrologist**. Small inland waterways are flagged.
- Bang Bua Thong has two exploratory reaches. Other Nonthaburi districts have none yet.
- The 7-day forecast (trend, median peak and band, run time) is fetched from GEOGLOWS and
  cached by the API.
- **Only Hub Admins and Platform Admins can see River Watch today.**

### Proposed summary section

"7. River outlook (GEOGLOWS, exploratory)", after the live section, for districts that have a
reach:

- the reach and why it was chosen ("main river by drainage area; not confirmed by a
  hydrologist");
- the 7-day trend in words (rising, steady or falling), the median peak with its "where most
  forecasts fall" band, and the time of the forecast run;
- a small chart picture of the 7-day flow;
- fixed caveats: "river flow, not street flooding"; "no 'high' threshold exists"; "not a
  warning";
- for an inland district with only a small waterway, one line saying so instead of a forecast;
- the same in Thai for the Thai download.

### Decision needed

Planners would see River Watch content for the first time. ADR-0036 limits it to admins, and
decision D7 recommended waiting for hydrologist-confirmed reaches (D3). Options:

1. **Show it now, clearly labelled "exploratory, not confirmed"** (the summary keeps the caveats).
2. **Wait until reaches are confirmed** (D3).

## Questions for the owner

1. **A, scope:** the whole pilot area (recommended), or only the selected district?
2. **A, replace today's live group** with the per-source group (recommended), or keep both?
3. **B:** show GEOGLOWS in planners' summaries now, labelled exploratory, or wait for confirmed
   reaches?
