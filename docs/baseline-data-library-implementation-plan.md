# Baseline data-library implementation plan

**Status:** Approved scope for local Docker Desktop implementation; server upload and vulnerability activation remain gated.
**Date:** 19 September 2026.
**Design:** [`data-library-sig-assessment-design.md`](data-library-sig-assessment-design.md)
**Review:** [`data-library-solution-review.md`](data-library-solution-review.md)
**Decision:** [`adr/0008-baseline-and-hub-data-overrides.md`](adr/0008-baseline-and-hub-data-overrides.md)

## 1. Outcome of this implementation

Import the accepted Data Science baseline from the existing read-only `.local/data-in` mount into GRP-managed persistent storage and version records, excluding the large vulnerability rasters.

The completed local slice will provide:

- one versioned Thailand district-boundary collection;
- one versioned DDPM shelter dataset, materialized as spatial points;
- one logical RP100 hazard version containing a manifest of all six source tiles;
- immutable source checksums and provenance;
- background import jobs with progress, lease renewal, safe retry and completion notices;
- a Data library Admin page showing readiness and validation findings;
- exact version selection/pinning for later assessments;
- persistent data across API/worker image rebuilds.

It will **not** yet claim a real flood assessment. RP100 remains `waiting_for_method` until DEP-05 defines NoData and permanent-water behavior. Vulnerability remains `not_imported` until separate VM processing and DEP-07.

## 2. Decisions closed from the senior review

1. **SIG is optional.** A supported GRP assessment can run when SIG is unavailable.
2. **Hub-local inputs are private.** Any assessment using a Hub-local version is ineligible for SIG and returns 404 from the future evidence endpoint. Changing this requires a separate ADR.
3. **Boundaries are collection-versioned.** A boundary collection is a dataset version; each materialized boundary references that version. An assessment pins both boundary feature and collection version.
4. **Hazard is one logical version.** The six RP100 tiles are one ordered manifest with source checksums, extent and deterministic overlap rules. They are not six choices in the UI.
5. **No silent fallback.** An invalid Hub override stops; the person explicitly chooses another version.
6. **Long jobs renew leases.** Import implementation cannot begin processing large files until heartbeat renewal and idempotent promotion tests pass.
7. **Promotion is atomic.** Imports load into job-scoped staging and become selectable only after all checks pass.
8. **Local source import comes before browser upload.** The existing 2.1 GB is not transferred again.

## 3. Storage layout

Do not place source data in an image or writable container layer.

```text
.local/data-in/                    read-only source bind mount
        |
        | worker reads and fingerprints
        v
/srv/grp/data/imports/<job-id>/    job-scoped quarantine/staging
/srv/grp/data/datasets/<id>/<version-id>/
    manifest.json                  canonical source and file manifest
    original/...                   immutable accepted source files
    working/...                    COG/VRT or derived worker products
    previews/...                   display-only products
```

PostgreSQL holds datasets, versions, file manifests, import jobs, findings, Hub selections and materialized vector records. The named Docker volume survives container recreation. The storage protocol allows later movement to S3-compatible storage.

## 4. Schema plan

Migration `0008` should add or extend:

- `data_import_job`: category, source mode, state, progress, lease, attempts, support reference, requester and safe report;
- `dataset_file`: immutable file role, generated storage key, size and SHA-256;
- `dataset_version`: readiness state, provenance, accepted/current timestamps and importer version;
- `hub_dataset_selection`: unique Hub/category/scenario pointer to the accepted default;
- boundary collection/version relationship on `boundary`;
- spatial geometry columns and indexes in PostgreSQL, retaining a test-compatible representation where required;
- uniqueness preventing two current bindings for the same Hub/category/scenario.

Readiness states:

```text
received
validating
needs_correction
technically_valid
waiting_for_method
ready_for_acceptance
assessment_ready
retired
```

The transition to `assessment_ready` is deterministic and category-specific. A boolean alone is not sufficient.

## 5. Job and transaction plan

