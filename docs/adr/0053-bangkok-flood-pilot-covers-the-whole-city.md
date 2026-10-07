# ADR-0053: the Bangkok flood pilot covers the whole city

## Status

Accepted on 4 October 2026 by the Product Owner ("I also want to do whole Bangkok now"). It
widens the demo area set on 3 October 2026 (ADR-0040, ADR-0041). It is still a Gate A local demo.

## Context

- The demo area was four districts: Bang Sue, Chatuchak, Bang Kapi and Lat Krabang.
- The Floodboard roads export already covers all of Bangkok (5,571 segments in the capture of
  `20261003T233446Z`), and the camera registry already holds 1,413 cameras city-wide.
- The owner wants one live feed for the whole city, to share through Global Risk
  (`docs/pilot/2026-10-03_Global_Risk_Live_Feed_Plan.md`).

Measured on that capture, offline:

| Step | Four districts | 50 districts |
| --- | --- | --- |
| Incident grouping | 10 incidents, 0.22 s | 44 incidents, 0.8 s |
| Facility exposure | 94 facilities | 1,067 facilities, 0.97 s |

## Decision

- `demo_corridor.areas` in `core/data/flood_pilot_bangkok.json` lists all 50 district codes.
  The page, incidents, answers and changes use it as before; nothing else is renamed.
- OSM facilities were captured again for the 50 districts on 4 October 2026: 707 schools, 183
  hospitals and 177 clinics (ODbL, labelled as OSM).
- **Rain stays narrow to keep cost flat.** A new `rain_areas` list keeps district rain on the
  first four districts. The busiest active incidents anywhere in the city still get their own
  rain record (`TOP_INCIDENTS`), so Longdo Weather calls stay about the same.

## Consequences

- About 1 s more worker time for each roads snapshot. No web request does more work.
- Facility exposure rows grow from about 94 to 1,067 per snapshot. With snapshots about every
  20 minutes and 7-day exposure retention (ADR-0045), that is about 540,000 rows at most.
- Incidents opened before this change keep their identity. New incidents can now open in any
  district.
- District rain rows exist only for the four `rain_areas` districts. Widening it later is a
  config change, but it multiplies Longdo Weather calls by the number of districts.
