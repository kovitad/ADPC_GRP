# ADR-0008: Versioned platform baseline with Hub-level data overrides

**Status:** Proposed for product owner, Technical Lead, Data Science and security review.

**Date:** 2026-09-19

**Deciders:** Product owner and architecture owner (Ole), Technical Lead (Kwan), Scientific and Data Authority, ADPC security

## Context

ADR-0007 accepts the Data Science delivery as the initial source data. The product owner wants it to become reusable baseline data while allowing later users to contribute newer local data for selected categories. GRP must preserve reproducibility, Hub isolation and a clear relationship with SIG screening and evidence.

Allowing every person to silently replace a source would make two planners receive different answers and would make old results impossible to replay. Overwriting a baseline version would have the same problem. Sending raw data to SIG would unnecessarily widen the trust boundary.

The detailed design is [`../data-library-sig-assessment-design.md`](../data-library-sig-assessment-design.md).

## Decision

1. Register the accepted Data Science delivery as immutable **platform baseline** versions.
2. Permit a person to upload a candidate only within an administered Hub. A Hub Admin accepts a validated candidate before it becomes the Hub's current override. Platform Admins manage platform baseline versions.
3. Resolve inputs per category. A Hub may override shelters while retaining baseline boundaries and flood hazard, for example.
4. Never overwrite a version. Replacements create a new immutable version and move only the “current” pointer.
5. Every assessment shows and pins the exact boundary, dataset and method version IDs and checksums before the job runs.
6. Never silently fall back from an invalid or incompatible Hub override to the platform baseline.
7. Keep technical validation, source acceptance, method approval and assessment readiness as separate statuses.
8. Use SIG first for general screening. Use GRP for deterministic, reproducible assessments. Share only an Admin-approved public result field set with SIG; never raw files.
9. Use PostgreSQL/PostGIS for metadata and spatial vectors, the existing storage protocol for original files and rasters, and PostgreSQL-leased worker jobs for validation and ingestion. Do not add a vector-embedding database.
10. Implement existing-source import before browser upload so the 2.1 GB delivery is not transferred twice.

## Options considered

| Option | Benefit | Main problem |
|---|---|---|
| One platform baseline only | Simplest | Cannot incorporate authoritative local improvements |
| Per-user private defaults | Flexible for individuals | Inconsistent answers, weak governance and poor supportability |
| Hub-level accepted overrides over immutable baseline (chosen) | Local ownership with reproducibility | Requires version selection, acceptance UI and compatibility checks |
| Overwrite files in place | Easy storage model | Destroys replay and auditability |
| Use SIG map as the only hazard source | Avoids duplicate storage | Current embed is not a machine-readable, pinned calculation contract |
| Store GIS data in an embedding/vector database | Familiar AI pattern | Wrong operations and unnecessary infrastructure |

## Consequences

- A candidate uploader is not automatically the approver.
- The UI must expose provenance and selected versions, not hide resolution rules.
- Dataset compatibility becomes a server-side rule tested independently of the LLM.
- Storage grows because old versions are retained; retention policy may archive files but cannot invalidate stored results.
- Hub-local source data and raw uploads remain private by default.
- The existing `dataset` and `dataset_version` model must be extended with import jobs, multi-file manifests, validation/readiness states and Hub-current selection.

## Action items

- [ ] Product and Technical Lead approve the baseline/Hub override rule.
- [ ] Data Science confirms category metadata and DEP-05 flood NoData semantics.
- [ ] Security approves upload limits, quarantine and malware-scanning expectations.
- [ ] Add schema migration and contract tests.
- [ ] Build existing-source import before browser upload.
- [ ] Add PostGIS loaders for boundaries and shelters.
- [ ] Add COG registration and compatibility rules for hazard rasters.
- [ ] Add the Data library page and background notifications.
- [ ] Connect only assessment-ready versions to new assessment jobs.
- [ ] Implement the reviewed SIG `assessment_ref` evidence contract.