```mermaid
sequenceDiagram
    participant A as Hub or Platform Admin
    participant API as FastAPI
    participant DB as PostgreSQL
    participant W as Import worker
    participant S as Managed storage

    A->>API: Select known source category and start import
    API->>DB: Create queued import with idempotency key
    API-->>A: Job ID and support reference
    W->>DB: Claim job with lease
    loop During long processing
      W->>DB: Renew lease and progress
    end
    W->>S: Copy to job staging and recompute checksums
    W->>W: GIS validation and conversion
    W->>DB: Load job-scoped staging records
    W->>DB: Validate counts and compatibility
    alt all checks pass
      W->>DB: Atomic promotion to immutable version
      W->>S: Finalize generated storage keys
      W->>DB: Mark technically valid or waiting for method
    else validation fails
      W->>DB: Store safe findings; no selectable version
    end
    API-->>A: Shared job notification reports completion
```

Finalization must be idempotent. The same job cannot create two versions even if a worker dies after storage writes but before acknowledging completion.

## 6. Category implementation

### 6.1 District boundaries

Source: `administrative_boundary/district_boundary`.

- Require same-stem `.shp`, `.shx`, `.dbf`, `.prj`; preserve `.cpg` and metadata sidecars.
- Require polygon/multipolygon geometry and EPSG:4326.
- Map `ADMIN_ID2`, Thai/English district and province names, and `VERSION`.
- Validate unique administrative codes and geometry validity.
- Store full PostGIS geometry, simplified map geometry and geometry checksum.
- Initially mark only reviewed areas supported; importing 928 rows does not automatically authorize all assessments.

### 6.2 Evacuation shelters

Source: `evacuation_centers/shelters`.

- Require point geometry and EPSG:4326.
- Materialize the safe confirmed fields only.
- Assign district membership spatially, never from the unreliable district-name column.
- Report all 1,139 known name/geometry mismatches rather than moving points.
- Keep `สถา`, `สถ_1` and `รอง` out of planner-facing attributes until DEP-06 confirms their source mapping and meaning.

### 6.3 RP100 flood hazard

Source: `floods/flood_depth_rp100`.

- Register six GeoTIFFs as one RP100 dataset version.
- Manifest order is stable by source filename; record each checksum, bounds, CRS, resolution and NoData.
- Validate no unintended overlap or gap over Thailand; define deterministic selection at tile edges.
- Retain originals and produce COG/overview working copies sequentially with bounded memory.
- Generate district-clipped products only as worker jobs.
- End state is `waiting_for_method`, not assessment-ready, until DEP-05 is resolved.

### 6.4 Vulnerability

Do not copy or convert the large vulnerability rasters in the local baseline slice.

Record only a visible deferred item:

```text
Not imported — process separately on the deployment VM; scientific meaning pending DEP-07
```

No vulnerability dataset version is offered to assessments.

## 7. Local resource controls

- one import worker;
- one raster conversion at a time;
- GDAL cache 256–512 MB;
- block/window reads only;
- no whole-raster NumPy arrays;
- minimum 10 GB free temporary disk for the baseline slice;
- cleanup staging files after success and under a timed failed-job retention policy;
- assessment jobs have priority, but import jobs use a separate queue/class so neither starves indefinitely.

## 8. UI plan

Add an Admin-only **Data library** page:

- baseline and Hub datasets grouped by category;
- provider, edition, owner, readiness, current/replaced state and created date;
- **Import accepted baseline** actions that point to known source folders;
- required-file explanation before starting;
- progress through the shared background-job tracker;
- findings with blocker/problem/known severity;
- acceptance action only for `ready_for_acceptance` versions;
- explicit `waiting_for_method` explanation for flood;
- vulnerability deferred card;
- no browser upload in this first slice.

## 9. Tests and release gates

### Fast and contract

- legal readiness transitions only;
- category manifest validation;
- checksum and idempotency behavior;
- lease heartbeat and expired-lease reclaim;
- two workers cannot promote one import twice;
- one-current Hub selection under concurrent updates;
- cross-Hub routes return 404;
- planners cannot import, accept, replace or retire;
- malformed paths and unsupported files fail safely.

