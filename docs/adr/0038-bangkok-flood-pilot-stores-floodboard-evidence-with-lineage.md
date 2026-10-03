# ADR-0038: The Bangkok flood pilot stores Floodboard evidence with lineage and freshness

## Status

Accepted on 3 October 2026 for a local demo (release Gate A in the integration tweak). It covers
slices 1 and 2 of [`docs/pilot/2026-10-03_Bangkok_Flood_Pilot_Implementation_Plan.md`](../pilot/2026-10-03_Bangkok_Flood_Pilot_Implementation_Plan.md).

The Product Owner made these choices on 3 October:
- capture now;
- OSM for exposure assets (later slice);
- "add Hub operators" for access;
- build slices 1 and 2 first.

The inputs are the owner's development spec v0.3, `GRP_Bangkok_Integration_Tweak_v0.1.md` and
`expected_outcome.docx`.

## Context

- **Floodboard publishes two open exports under CC BY 4.0.** They need no key:
  - `roads.geojson`, with about 5,000 road segments and a per-vehicle verdict;
  - `reports.csv`, holding about the last 24 hours.
- **Floodboard is itself a fusion of other sources:** Traffy, crowd reports, BMA sensors and BMA
  DDS.
- **Measured on 3 October:**
  - Roads have no IDs and names repeat. A SHA-256 of the geometry was stable for 5,002 of 5,013
    segments across pulls.
  - `conf` decays without `updated` changing, and `updated` can move on an unchanged segment.
    Report `current_weight` decays too.
  - Report `text` quotes news and Traffy complaints.
  - `stats.json` and `feed.json` do not exist.
  - `robots.txt` disallows `/api/cam/`.
- **Other sources are blocked.** The BMA water-level entry on data.go.th has only a data
  dictionary and no licence. The community CCTV catalogue has no licence.
- **The spec suggests Next.js, TypeScript and MapLibre.** The repo uses FastAPI, static `web/`,
  Leaflet, PostGIS and a worker.

## Decision

1. **Keep the existing stack.** This is a deliberate deviation from the spec's suggested
   frontend; the spec allows FastAPI and asks for replaceable parts. The Bangkok view is a page in
   the existing Pilot tab (`/flood.html`), not a second application, as the tweak asks.
2. **The worker fetches; the API only reads.**
   - `core/flood_evidence/ingest.py` pulls each source on its own interval (roads 10 min,
     reports 15 min). It runs only when no assessment, import or inspection is waiting, and only
     when `FLOOD_PILOT_PULLS_ENABLED` is true. That flag is off by default and on in
     `compose.desktop.yml`.
   - Each pull is bounded: a 20-second timeout and a byte cap.
3. **Every attempt is a `flood_source_fetch` row,** whether it succeeds or fails. The row holds
   the outcome, HTTP status, SHA-256 and the gzipped raw bytes in storage, so source health and
   audit come from one record.
4. **A file that fails its format check stores no observations** (fail closed). The last good
   data stays, shown with its real age.
5. **One `flood_observation` row per distinct observed state.** The state hash covers observed
   facts only: depth, closures, cleared, verdict, underlying sources and evidence class. It also
   includes a report's own time and a hash of its text. Floodboard's decaying scores are stored
   as `provider_judgement` and never create a new state. A repeated state only refreshes
   `reported_at`, `last_seen_at` and `last_fetch_id`.
6. **The current road layer is the latest good snapshot**, not the newest row per segment, so a
   segment Floodboard drops leaves the map. Reports are read as an event stream within a window
   (default 6 h, maximum 24 h).
7. **Freshness bands follow spec §11:** current ≤30 min, recent ≤2 h, aging ≤6 h, stale ≤12 h,
   expired after that. The bands are configured per pilot. Only current, recent and aging
   evidence counts as "now". An expired segment keeps its record but **loses Floodboard's verdict**
   and is drawn grey as "no recent report".
8. **Lineage and evidence class are always stored and shown.**
   - Floodboard's own source names are kept as `underlying_sources`, so a Traffy or BMA report
     reached through Floodboard and later directly is one piece of evidence, not two.
   - Zone, estimated, inferred and cluster features are `provider_derived`.
   - The verdict is served as `provider_verdict` and labelled as Floodboard's estimate. GRP
     computes no passability of its own until BMA supplies rules.
9. **Privacy.** Report text is reduced to a SHA-256 and links are not kept, so neither is ever
   served. Fixtures are redacted.
10. **Access ("add Hub operators").**
    - A pilot lists its Hubs in `core/data/flood_pilot_bangkok.json` (Bangkok: `adpc`). Every
      member of those Hubs, in any role, and every Platform Admin can open it. Another Hub's Admin
      is refused.
    - River Watch and HAND stay Admin-only (ADR-0036/0037). Non-admin members see the Pilot nav
      item pointing at `/flood.html`.
    - Configuration stays in code and admin hands.
11. **Routes,** all `protected` and read-only, under `/api/v1/pilot/flood`:
    - `/` (pilots the caller can open);
    - `/{pilot_id}`, `/{pilot_id}/situation`, `/{pilot_id}/roads`, `/{pilot_id}/reports` and
      `/{pilot_id}/areas`.
    - `as_of` may look back but never ahead.
    - There is no raw-bytes route for operators.
12. **Capture and backfill.**
    - `grpcli/floodboard_capture.py` saves both exports into the ignored
      `.local/capture/floodboard/` for replay.
    - `python -m grpcli.flood_pilot ingest-capture <folder>` loads captures through the same
      `ingest_body` the worker uses.

## Consequences

- The page answers the owner's screens 1 and 2 honestly. Floodboard is real. BMA, CCTV and
  assets appear as "not connected", never as "no flooding".
- **Storage grows.** Raw roads are about 2.4 MB per pull, about 0.3 MB gzipped, at 144 pulls a
  day. Observation rows grow only with real state changes. A retention rule is needed before
  Gate B.
- The latest-snapshot rule reads live state correctly. Replay (slice 6) will re-run stored raw
  fetches rather than query history at a past `as_of`.
- The area filter on the page is a display filter over the loaded features. Server-side spatial
  joins arrive with exposure (slice 4).
- **Not done here:**
  - incidents, corroboration scoring and verification actions;
  - CCTV, assets and AI;
  - direct BMA or Traffy feeds;
  - feed registration and Global Risk submission (Gate A forbids them).
