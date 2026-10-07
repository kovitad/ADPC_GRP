# ADR-0049: Longdo Weather rain is context, never evidence, and live only

## Status

Accepted on 3 October 2026 for the Gate A local demo. This is part 2 of the Longdo integrations
the Product Owner chose (ADR-0048 covers events).

## Context

- **Longdo Weather** (`weather.longdo.com`, OpenAPI 1.0.1) offers rain now at a point, within a
  radius or within a polygon; a +15/+30 minute forecast; radar tiles and layers every 15
  minutes; and wind. It uses the shared Longdo key, sent as `?key=`.
- **Terms:** the service is provided "as is". Radar is an estimate and must not be the only basis
  for evacuation or travel decisions. No quota is stated on the terms page; it depends on the
  key's plan.
- **Measured on 3 October:**
  - `/area` and `/location` returned 503 once, then worked;
  - `/polygon` returns **403** for this key's plan;
  - forecast and layer list work.

## Decision

1. **Live pilots only.** A worker step, separate from ingest, runs every 5 minutes when the worker
   is idle. It calls Longdo only when the radar `observation_base_time` changes. Replays never
   call Longdo and show "not available in a replay".
2. **Scopes:** the four demo districts (a circle around each centre, up to 8 km) and the top 10
   active incidents (a circle from their extent, 0.5–3 km). Each scope records rain now (`/area`)
   and the +15/+30 minute forecast (`/forecast/area`). That is about 28 calls per radar image,
   about 2,700 a day; check this against the key's plan in the console.
3. **Unknown is never "no rain".** A failed call is stored as unavailable and shown as "rain
   unknown".
4. **Rain is context.** It is never a source family and never changes confidence, conflict or
   access. It reaches the facts as its own fact `W` (kind `rain`), and the AI instructions say
   "rain is not flooding, and a forecast is not an observation".
5. **The key stays secret.**
   - The launcher copies `LONGDO_API_KEY` from `.env` into the secret file `longdo_api_key`, and
     settings read `longdo_api_key_file`.
   - The `httpx` logger is raised to WARNING, so request URLs (which carry the key) are never
     logged.
   - Stored errors are redacted.
   - Verified live: the key is in neither the stored rows nor the worker log.
6. **On the page:**
   - a "Rain now" card (the heaviest level in the area, plus the next 30 minutes);
   - a "Rain here (context, not flooding)" section on each incident;
   - a Longdo Weather coverage row;
   - Longdo's legend words in Thai and English.

## Consequences

- **Live, 15:45–16:00 on 3 October:** no rain over the demo districts or the top incidents, and
  none forecast for the next 30 minutes.
- **The radar map layer is not built.** It would need a tile proxy to keep the key off the page.
- **Tests:**
  - one run per radar image;
  - an unavailable reading stays unknown, and the key never appears in stored errors or logs;
  - the `httpx` logger stays quiet;
  - replays never call Longdo;
  - the AI is told rain is not flooding.
