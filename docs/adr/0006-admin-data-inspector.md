# ADR-0006: Admin data inspector over a read-only source folder (Docker Desktop only)

**Status:** Accepted by the product owner on 2026-09-18 for local Docker Desktop testing.

**Date:** 2026-09-18

**Deciders:** Product owner and architecture owner (Ole); Technical Lead (Kwan) to review

## Context

The Thailand datasets have been delivered and sit in `.local/data-in` on the product owner's PC.
`tools/prove_dataset.py` proved them on three districts and found that the shelter district names
cannot be joined, that at least one shelter is in the wrong province, and that in Pua every
shelter sits on a pixel holding no value ([`docs/dataset-proof-results.md`](../dataset-proof-results.md)).

Those findings came from a script the product owner cannot run without a Python environment, and
each new question needs a developer. The Hub needs to see, for itself, what arrived, what is wrong
with it and what is missing, so it can go back to the provider — and it needs that **before**
anyone writes the loaders in backlog Epic A, because the findings change the loader design.

Loading the data properly is blocked on decisions DEP-04 to DEP-07. Looking at it is not.

## Decision

Add an Admin-only **Source data** page and `/api/v1/data-inspector/*`, enabled only when
`DATA_INSPECTOR_ENABLED=true` **and** `GRP_ENV=dev`, set only in `deploy/compose.desktop.yml`.

- **The folder.** `.local/data-in` is bind-mounted **read-only** into the api and worker
  containers at `/srv/grp/data-in`. The product owner keeps putting files there; the app can
  never write to, move or delete them. A browser cannot hand a Windows path to a server, so the
  page browses *within* this mounted root rather than opening a file dialog.
- **Who.** Platform Admin, or Hub Admin of any Hub. Not Planners and not Hub Experts:
  `PLANNING_MEMBER_ROLES` includes Admin and so cannot be used for this check. Covered by the
  permission matrix (`tests/contract/test_permission_matrix.py`).
- **Where it runs.** Reading GIS files is the worker's work (AD-03). Picking a folder queues a
  job in `dataset_inspection`, claimed with `FOR UPDATE SKIP LOCKED` under a lease, exactly as
  assessments are. The API never imports rasterio, shapely or pyogrio.
- **Caching.** The cache key is a fingerprint of every file in scope. Files up to 200 MB are
  hashed whole; larger ones (the ~600 MB vulnerability rasters) are hashed at head and tail with
  their size, and the report says which. Modification time is deliberately **not** used: through a
  Windows bind mount it can shift without a change and stay still despite one. A report is reused
  only while its files are unchanged, and a job whose files changed while it waited stops with
  `INPUT_FINGERPRINT_MISMATCH` rather than describing something else.
- **What it reports.** Per layer: CRS, size, resolution, value range, no-data share, columns with
  fill counts and sample values. Findings are graded **blocker** (cannot be loaded, or would be
  loaded wrongly, until someone decides), **problem** (usable but something is wrong) and
  **known** (already understood and on the backlog, shown so it is not rediscovered as a
  surprise). When both boundaries and points are in scope it cross-checks every point against the
  polygons and maps them.
- **It is never a result.** No version is pinned, no method is recorded, nothing is approved. The
  page says so at the top, and no number from it may be shown to a planner, put in a brief or sent
  to SIG. An inspection is not an assessment and shares no table with one.

## Options considered

| Option | Benefit | Main risk |
|---|---|---|
| Keep using `tools/prove_dataset.py` only | Already works; nothing to maintain | Needs a developer for every question; the Hub cannot see its own data |
| A standalone local web app outside GRP | No auth, no Docker, shareable report | Another thing to run; no reuse of the job queue, map or theme |
| Admin page inside GRP as a worker job (chosen) | Fits how the owner already tests; reuses jobs, map and theme; cached | A new page and table to maintain; dev-only for now |
| Read the files in the API | Simplest to write | Breaks AD-03 and would block the API on a 600 MB read |

## Consequences

- Not for Sandbox, staging or production. Moving it needs a security review (the folder becomes a
  server-side read surface), a spec update and a new decision.
- The report describes delivered source data **before ingestion**. ADR-0007 records the owner's
  acceptance of the Data Science delivery, but presenting preview numbers as an assessment or
  evidence would still breach AD-12 and Section 8.4; the warning banner and this ADR are the control.
- `hub_id` on `dataset_inspection` is nullable: the source folder belongs to the server, not to a
  Hub, so a Platform Admin who is a member of none may still inspect it. Consequently any Admin
  can read any inspection — acceptable while there is one shared read-only folder on one local
  machine, and a reason this stays dev-only.
- Head-and-tail fingerprints can miss a change in the middle of a very large raster. The report
  marks those files, so a reader knows which lines to trust. If that becomes a real risk, raise
  `FULL_HASH_LIMIT_BYTES` and accept the slower first read.
- `tools/prove_dataset.py` stays. It is the independent check against this page, and against the
  loaders when they exist.

## Action items

- [x] Read-only mount, settings flag, migration `20260918_0006`, worker claim loop
- [x] Findings graded blocker / problem / known, with the known ones naming their backlog item
- [x] Permission matrix rows, path-traversal tests, cache and concurrency tests
- [ ] Product owner accepts the page in the browser against the real `.local/data-in`
- [ ] Feed the nationwide counts into backlog A2 and the provider conversation
