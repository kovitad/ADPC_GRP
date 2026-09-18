# Bringing the real Thailand datasets into GRP

**Status:** Proposed. Needs the product owner's choice in Section 6 and the Scientific and Data Authority's provenance for DEP-04 to DEP-07.
**Date:** 18 September 2026.

> **The files are now on this PC and have been inspected.** See
> [`thailand-dataset-inventory.md`](thailand-dataset-inventory.md) for what they actually
> contain, including the blocking question about how dry land is stored in the flood raster.
> The size estimates below are settled: the six flood tiles total 113 MB, and the two
> vulnerability rasters are about 600 MB each.

## 1. The four datasets

| Dataset | Form | GRP use | Dependency |
|---|---|---|---|
| Administrative boundaries | Shapefile | Supported assessment areas (`boundary`) | DEP-04 |
| Evacuation centers | Points | The features an assessment classifies (`feature`) | DEP-06 |
| Flood depth RP100 | Raster | The hazard layer the method samples, and the map's flood colours | DEP-05 |
| Vulnerable people | Raster, values 0 to 1 | Increment 6 only; a map layer before that, clearly marked as not approved | DEP-07 |

Source folders are on the ADPC Google Drive. **Files never go into Git.** They are downloaded once, recorded with provenance, and stored under the storage root (`/srv/grp/data`, `.local/data` in development).

## 2. What already works, and what does not

- **Analysis is ready for large rasters.** The worker reads only the pixels under each center (a windowed read), so a country-wide file costs little per job.
- **Drawing is not.** The current flood layer is one PNG covering the whole raster, drawn once at seed time. That is fine for the 120 × 120 synthetic test file and impossible for Thailand.
- **Boundaries are stored as GeoJSON.** Real district geometry should move to PostGIS columns, with a simplified copy for the map.

Rough size expectation for a country-wide flood raster: a few hundred megabytes when it stores the 1 to 5 severity classes with compression, and several gigabytes when it stores continuous depth as 32-bit values. Confirm from the file before deciding anything.

## 3. Ingestion pipeline (one command per dataset, idempotent)

1. **Receive.** The file is downloaded by a person into `.local/data-in/` (ignored by Git). Nothing reaches out to Google Drive from the code.
2. **Record provenance.** Source, edition or publication date, licence, retrieval date, and a SHA-256 of the original file. The spec requires this before anything is presented as evidence.
3. **Convert.** Rasters become Cloud-Optimized GeoTIFF: internally tiled, compressed (DEFLATE with a predictor), with overviews. Keep the original as the pinned source; the COG is the working copy.
4. **Store.** Written through the storage interface under a generated key; the fingerprint goes in `dataset_version.sha256`, metadata in `dataset_version.metadata`.
5. **Register.** One `dataset` row per named source and one `dataset_version` per locked copy, with `is_current` moved only on replacement. Old versions stay, so old results keep their inputs.
6. **Verify.** Re-read the stored file, confirm CRS is EPSG:4326, confirm the value range matches the declared legend, and log a `dataset_accepted` security event.

## 4. Per dataset

### 4.1 Administrative boundaries
- Load districts with `admin_code`, `admin_level`, name, source, edition and a geometry fingerprint.
- Move `boundary.geom` to a PostGIS geometry column (migration), keeping a simplified copy for the browser so full-detail outlines are not sent to the map.
- Mark only the districts the Scientific and Data Authority approves as `is_supported`.
- **Result:** real districts become selectable GRP assessment areas; the chat's area confirmation then matches real names.

### 4.2 Evacuation centers
- One `dataset_version`, then `feature` rows with name, longitude, latitude and safe attributes.
- Fingerprint is order-independent, as now, so re-imports do not invalidate pinned jobs.
- Required fields and the provider must come with DEP-06.

### 4.3 Flood depth RP100
- Convert to COG. If the file holds the 1 to 5 severity classes rather than depth in metres, keep it that way: it is far smaller and matches the legend the planner already sees.
- The method reads windows, unchanged.
- Record the return period on the version (`return_period_years = 100`), so the seven scenarios of Increment 5 slot in later.

### 4.4 Vulnerable people
- Store and register like any dataset, but **do not** let it enter a result until DEP-07 defines the layer and the meaning of its values.
- Until then it appears as a map layer marked "not approved", replacing today's placeholder.

## 5. Drawing the flood layer on the map

| Option | How it works | Pros | Cons |
|---|---|---|---|
| **A. Per-district picture** (recommended for MVP) | When a district is loaded, the worker draws one PNG clipped to that district, stored and served like today's overlay | Simple; reuses the existing path; small files; keeps GIS in the worker (AD-03) | Flood colours only inside supported districts; no smooth country-wide zoom |
| **B. Map tiles on demand** | A tile service cuts the COG into map tiles as the planner pans and zooms | Country-wide layer at any zoom; the usual web-map experience | A new service to run, cache and monitor; must stay outside the API to keep AD-03 |

Recommendation: **A now, B when planners ask to browse the whole country.** B is the first extraction candidate in the scaling design.

## 6. Decisions needed

1. **Option A or B** for drawing flood depth.
2. **Does the flood raster hold depth in metres or the 1 to 5 classes?** If unknown, GRP reports size, resolution, CRS and value range first.
3. **Licence and edition** for each dataset, for the provenance record.
4. **Which districts are approved** as supported assessment areas at pilot start.

## 7. Order of work

1. Inspect the downloaded files and report size, resolution, CRS and value range. No code changes.
2. PostGIS geometry migration and the boundary loader; load approved districts.
3. Evacuation-center loader; one real district assessed end to end against the synthetic-style checks.
4. Flood COG conversion and Option A rendering; the map shows real flood colours for that district.
5. Compare with the signed Chiang Yuen result when DEP-04 arrives; only then is Increment 1 accepted.
6. Register the vulnerability raster as an unapproved layer, ready for Increment 6.

## 8. Rules that do not bend

- Data files never enter Git, and no key or personal data is stored with them.
- A result is never shown without its pinned versions and fingerprints.
- A dataset without a recorded licence and edition may be loaded for testing but must not be presented as evidence.
- Replacing a dataset creates a new version; earlier results keep the inputs they used.
- The vulnerability layer stays out of results until it is approved.
