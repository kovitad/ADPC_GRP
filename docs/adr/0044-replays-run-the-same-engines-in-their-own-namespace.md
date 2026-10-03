# ADR-0044: Replays run the same engines in their own namespace, on a forward-only clock

## Status

Accepted on 3 October 2026 for a local demo (Gate A). This is slice 6 of the Bangkok flood pilot
plan, covering spec §30 and AC9: replay as test harness, demo and training tool. Part 6a, build
and playback, is described here. Part 6b, injected reports and outages, is added below when
built.

## Context

- Every live roads snapshot's raw bytes are already stored, gzipped, under
  `flood_source_fetch.storage_key`. Failed pulls are stored as rows too.
- **A road row only knows its newest snapshot,** because `last_fetch_id` moves forward, so past
  road states cannot be read back from live tables. ADR-0038 anticipated this: replay re-runs the
  stored fetches.
- **A replay must never pass for live data or create real records.** Reviews would write
  `AuditEvent`s against a real Hub, and AI would spend the allowance and send simulated evidence.

## Decision

1. **Each replay has its own namespace.** Every row carries `pilot_id = r` plus 11 hex
   characters. `PilotConfig` gains `base_id` (whose facility, camera, outline and Hub settings
   to use) and `clock` (the simulated time).
   - Replay configs are built with `dataclasses.replace` and never cached.
   - Replay IDs are checked against a strict pattern before any database lookup.
   - Replays are never listed as pilots.
   - The worker's live pull loop never touches them.
2. **Same code, same order.** The worker walks the live pilot's stored fetches, successes and
   failures, in `retrieved_at` order, through `ingest_body`, which now accepts `stored_key` and
   points at the original raw bytes instead of copying them. Exposure and incidents run after
   each roads snapshot, with that snapshot's time as "now".
   - One stored fetch is processed per idle worker pass, after assessments, imports, inspections
     and live pulls.
3. **The clock moves forward only.** `advance` raises the target time. `restart` wipes the
   namespace (children first, ending with fetches) and rebuilds. There is no jump back.
4. **Reads are clamped.** Every flood route uses `now_for(config)`, which is the replay clock in
   a replay, and an explicit `as_of` past the clock is refused.
5. **Read-only.** In a replay:
   - incident reviews and facility access confirmations return `409 REPLAY_READ_ONLY`;
   - `/ask` returns the computed answer only, with reason `replay`;
   - the `L` fact says "simulated time" and "uses today's facility list, cameras and rules".
6. **Limits:**
   - at most 3 open replays per pilot;
   - at most 12 hours per replay;
   - deleted automatically after 24 hours;
   - building, moving, restarting and deleting need a pilot-Hub membership; anyone who can open
     the pilot can watch.
7. **Routes** under `/api/v1/pilot/flood/{pilot_id}/replays`: list (with the stored range),
   create, read, `advance` (`to` or `by_minutes`), `restart` and delete. A replay's data is read
   through the ordinary routes with the replay ID as `pilot_id`.
8. **On the page** (`?replay=<id>`):
   - a sticky purple "REPLAY · simulated time … · not live data" bar, and "REPLAY" in the tab
     title;
   - player controls: play or pause, speed (1×, 5×, 20×, 60×, meaning simulated minutes per
     real minute), +10 minutes, +1 hour, restart, delete, and back to live;
   - every age, the hour window and "shown at" use the replay clock;
   - officer buttons are hidden;
   - links keep `?replay=`;
   - the live page has a "Replay a past period" panel.

## Consequences

- **Real data, 3 October:** a replay of 10:00–11:40 Bangkok time processed 21 stored downloads in
  76 s. Its incident runs matched live exactly after 11:08 (59, 55, 55, 55 open incidents). The
  test replay was deleted afterwards.
- **A replay uses today's registries and rules.** The facility file grew from 52 to 94 entries
  that morning, and the incident code changed during the day, so a replay of an earlier hour
  shows what today's rules make of it, not what the page showed then.
- **Tests:**
  - a replay reproduces the live runs and incidents and leaves live rows untouched;
  - failed pulls replay as failures, and raw bytes are not copied;
  - the clock moves forward only, and restart rebuilds;
  - wipe leaves no rows and refuses live namespaces;
  - bad windows are refused;
  - reads cannot pass the clock;
  - writes are refused and there is no AI in a replay;
  - replays are not listed as pilots.
