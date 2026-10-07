# Floodboard fixtures

These files were cut on 3 October 2026 from Floodboard's open exports for the Bangkok flood
pilot (ADR-0038). No credentials were used.

| File | Source |
|---|---|
| `roads_20261003.geojson` | Seven features from `https://www.floodboard.org/api/export/roads.geojson`. Each line keeps at most two parts of six points. |
| `reports_20261003.csv` | Eight rows from `https://www.floodboard.org/api/export/reports.csv` |

- **Source:** Floodboard (floodboard.org).
- **Licence:** CC BY 4.0. Keep this attribution.
- **Redacted:** report `text` is replaced and `url` is blank. Traffy, crowd and news IDs are
  replaced with `fixture-N`, because quoted complaints and links can identify people. BMA sensor
  and DDS IDs are kept.
- **Purpose:** these are parser and engine test inputs only. Never edit one to make a test pass.
- **Full captures:** the full live capture lives in the ignored `.local/capture/floodboard/` and
  is never committed.
