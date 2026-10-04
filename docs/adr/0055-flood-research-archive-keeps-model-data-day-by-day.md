# ADR-0055: a flood research archive keeps model data day by day, without personal data

## Status

Accepted on 4 October 2026 by the Product Owner:

- "save all the data somewhere for the data scientists to build the model";
- "we keep only important data for the model later".

Design: [`docs/pilot/2026-10-04_Flood_Research_Archive_Design.md`](../pilot/2026-10-04_Flood_Research_Archive_Design.md).
It adds to ADR-0045 (retention); it does not replace it.

## Context

- Retention removes facility states after 7 days and raw downloads after 14. The first facility
  states would have gone on 10 October 2026.
- Labels (officer checks, later camera checks and sensors) are scarce and must be kept from the
  first day in one form.
- The backup capture (`grpcli.floodboard_capture`) kept report text and links with no deletion,
  which breaks ADR-0038.

## Decision

1. **`core/flood_evidence/archive.py`** writes each finished UTC day, once, to
   `research/flood/<pilot>/v1/<table>/<day>.jsonl.gz`, plus `manifests/<day>.json` written last.
   - **Tables:** `road_state`, `road_geometry`, `report`, `incident`, `incident_event`,
     `incident_run`, `facility_exposure`, `label`, `weather` and `context`.
   - **State changes, not snapshots.** Roads and reports use the existing change log
     (`valid_from` and `valid_to` as of the export). Facility rows are written only when the state
     changes.
   - **No personal data.**
     - Reports are keyed by a salted HMAC of the record key.
     - Officers get a stable salted pseudonym.
     - Officer notes, report text, links and provider IDs are never written.
     - The salt is kept at `private/flood-archive-salt`, outside the research folder.
   - **Pinned versions:** rows made by a rule carry `rule_version`. The manifest records the
     archive version, the row counts, SHA-256 values, the fetch counts and the licences.
   - Today and replays are refused. Storage keys are immutable, so a day is never overwritten.
2. **The worker archives before retention**, in the same hourly housekeeping.
   `python -m grpcli.flood_pilot archive` does the same by hand, including the backfill.
3. **The backup capture is cleaned.**
   - `reports.csv` is cleaned before it is written: `id` and `text` become `sha256:<hex>`, and
     `url` is emptied.
   - `parse_reports` and `record_key` read the cleaned file to the same keys and states.
   - `--clean-existing` cleaned the 29 earlier files on 4 October 2026, with the owner's approval.
4. **Format:** gzipped JSON Lines, with no new dependency. A GeoParquet copy can be added later.
5. **Place:** GRP storage on this machine for now, then the Ubuntu host. No public route. Data
   scientists read the files.

## Consequences

- The archive is a small fraction of the raw data. Its size is measured in the handover.
- `valid_to` is as of the export. A state that continued past midnight is not extended
  afterwards; the next change starts a new row. Models must rebuild time series from changes.
- Incident districts are approximate (`district_codes_approx`: the box corners and centre).
- Missing evidence is not a "dry" label. The data card says so.
- Sharing outside ADPC needs DDPM's and each source's terms. Longdo weather is internal research
  only.
