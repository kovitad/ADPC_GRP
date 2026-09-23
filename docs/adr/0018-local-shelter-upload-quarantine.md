# ADR-0018: Keep local shelter uploads on the shared data volume

**Status:** Accepted for the Developer environment only on 2026-09-23. Server rollout remains
blocked on the ADR-0008 upload security review.

**Date:** 2026-09-23

**Deciders:** Product owner; Technical Lead and Security to review before staging

## Context

The existing Data Library imports Shapefile components already mounted under `DATA_IN_ROOT`.
For an end-to-end local test, a Platform Admin must be able to select the original shelter bundle
in the browser without first copying files into the repository. The API and worker already share
the persistent `STORAGE_ROOT` volume. PostgreSQL is needed for workflow and provenance, but storing
large binary files in database BLOBs would enlarge backups, WAL traffic and restore time without
improving validation.

## Decision

Add a Developer-only shelter ZIP upload guarded by `SHELTER_BROWSER_UPLOAD_ENABLED` and
`GRP_ENV=dev`.

- The browser sends one ZIP as the request body. The API streams it to
  `STORAGE_ROOT/quarantine/browser-uploads/<job-id>` without loading it all into memory.
- The ZIP must contain the exact `ddpm_shelters` Shapefile components. Paths, extra files,
  duplicate names, encryption, symbolic links, excessive expansion and missing sidecars are
  refused before worker processing.
- PostgreSQL stores the job, ownership, file list, sizes, state and audit event—not source bytes.
- The GIS worker reads the generated quarantine path, applies the existing shelter validator,
  copies approved components into immutable dataset-version storage and removes quarantine.
- This local feature does not upload to Google Drive, submit a SIG manifest, make a dataset
  current or bypass the existing baseline activation decision.

## Options considered

| Option | Assessment |
|---|---|
| PostgreSQL BLOB | Rejected: simple topology, but expensive backups/WAL and poor large-file lifecycle |
| Shared VM/Docker volume | Chosen for the single-host Developer pilot; matches the existing storage boundary |
| Google Drive | Rejected for ingestion: download links and permissions are not a stable storage contract |
| S3-compatible object storage | Preferred when a second host or measured upload size requires it |

## Consequences

- A Platform Admin can test the real 29.99 MB shelter bundle from the Data Library page.
- API and worker must share `STORAGE_ROOT`; Docker Desktop already does so.
- Raw quarantine is private and temporary. Immutable source components remain with their dataset
  version for replay and checksums.
- Production still needs malware scanning, retention/housekeeping targets, capacity monitoring and
  a reviewed upload limit. Until then the route stays disabled outside Developer mode.

## Action items

- [x] Streamed ZIP gate, generated quarantine path, audit record and existing-worker reuse
- [x] Permission, traversal, missing-sidecar and real DDPM bundle tests
- [ ] Technical Lead and Security review before enabling on staging
- [ ] Add malware scanning and abandoned-quarantine housekeeping before server rollout
- [ ] Replace local volume transport with direct multipart object storage only when required
