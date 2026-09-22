# Senior technical review: data library, SIG screening and GRP assessment

**Review date:** 19 September 2026

**Reviewed:** [`data-library-sig-assessment-design.md`](data-library-sig-assessment-design.md), ADR-0008, current models, worker and backlog

**Verdict:** **Approved for the bounded local baseline implementation; mandatory engineering gates remain before browser upload or server rollout**

## Executive assessment

The central architecture is correct:

- SIG is used for broad screening and external evidence;
- GRP owns deterministic assessments and immutable results;
- PostgreSQL/PostGIS stores metadata and spatial vectors;
- rasters and originals use managed file/object storage;
- slow GIS and ingestion work runs in background workers;
- a platform baseline can be selectively replaced by visible Hub-level versions;
- assessments pin exact versions and never silently fall back;
- an embedding/vector database is not introduced.

This is an appropriate modular-monolith design for the pilot and has a credible scale path. ADR-0008 now closes the P0 policy/model choices for the bounded local baseline scope. The lease, idempotency, atomic-promotion and concurrency controls remain implementation prerequisites, not optional follow-up work. Browser upload and server rollout still require the security and operational gates below.

## Findings requiring decisions

### P0 — resolve before schema or API implementation

#### 1. Hub-uploaded results conflict with the existing SIG privacy rule

The proposed design says Hub-local results might be shared when policy permits derived fields. The approved backlog and development plan currently require uploaded-data assessments to return 404 to SIG.

**Risk:** implementation could unintentionally expose a result derived from private Hub data.

**Required decision:** keep the existing default: any assessment using a Hub-local input is ineligible for SIG. If the product later needs sharing, create a separate ADR defining the allowed derived fields, consent, licence, disclosure review and audit event. Do not hide this inside ADR-0008.

#### 2. Boundaries are not versioned like the proposed model assumes

The design shows assessments pinning dataset versions, but the current `boundary` table is a separate global record with no Hub owner, dataset-version relationship or replacement lineage.

**Risk:** a Hub boundary override cannot be represented safely, and “current boundary” could mean something different from current shelters/hazard.

**Required change:** choose one model before migration design:

- recommended: make a boundary collection a dataset version and link each materialized boundary feature to that version; or
- create explicit `boundary_set`/`boundary_set_version` tables with Hub ownership and provenance.

An assessment must pin both the boundary feature and its collection version/fingerprint.

#### 3. Long import jobs have no lease renewal

Current jobs use a 15-minute lease and do not renew it. COG conversion, nationwide spatial checks and 600 MB raster processing can exceed that time.

**Risk:** a second worker can claim the same import while the first is still writing, causing duplicate versions or conflicting files.

**Required change:** implement heartbeat/lease renewal and idempotent finalization before any large import. Promotion to an accepted version must use a unique import key and one database transaction.

#### 4. “Accepted baseline” must not imply “assessment-ready baseline”

The source delivery is accepted, but the RP100 NoData meaning and vulnerability method remain unresolved.

**Risk:** a UI or developer may offer technically loaded flood/vulnerability data to an assessment before the scientific contract is approved.

**Required change:** store status independently per version: `received`, `technically_valid`, `method_compatible`, `accepted_current`, `retired`. Flood cannot reach `method_compatible` until DEP-05 is resolved; vulnerability cannot until DEP-07.

#### 5. Multi-tile hazard semantics are unspecified

The delivered RP100 source has six tiles, while the current `dataset_version` has one `storage_key` and the assessment worker reads one raster.

**Risk:** selecting a “flood version” could omit tiles, double-count overlaps or behave differently at tile boundaries.

**Required decision:** define one immutable hazard version as either:

- one generated national COG/VRT plus a manifest of source checksums; or
- a version with an ordered tile manifest and deterministic tile-selection/overlap rules.

The recommended MVP is a validated tile manifest plus generated per-district COG/PNG products; never present six independent tiles as six alternative RP100 datasets.

