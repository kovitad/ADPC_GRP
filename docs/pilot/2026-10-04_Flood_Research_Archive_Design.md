# Flood research archive for data scientists: design

Status: design, 4 October 2026. Nothing built. The Product Owner asked: "since we launch the
first for DDPM, why don't we save all the data somewhere for the data scientists to build the
model based on the data?" This answers decision D6 of the DDPM reports design, and it is the event
archive that the insurance section asked for.

## 1. Why now

- **The pilot deletes history.** Raw downloads go after 14 days and facility states after 7
  (ADR-0045). The pilot started on 3 October 2026, so **facility states start disappearing on
  10 October**. An archive started before then loses nothing.
- **Labels are the scarce part.** A flood model needs examples of "flooded here, at this time"
  and "dry here". Officer checks, the planned camera check and later BMA sensors are the only
  labels we will ever have, so they must be kept in a consistent form from the first day.
- **One archive serves everyone.** The same archive feeds data science, DDPM after-action
  reports, and any future insurance or partner export.

## 2. What we hold today (measured on 4 October 2026)

| Data | Size | Kept by | Personal data |
| --- | --- | --- | --- |
| `.local/capture/floodboard/` (backup capture, roads, reports and manifest every 20 minutes) | 88 MB for 44 snapshots, about 2 MB each | never deleted | **yes:** `reports.csv` keeps report text and links |
| `flood_observation` (road and report states, changes only) | 41 MB, 24,071 rows | kept | no text; report IDs pruned after 14 days |
| `flood_asset_exposure` | 2.2 MB, 6,238 rows | **deleted after 7 days** | no |
| incidents, events, runs, weather, reviews | under 1.5 MB together | kept | reviews name an officer |
| raw downloads in GRP storage | about 30 MB a day before whole Bangkok | **deleted after 14 days** | reports export: yes |

**A problem to fix whatever is decided.** The backup capture keeps report text and links with
no deletion. That breaks the rule ADR-0038 and ADR-0045 set for the main pipeline. Section 6
fixes it.

## 3. What to archive: only what a model needs

The owner's rule (4 October 2026): **keep the data day by day from go-live as the source for
later models, but keep only what matters for a model.** Raw files are not kept forever.

### Kept indefinitely, one file per table per UTC day

| Table | One row per | Main fields | Why a model needs it |
| --- | --- | --- | --- |
| `road_state` | **change** of a road segment's state (not every snapshot) | segment key, district, depth, closed and cleared flags, Floodboard confidence, source families, `valid_from`, `valid_to` | the main signal; the full time series is rebuilt from changes |
| `road_geometry` | distinct segment geometry, once | geometry hash, line, road name and class | joins without repeating geometry |
| `report` | report observation | salted hash of the provider ID, time, point, source family, depth, cleared; **no text, URL or name** | point evidence and its timing |
| `incident` and `incident_event` | incident, and lifecycle change | footprint road keys, box, district codes, confidence, reasons, **rule version**, events | event targets: start, duration, size, merges |
| `facility_exposure` | **change** of a facility's state | asset ID, exposure and access state, nearest distance, rule version, `valid_from`, `valid_to` | the impact layer |
| `label` | human or machine check | target, label (`flooding_seen`, `dry_seen`, `cannot_tell`; later `water`, `partial_water`, `dry`), method (`officer`, `camera_check`, `sensor`), time, pseudonymous checker | **the ground truth** |
| `weather` | district or incident per radar observation | rain now and the 30-minute forecast levels | a predictor (Longdo: internal research only) |
| `river_forecast` | GEOGLOWS run per reach | the summary object and raw-bytes SHA-256 | a predictor for riverine areas |
| `context` | version change | OSM capture time, boundary edition, camera registry version, pilot config hash | reproducibility |

**State changes, not snapshots.** Most segments keep the same state for hours. Storing a row only
when something changes, with `valid_from` and `valid_to`, keeps the full history at a fraction
of the size. `flood_observation` already works this way.

### Not kept beyond today's retention

- **Raw Floodboard exports** (roads and reports): deleted after 14 days as now (ADR-0045). The
  research tables keep their facts, and each day's manifest keeps the SHA-256 of every raw file
  used, so the source can be identified.
