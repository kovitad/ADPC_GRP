# ADR-0069: public flood feed waits for a successful snapshot

## Status

Accepted on 7 October 2026 for the temporary Lightsail pilot.

## Context

The Bangkok district feed always contains 56 district rows, even when no incidents exist. Before a
first successful Floodboard roads snapshot, those rows have null `as_of` and `valid_until` values
and zero incidents. If publication is enabled at that point, Global Risk's `generic_json` validator
can fetch a non-empty list and accept it even though it has no freshness evidence. That would make
"not fetched" look like "no flooding found".

The Product Owner approved enabling the regular Floodboard pulls and a replacement public pilot
feed after the old auto-approved contribution's temporary tunnel expired.

## Decision

1. Add the explicit bootstrap option `--enable-public-flood-feed`. It sets both
   `FLOOD_PILOT_PULLS_ENABLED=true` and `FLOOD_FEED_PUBLIC=true`; defaults remain false.
2. When publication is enabled but no successful timestamped roads snapshot exists, the public
   route returns HTTP 503 with `FLOOD_FEED_NOT_READY`. It does not return district zeros.
3. The feed returns HTTP 200 only when `checked_at`, `as_of` and `valid_until` are all present.
4. The worker remains the only process that contacts Floodboard. Web requests read stored evidence
   only.
5. A Global Risk replacement contribution is attempted only after an anonymous read proves 56
   timestamped district rows. The broken original must be retired or excluded to avoid duplicates.

## Consequences

A deployment may safely enable collection and publication together: the route stays unavailable
until the first good snapshot. Provider failure remains visible as 503 rather than misleading zero
risk. Existing protected routes continue to show an empty operational state to authorized users for
diagnosis.
