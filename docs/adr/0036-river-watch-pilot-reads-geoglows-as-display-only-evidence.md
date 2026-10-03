# ADR-0036: River Watch pilot reads GEOGLOWS as display-only forecast evidence

## Status

Accepted on 2 October 2026 for a local pilot. The Product Owner asked for "pilot tab for me to do
the forecast feature using live feed from geoglow", in plain language that someone without
hydrology training can follow. They chose:

- to show **both** exploratory reaches, labelled as not confirmed;
- to show the tab to **Hub Admins and Platform Admins only**.

Plans: [`docs/pilot/2026-10-02_Bang_Bua_Thong_GEOGLOWS_River_Watch_Plan.md`](../pilot/2026-10-02_Bang_Bua_Thong_GEOGLOWS_River_Watch_Plan.md)
(version 2.1, Phase A). Phase B, the HAND depth experiment, is planned separately in
[`docs/pilot/2026-10-02_Pilot_Tab_Phase_B_HAND_Plan.md`](../pilot/2026-10-02_Pilot_Tab_Phase_B_HAND_Plan.md)
and is not covered by this ADR.

## Context

- GEOGLOWS publishes a free, public, daily river-discharge forecast per modelled reach.
  `forecaststats` returns parallel arrays.
- Live checks on 2 October 2026:
  - the median and percentile series are blank at most hourly steps and three-hourly elsewhere;
  - `/dates` answers CSV, not the JSON its documentation describes;
  - `metadata.gen_date` is the retrieval time, not the forecast run;
  - `returnperiods` fails upstream ("No variable named 'logpearson3'"), so GEOGLOWS currently
    offers no "is this high?" threshold.
- No hydrologist has confirmed a reach for Bang Bua Thong. The two candidates came from a
  nearest-river lookup.
- Global Risk may auto-approve contributions, and its `generic_json` feed expects a list of record
  objects.

## Decision

1. **A new Pilot page.** `/pilot.html` is shown in the top bar to Hub Admins and Platform Admins.
   Its four routes under `/api/v1/pilot/river-watch` are `protected` and use `AdminUser`:
   - `reaches`;
   - `{reach_id}`, the card;
   - `{reach_id}/feed-preview`;
   - `{reach_id}/raw/{run}`, the exact upstream bytes GRP holds.
2. **An allow-list of reaches.** Only `430537201` and `430392813` can be asked for. Both are
   labelled "exploratory, not confirmed" and given no river name. Any other reach returns 404
   before anything is fetched.
3. **Pure checking and summary in `core/river_watch.py`.**
   - A blank value is missing, never zero, and a median is never filled from `high_res`.
   - The forecast is refused on misaligned arrays, non-increasing or non-UTC times, a negative or
     non-numeric flow, a wrong reach, missing units, or P25 > median > P75.
   - The window is `[now, now + 7 days)`.
   - The peak is the highest median, earliest on a tie, with P25/P75 at that time.
   - The trend is rise, steady (within 5% of the first value) or fall.
   - The card and the feed preview use the **same summary object**.
4. **Three times kept apart.**
   - The run is pinned with `date=`, and `issued_at` comes from the run.
   - Freshness compares the run with the newest run due by now, at 14:00 UTC each day.
   - A morning query on the previous day's run is "latest".
   - A cached run shown because GEOGLOWS failed is "older", never new.
5. **Fetch and cache in the API process.** `httpx` with a 30-second timeout and one retry. One
   fetch per (reach, run), and the run list re-checked every 30 minutes. The raw bytes are kept
   with the cached forecast and can be downloaded. Their SHA-256, the request URL and the timing
   are shown under "For specialists". If the newest listed run fails and nothing is held, as
   after a restart, the previous listed run is used and marked older. This is an HTTP read, not
   GIS work, so it does not go to the worker.
6. **Plain language.**
   - The headline is a sentence.
   - The unit is spelled out and compared with Olympic pools or bathtubs.
   - The band is "where most forecasts fall".
   - Times are in Bangkok time.
   - The chart's y-axis starts at zero, and the x-axis is real time.
   - A fixed "What this is not" box and a "What to check next" list are shown.
   - No threshold, warning, water level, inundation or RP100 link appears.
7. **The feed is a preview only.** The card response carries its own preview, built from the
   same summary, so the page's preview and the card cannot drift apart. The preview shows `records: [summary]` with
   `as_of_field: issued_at_utc` and `sent_to_global_risk: false`. A public endpoint or a Global
   Risk registration needs:
   - a confirmed reach;
   - a settled licence (CC BY-NC-SA 4.0 or CC BY 4.0);
   - Global Risk's answer on time and location handling;
   - a new ADR.

## Options considered

