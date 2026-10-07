# ADR-0045: Flood-pilot retention keeps facts and history, and removes old raw data and report IDs

## Status

Accepted on 3 October 2026 for the Bangkok flood pilot. This is the retention rule that
ADR-0038, ADR-0040 and ADR-0044 required before Gate B.

## Context

- **Raw Floodboard downloads** are stored gzipped for audit and replay. On 3 October that was
  about 6.4 MB in 5 hours, roughly 30 MB a day.
- **Report rows keep provider IDs** (`external_id`). Traffy ticket IDs and news links can lead to
  pages about people. ADR-0038 already keeps report text out.
- **One facility-state row is stored per facility per roads snapshot,** about 13,500 a day for
  94 facilities. "What changed" needs only the last 24 hours.
- **Storage deletes only whole generated folders,** never a loose key. Raw keys are filed by UTC
  day.

## Decision

1. **Settings live in the pilot config:** `"retention": {"raw_days": 14, "exposure_days": 7}`.
2. **`core/flood_evidence/retention.py`** runs hourly in the worker housekeeping, for live pilots
   only. It refuses replay namespaces, which expire on their own after 24 hours.
   - **Raw downloads:** whole UTC days strictly before `now − raw_days` are removed. The fetch row
     stays with its outcome, size and SHA-256, and `storage_key` is cleared.
   - **Report IDs** last seen before `now − raw_days` become `pruned:<record key>`. The observed
     facts (time, place, depth, cleared, source family) stay.
   - **Facility states** belonging to snapshots older than `exposure_days` are deleted.
   - **Kept:** observations, incidents, incident events, reviews and the audit log.
3. **Order:** `prune` changes the database and returns the folders to delete. The worker commits,
   then calls `delete_raw`, so no row ever points at a file that is already gone.
4. **Replays:** the "available" range counts only fetches that still have raw bytes, and a replay
   window containing removed raw data is refused (`raw_pruned`). A replay already built over a day
   that is later removed fails clearly on restart. This can only happen at the 14-day edge,
   because replays live 24 hours.

## Consequences

- **Raw storage** is bounded at about 0.4 GB at the current rate.
- **Replays reach back 14 days.**
- **Provider IDs that could identify people** are gone after 14 days.
- **Database rows still grow slowly** with real state changes. A cap for observations is not
  needed at pilot scale and is left for Gate C.
- **On the live stack on 3 October,** a dry run found nothing to remove yet: all data was from
  that day.
- **Tests:**
  - old raw days are removed and recent days kept, only after the commit, with SHA-256 kept;
  - old report IDs become opaque while their facts stay, and recently seen IDs are kept;
  - old facility states are deleted;
  - a second run changes nothing more;
  - retention never runs on a replay namespace.
