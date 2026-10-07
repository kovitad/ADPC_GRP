# Data card: Bangkok flood research archive (FloodArchive v1)

**Where:** GRP storage, `research/flood/bangkok/v1/`. One gzipped JSON Lines file per table per
UTC day, plus `manifests/<day>.json`. ADR-0055.

**Read it:**

```python
import duckdb
duckdb.sql("select * from read_json_auto('research/flood/bangkok/v1/road_state/*.jsonl.gz')")
```

## Tables

| Table | One row per | Notes |
| --- | --- | --- |
| `road_state` | new state of a Floodboard road segment | `valid_from`/`valid_to` (as of export); `district_codes`; Floodboard's verdict and confidence are its estimates, not GRP's |
| `road_geometry` | segment geometry seen that day | join on `geometry_hash`; names in Thai and English |
| `report` | new state of a public report | `report_key` is a salted hash; no text, link or provider ID |
| `incident` | incident active that day | its state at export time; `district_codes` from its roads (`district_codes_basis` = `roads`), or a box approximation for incidents before ADR-0056 |
| `incident_event` | incident change (created, merged, split, receding, closed...) | detail as recorded |
| `incident_run` | incident pass over a roads snapshot | active count, run time |
| `facility_exposure` | change of a school, hospital or clinic's state | OSM facilities (ODbL) |
| `label` | officer check | `checker` is a stable pseudonym; `withdrawn_at` matters |
| `weather` | rain now and the 30-minute forecast per scope | Longdo: internal research only |
| `context` | archive day | config values and facility source |

## Caveats every model must respect

- **Missing evidence is not "dry".** Crowd reports cover busy places, daytime and main roads
  more often.
- **Labels are few.** Officer checks expire, and can be withdrawn.
- **Floodboard re-cuts segments.** A new geometry hash can be the same street.
- **Freshness:** Floodboard's `updated` time can be a recalculation (ADR-0038). Report
  `observed_at` is the better clock.
- **Rule versions change.** Compare like with like by `rule_version`.
- **Licences:**
  - Floodboard is CC BY 4.0 (credit "Floodboard (floodboard.org)").
  - OSM is ODbL.
  - Longdo is internal only.
  - Joins with DDPM baseline data need DDPM's terms before any sharing outside ADPC.