- **Report text, links, provider IDs, names and photos:** never kept.
- **Per-snapshot facility rows:** replaced by state changes.
- **Replays:** never archived.

Size: to be measured in step 1. The state-change tables should be a small fraction of the 88 MB
the raw capture used in its first day.

## 4. Format and place

- **Format:** gzipped JSON Lines (`.jsonl.gz`), one file per table per day, with geometry as
  GeoJSON. This needs no new dependency: Python, pandas, DuckDB and QGIS read it directly.
  GeoParquet would be smaller and faster, but it adds `pyarrow`. It can be added later as a
  conversion without changing what is kept.
- **Layout** (in GRP storage, the same replaceable storage protocol):

  ```text
  research/flood/bangkok/v1/
    datacard.md                       what each table means, caveats, licences, label rules
    <table>/date=2026-10-04/part-000.jsonl.gz
    <table>/date=2026-10-04/manifest.json   row count, SHA-256, rule versions, sources
  ```

- **Who writes it:** a worker job, once a day for the previous UTC day. It runs **before**
  retention removes anything, and never in a web request. A day already written is never
  overwritten; a rerun writes `part-001` and the manifest says why.
- **Where it lives:** on the local stack for now (`STORAGE_ROOT`). Later, a bucket on the Ubuntu
  host or a cloud bucket (D-A2). Data scientists read files; there is no new public route.

## 5. Rules that keep it honest and usable

- **Labels are sparse, and the data card says so.** Only a few officer checks exist (2 reviews on
  4 October). "No report" is not "dry". Models must not treat missing evidence as a negative
  label.
- **Crowd data has biases, and the data card says so:** more reports where more people are, by
  day and on main roads; Floodboard re-cuts segments; its `updated` time can be a recalculation
  (ADR-0038).
- **Rule versions are pinned.** Incident and exposure rules will change. A model trained on
  `IncidentGrouping v0.1` must be able to tell which records came from it.
- **Replays never enter the archive.** Only live pilot IDs are exported.
- **Licences travel with the data:**
  - Floodboard is CC BY 4.0, so credit is required.
  - OSM is ODbL: a shared derived database must stay open.
  - Longdo weather and events, and anything from cameras, are **internal research only**.
  - DDPM baseline joins need DDPM's terms before any sharing outside ADPC.

## 6. Fixing the backup capture

`grpcli.floodboard_capture` keeps `reports.csv` with text and links indefinitely. Two options:

- **Strip at capture:** write `reports.csv` without the `text` and `url` columns, and hash the
  `id`.
- **Delete after 14 days:** match the main pipeline.

**Recommendation: strip at capture,** and delete the text already captured once the archive has
taken the facts. That is 44 folders today; nothing is lost that the research tier needs. The
deletion needs the owner's yes (D-A3).

## 7. Steps

1. **Exporter and data card** (`core/flood_evidence/archive.py`, a worker job, tests, ADR-0055):
   - all tables in section 3 except `river_forecast` and the camera labels;
   - tests: no text, URL or name in any file; replays refused; a day never overwritten; rule
     versions present; row counts match the database.
2. **Backfill** from 3 October: export every day still held, before 10 October, when facility
   states start to go.
3. **Measure the daily size** and record it in the data card.
4. **Fix the backup capture** (section 6).
5. **GEOGLOWS runs and camera labels**, once those features run on the stack.
6. **Later:** a GeoParquet conversion, a bucket off the laptop, and a read-only account for data
   scientists.

## 8. Decisions for the owner

- **D-A1. Start now?** Build the exporter and backfill before 10 October, so nothing is lost.
- **D-A2. Where?** Local storage on this machine for now, then the Ubuntu host. Or a cloud bucket
  now? A laptop disk is a single copy; one external backup would be wise.
- **D-A3. The backup capture's report text.** Strip it at capture and delete the 44 folders of
  text already held, once archived? Or keep it under a 14-day rule?
- **D-A4. Who gets access.** ADPC data scientists only, at first? Sharing outside ADPC needs DDPM
  and source terms (section 5).
- **D-A5. Officer pseudonyms.** Labels keep a stable pseudonym per officer (useful for checking
  agreement between people) but never a name. Is that acceptable?