### P1 — resolve during detailed design

#### 6. Current-version and override resolution need database constraints

A boolean `is_current` alone does not guarantee one current version per dataset, Hub, category, scenario and method compatibility group.

**Required change:** add an explicit binding such as `hub_dataset_selection(hub_id, category, scenario, dataset_version_id)` with a unique key, or a partial unique index with equivalent semantics. Update the pointer and audit event atomically with optimistic concurrency.

#### 7. Compatibility is described but not modelled

The design says versions must be compatible but does not define the contract.

**Required change:** each method version must declare machine-checkable requirements: category, hazard type, return period, units, CRS handling, required fields, NoData policy, geometry level and vulnerability meaning. Compatibility is calculated by server code and stored with reasons, never inferred by an LLM.

#### 8. SIG screening must be optional, not an availability dependency

The flow currently places SIG before every detailed assessment.

**Risk:** SIG outage, authentication loss or latency could prevent a valid GRP assessment.

**Required change:** allow a planner to start a supported GRP assessment directly. SIG screening is recommended context, not a prerequisite. Record SIG and GRP area/source differences visibly when both are used.

#### 9. SIG and GRP can describe different hazards or areas

A SIG screen and GRP result may use different AOIs, return periods, source editions or NoData rules.

**Required change:** never imply that the SIG map is the visual rendering of the GRP result unless identifiers match through a reviewed contract. Show a comparison block: area source, hazard source, scenario, timestamp and known differences.

#### 10. Import work needs a separate queue or worker class

The current worker runs one assessment or inspection at a time. Large imports could starve planner jobs; always prioritizing assessments could also starve imports.

**Required change:** use separate PostgreSQL job types/queues and process classes: assessment, import/validation and export. They may initially share an image, but must have independent concurrency and service targets.

#### 11. Ingestion needs staging and atomic promotion

The design does not specify what happens when 9,000 of 10,303 features load and the final validation fails.

**Required change:** load into job-scoped staging tables/storage keys, validate counts and invariants, then promote metadata and materialized records in one transaction. Failed jobs retain only a safe report and quarantined files under a retention policy.

#### 12. Browser upload needs an explicit large-file protocol

Streaming through FastAPI is acceptable for small pilot files, but 600 MB–2 GB transfers need resumability, request-size controls, proxy timeouts, quotas and cleanup.

**Required change:** set pilot limits before coding. For large files, prefer direct multipart upload to S3-compatible storage with short-lived server-issued upload grants, checksum completion and quarantine. Do not scale by increasing API timeouts indefinitely.

#### 13. Tenant isolation needs defence beyond route checks

Application checks and 404 behavior are necessary, but import jobs, storage keys and dataset-selection queries introduce additional cross-Hub paths.

**Required change:** centralize Hub-scoped repository queries, make storage keys opaque, add cross-Hub contract tests for every route and job result, and evaluate PostgreSQL row-level security before multi-Hub production. Platform baseline reads must be explicit exceptions.

#### 14. Uploader and approver separation is ambiguous

ADR-0008 says the uploader is not automatically the approver, but a single Hub Admin could perform both actions.

**Required decision:** for MVP, allow the same Hub Admin but log both actions and show a warning; for production or sensitive datasets, support optional four-eyes approval. Platform baseline changes should require stronger review than Hub-local shelter updates.

### P2 — complete before pilot or wider scale

#### 15. Retention, deletion and legal hold are undefined

Immutable results require their inputs, but licences or privacy obligations may require deletion.

Define hot/archive retention, legal hold, tombstones, loss-of-licence behavior and how an old result is displayed if its source file must be removed. A checksum and manifest must remain even when bytes are legally deleted.

#### 16. Backup consistency must include object storage

Database rows and files must restore to the same version. Define coordinated backup manifests, restore ordering and orphan-file reconciliation. Test restoration of one historical assessment and all pinned inputs.