### PostgreSQL integration

- migration from empty;
- PostGIS geometry and indexes;
- staging rollback leaves no selectable partial version;
- baseline plus Hub shelter override resolves category-by-category;
- replacing current does not change prior assessment pins.

### Local browser acceptance

- import boundaries, leave page, receive completion notice;
- import shelters and see mismatch count;
- register all six flood tiles as one version;
- see flood waiting for DEP-05 rather than assessment-ready;
- rebuild API and worker and verify versions/files remain;
- verify a Planner can see ready inputs but cannot administer them.

## 10. Execution order

1. ~~Migration and domain state model.~~ **Built in migrations `20260919_0008` and `20260920_0009`; the latter adds boundary datasets and indexed PostGIS geometry.**
2. ~~Safe import queue.~~ **Built:** idempotent request, lease renewal, attempt fencing and one-time finalization are covered by fast tests and a two-worker PostgreSQL publication test.
3. ~~Managed staging, manifests, checksums and atomic promotion.~~ **Built:** copies are re-hashed, final keys are immutable and deterministic, database publication is one transaction, materializer failures roll back, and failed handled imports remove unreferenced bytes.
4. **Built, integration-tested and imported locally:** the boundary loader requires the complete same-stem delivery, validates EPSG:4326, required fields, unique codes and valid polygon geometry, writes full and simplified indexed PostGIS geometry, and leaves all areas unsupported. The persistent local library now contains all 928 features, six source files and 928 valid PostGIS geometries.
5. **Built and imported locally:** the shelter loader materializes all 10,303 points, assigns district membership by geometry, populates PostGIS points and reports all 1,139 district-name conflicts without moving them. The uncertain `สถา`, `สถ_1` and `รอง` fields are excluded; generated centre labels are used instead.
6. **Built and imported locally:** six RP100 originals form one ordered logical version; six COGs are generated sequentially with bounded GDAL cache and one national display PNG is stored. The version is `waiting_for_method` pending DEP-05.
7. **Built:** protected Data library summary and Platform Admin import actions now cover boundaries, shelters and hazard, with audit, status polling and shared completion notices.
8. **Built:** the Admin Data library page shows all three categories, readiness, counts, shelter conflicts and flood waiting state. ADR-0009 permits non-current `map_preview` versions on the Planning map without exposing them to assessment selection. ADR-0011 makes preview display opt-in and configures RP20/RP50/RP100 explicitly; only imported scenarios are enabled. ADR-0012 makes a completed assessment open its exact pinned red-tone hazard picture and all in-scope assessed centres.
9. **Partly complete:** Docker Desktop rebuilt, migration `0010` applied and real imports verified. A person must sign in again for visual browser acceptance of the protected map.
10. **Complete for the imports:** measured results are in [`baseline-map-implementation-report.md`](baseline-map-implementation-report.md) and `handovers.md`.

## 11. Plan after the local baseline is complete

1. **Resolve DEP-05** with Data Science: NoData meaning, modelled-area mask and permanent-water rule.
2. **Create and approve method v2** against the registered RP100 logical version.
3. **Run one real district assessment** and compare it with the independent proof tool and signed Chiang Yuen case when available.
4. **Implement one Hub shelter override** end to end, proving old results remain unchanged.
5. **Add browser upload** with quarantine, limits and security review, reusing the same import pipeline.
6. **Prepare the deployment-VM vulnerability command** for one-raster-at-a-time reprojection/COG conversion; keep versions out of assessments until DEP-07.
7. **Build summary/map exports** from immutable results.
8. **Implement the protected SIG evidence endpoint and `assessment_ref` contract** for platform-input assessments only.
9. **Move to S3-compatible storage and direct multipart upload** only when a second host or measured file sizes require it.
10. **Pilot hardening:** load, restore, security and operational alert rehearsals.