- **Point Global Risk's `generic_json` at GEOGLOWS directly.** Rejected: GEOGLOWS returns arrays,
  not record objects, and nothing would check freshness or the reach.
- **Use GEOGLOWS return periods as "high" lines.** Rejected for now: the route is broken, and no
  local agreement exists that they mean anything for this reach.
- **Let the browser call GEOGLOWS.** Rejected: there would be no shared cache, no check, and no
  single summary for the page and the feed.
- **A charting library from a CDN.** Rejected: external browser calls are already listed as debt.

## Consequences

- An Admin can see a live seven-day signal and its provenance in seconds. Nothing leaves GRP.
- The cache is per process, like the other in-memory stores; a restart refetches.
- A confirmed reach, a reviewed threshold and a public feed are explicit later decisions.

## Action items

- [x] `core/river_watch.py`, `api/river_watch.py`, `web/pilot.*`, offline tests on a captured
      snapshot, permission matrix entries
- [ ] Hydrologist confirms one reach; remove the other
- [ ] Settle the GEOGLOWS licence for the derived summary
- [ ] Ask Global Risk how a feed's run time, valid time and reach scope are handled

## Amendment, 2 October 2026: a river map and plain names

The owner, as a non-specialist, could not tell which river the pilot showed. They asked: "can you
add the river map? and name then? … or canal name near by … show osm and highlight the river
canal near by".

- **The model line.** Each allow-listed reach's GEOGLOWS v2 stream line was captured once from the
  GEOGLOWS layer on Esri Living Atlas, with `comid` equal to the reach ID. It is stored with its
  stream order, upstream area and length in `core/data/river_watch_reaches.json`. The terms of
  that Esri service still need to be confirmed. The same lines are published as GEOGLOWS open
  data, and can be re-derived from there.
- **Nearby named waterways.** These were found with OpenStreetMap Nominatim reverse lookups along
  each line and fetched by way ID. Overpass was unavailable on the day. OpenStreetMap data is ODbL
  and credited on the page.
- **The page** draws the orange model line over OpenStreetMap tiles, the named canals nearby in
  blue with labels, and the original search point. It adds a plain size line: big, medium or
  small, with the drained area.
- **A labelled best guess.** Reach `430537201` is described as "Big river near Nonthaburi:
  probably the Chao Phraya (not confirmed)". The reasons:
  - its line sits on the wide river at Nonthaburi on the map;
  - its upstream area is about 148,000 km², and its mean flow about 8,100 m³/s.

  Reach `430392813` is "Small canal near Bang Bua Thong town". It drains about 147 km² over
  10.6 km, near Khlong Ban Kluai, Khlong Lam Ri and Khlong Lak Khon.
- **This relaxes, for display only,** the original rule that neither reach is given a river name.
  Every name stays visibly "probably" or "nearby" and "not confirmed". The feed preview and its
  `scope_note` are unchanged, and the hydrologist's choice of reach is still required.

## Amendment, 2 October 2026: Bangkok, by district

The owner asked to "do for all bangkok districk just pick and each district same is flood
assessment".

- **Capture.** `python -m grpcli.river_watch_capture --province Bangkok --out …` runs once in
  the API container. It reads only Bangkok's rectangle of GEOGLOWS's open
  `hydrography/vpu=407/streams_407.gpkg` over HTTP (about 2 minutes) and matches the segments to
  the 50 supported Bangkok district polygons. It also names the nearest OpenStreetMap waterway for
  each main river, using Nominatim at one request per second. The result is written to
  `core/data/river_watch_bangkok.json` (about 460 KB, 58 segments). It is not in the database and
  is not fetched live. The web request does no GIS work. If the pilot covers all of Thailand,
  these lines belong in the data library instead.
- **Rules.**
  - A district's main river is the segment that drains the most land inside it.
  - Inside Bangkok, a segment draining at least 100,000 km² is labelled "probably the Chao
    Phraya (not confirmed)".
  - A district whose main river drains under 1,000 km², or that has no segment, is "inland". The
    page then says plainly that a forecast there says little, because Bangkok's flat, pumped and
    gated canals are not in the model.
- **Result.** 17 districts lie on the Chao Phraya, 11 have only small streams, and 22 have no
  model river.
- **Routes.** `GET /api/v1/pilot/river-watch/districts` and `/districts/{admin_code}` are
  `protected` and `AdminUser`. The forecast allow-list now covers the pilot's two reaches plus the
  captured Bangkok segments. Any other ID returns 404 before anything is fetched.
- **Page.** A "Bangkok, by district" mode shows:
  - a Thai or English district list, with riverside districts marked;
  - the district outline and all its model rivers on the map, the main one in orange, with a tap
    choosing another;
  - the river named above the forecast headline.

  The forecast still updates itself when someone looks, cached per river and run.