#### 17. Upload threat controls need completion

Add MIME/content sniffing, malware scanning policy, filename normalization, file-count and total-size quotas, raster dimension/pixel limits, malformed-driver timeouts and archive-bomb controls before ZIP support. GIS libraries must run with constrained CPU/memory and no network access.

#### 18. Observability and service targets are incomplete

Record bytes received, validation duration, queue age, worker heartbeat, rows/features loaded, raster conversion duration, failure code and storage growth. Define alerts and targets separately for uploads, imports and assessments.

#### 19. Capacity assumptions need a benchmark

The current pilot target is small, but national geometry, six large hazard tiles and vulnerability rasters have different CPU/RAM profiles. Benchmark one baseline import, one Hub shelter override, two simultaneous assessments and a concurrent upload before declaring the deployment size sufficient.

#### 20. Schema and field mapping need versioning

Provider columns can change independently of file edition. Store an importer/mapping version and include it in the dataset-version manifest. A code change to field mapping must not reinterpret an old imported version silently.

## Revised architecture gates

### Gate A — policy approved

- Hub-level override policy accepted.
- Uploaded-data SIG policy remains deny-by-default or is changed through a separate ADR.
- Uploader/approver rule agreed.
- Licence and retention owners named.

### Gate B — model proved

- Boundary collection versioning resolved.
- One-current-selection constraint tested under concurrent updates.
- Method compatibility contract represented in data.
- Multi-tile hazard manifest and overlap rule tested.

### Gate C — ingestion safe

- Quarantine, checksums, staging and atomic promotion implemented.
- Lease renewal and idempotent finalization implemented.
- Cross-Hub denial and malformed-file tests pass.
- Failure leaves no selectable partial version.

### Gate D — assessment reproducible

- A baseline assessment and a Hub-override assessment pin different visible manifests.
- Replacing a current version does not alter either result.
- Direct GRP assessment works when SIG is unavailable.
- SIG/GRP source differences are visible.

### Gate E — scale and recovery proved

- Large-file and concurrent-job benchmark meets targets.
- Database plus file/object-store restore is rehearsed.
- Two import workers never promote one job twice.
- Storage, queue and worker alerts are operational.

## Recommended implementation order after review

1. Apply ADR-0008's uploaded-data deny-by-default rule and optional—not mandatory—SIG screening in tests and UI.
2. Implement the selected boundary collection versioning and hazard tile-manifest shape through the schema plan.
3. Add lease renewal and two-worker concurrency tests before import jobs.
4. Build baseline import for boundaries and shelters using staging and atomic promotion.
5. Add method-compatibility records and flood manifest registration; do not enable flood assessment until DEP-05.
6. Add the Hub selection/current-binding model and one shelter-override acceptance test.
7. Build the Data library UI.
8. Add quarantined browser upload after limits and security controls are approved.
9. Move large uploads to direct object storage when the measured threshold is reached.
10. Implement SIG `assessment_ref` only after the privacy contract is approved.

## Scale verdict

| Scale | Verdict |
|---|---|
| Local development and one-Hub demonstration | Suitable after P0 fixes |
| Pilot: about 50 named users, 20 concurrent readers, 5 queued jobs | Suitable with lease renewal, separate job classes, PostGIS, shared state and recovery test |
| Multiple Hubs on one deployment | Conditional on stronger tenant isolation, quotas and Hub selection constraints |
| Multiple API/worker hosts | Requires shared token/rate-limit state and S3-compatible storage |
| National continuous raster browsing | Add a tile service and cache; do not serve whole rasters through FastAPI |
| Large regional or multi-country platform | Reassess database partitioning, object-store lifecycle, worker autoscaling and operational ownership from measured load |

The bounded local baseline implementation may proceed under ADR-0008 and the baseline implementation plan. It must stop before browser upload, scientific flood activation or server rollout unless the corresponding gates have passed.
