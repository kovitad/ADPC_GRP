# ADR-0070: bank outlook keeps observed level and forecast flow separate

## Status

Accepted on 12 November 2026 for the Bangkok flood pilot. It builds on ADR-0036 (River Watch reads
GEOGLOWS as display-only evidence) and ADR-0038 (stored Floodboard evidence with lineage).

## Context

Live users ask one question about a river bank: "will the water go over the bank in the next three
days?" The platform holds two facts that look as if they answer it, but they do not.

- **ThaiWater** reports an observed water level at one station. It also reports the provider's
  distance from that level to the bank. This is a past observation at a point.
- **GEOGLOWS** forecasts discharge in m³/s for a model river reach. It does not forecast a water
  level.

To turn forecast discharge into a future bank state, the platform would need three things it does
not have:

1. A reviewed pairing between a ThaiWater station and a GEOGLOWS reach.
2. A discharge-to-stage rating curve for that pair.
3. A model of local controls such as tides, gates and pumps.

Without them, any yes or no answer would be invented. Showing the two facts side by side could also
lead readers to combine them themselves.

## Decision

1. Add the protected route `GET /api/v1/pilot/flood/{pilot_id}/bank-outlook?area_code=…`. It has
   the same access as the other flood-pilot reads: signed-out users get 401, users in other Hubs
   get 403 and members of the pilot Hub get 200. It is recorded in the permission matrix.
2. **The observation stays observed.** The route returns one station's latest valid observation,
   never an area average. It picks a station inside the area's district first. Otherwise it picks
   the nearest station within `MAX_NEARBY_KM` (15 km), and the response labels the relationship as
   `in_area` or `nearby` and gives the distance. The observation carries `valid_until` from the
   pilot's stale threshold, an `is_stale` flag and the provider's bank difference and status, which
   are passed through as reported. If there is no suitable station, it returns `unavailable` with a
   reason code.
3. **The forecast stays discharge.** The route reuses the River Watch 72-hour view (ADR-0036). It
   splits the view into three fixed 24-hour slots measured from the window start. Each slot shows
   the first, last and peak median discharge and a rise, steady or fall trend. The trend uses the
   same ±5 % rule as River Watch. No new statistic is computed.
4. **Bank overtopping is always `undetermined`.** Each slot carries the reason codes
   `no_rating_curve`, `station_reach_not_reviewed` and `local_controls_not_modelled`. The response
   sets `overtopping_method: "not_available"`. Its limitations list says that undetermined is not
   evidence that flooding is unlikely.
5. **The two facts have separate roles.** The response labels them
   `observation_role: "observed_station_context"` and `forecast_role: "modelled_discharge"`. The
   user interface must not draw them on one axis or derive a bank state from them.
6. Replays (ADR-0044) return `not_available_in_replay` with three unavailable slots. They do not
   fetch a live forecast. Unknown area codes return 404, which keeps the route fail-closed.
7. The forecast fetch reuses the existing River Watch fetcher with its lock and cache. This route
   adds no new outbound path, and it does no GIS work.

## Consequences

Live can show a station's observed distance to the bank and a three-day flow trend. It does not
claim to know whether the bank will overtop. A yes or no state can be added only when a later ADR
records a scientifically approved station–reach pair and rating curve. That change would set
`overtopping_method` and remove the matching reason codes. The response shape is designed for this.

Each request may wait on a GEOGLOWS fetch, as River Watch already does. Failures are returned in
`forecast.problem`, not as errors.

### Gaps

- Only the permission cases are tested. Behaviour tests are still needed for: station selection
  (in area, nearby, too far), stale observations, slot splitting, replay and unknown area codes.
- The numbering is out of order: two ADRs are numbered 0069. This record uses 0070 because the
  code already cites it.
