# Coastal Zoning Assessment implementation plan

**Source specification:** `docs/adhoc/grp-coastal-zoning-integration-spec-2026-10-23.md`
**Target branch:** `adhoc/grp-coastal-zoning-integration-spec-2026-10-23`
**Status:** In progress; lifecycle API, delegated MCP discovery, and Mangrove 360 shell implemented

## Implementation progress

Completed on this branch:

- ADR-0070 records the repository-native architecture and fail-closed gates.
- `core/coastal_zoning/models.py` defines persistent runs, P1-P10 checkpoints, zones, artifacts,
  and review history without storing receipt verdicts.
- Migration `20261023_0029` creates the five tables and constraints.
- `core/coastal_zoning/jobs.py` implements the currently unwired claim/lease, ordered checkpoint,
  progress, failure-duration, retry, and cancellation lifecycle.
- The starter-kit zoning function is ported to `core/coastal_zoning/rules.py`, pinned to its source
  SHA-256, and mechanically formatted without semantic changes. NumPy and SciPy are direct GIS
  dependencies.
- South Sumatra and Lamu pass their supplied golden thresholds. Four additional fast tests pin
  unknown hazards, DEM gaps, missing land cover, and class priority.
- Feature-flagged lifecycle routes now create/list/read/trace/cancel/retry Hub-scoped runs with
  idempotency, audit events, P1-P10 status, cross-Hub 404 behavior, and no GIS work in requests.
- `SigMcpClient.list_tools()` performs bounded MCP discovery. A delegated-user capability route
  proved the live `platform_capabilities`, `resolve_place_time`, `assemble_pack`, and
  `publish_answer` schemas; the sanitized schemas are pinned under `tests/fixtures/sig/`.
  `assemble_pack.geometry` advertises object or array input and `publish_answer` requires
  `pack_id` plus `draft`. Receipt verdicts remain view-time HTTPS resolver data.
- The complete suite passes 1,299 with two PostgreSQL-only skips. Ruff and whitespace checks are
  clean.
- The supplied Mangrove 360 brand kit is integrated without changing asset bytes: branded SERVIR
  sign-in, responsive coastal workspace, fictional-image disclaimer, recent Hub runs, and a
  feature-aware `Mangrove 360` link in the existing GRP menu. Desktop and 390 px browser checks
  pass; source asset hashes are regression-tested against the supplied manifest.
- Docker Desktop was rebuilt through `scripts/docker-desktop.ps1`; migration `20261023_0029` is at
  head and API/database/worker are healthy. Browser smoke tests proved delegated MCP discovery and
  create/read/ten-step-trace/cancel lifecycle behavior.

Not enabled yet: worker claims, actual polygon pack calls, GIS pipeline execution, AI, artifacts,
or the full AOI/report UI. The kit has no explicit licence file and its README says the fixture DEM licence/vintage is
unstated, so the fixture bytes remain local and the golden test skips where an approved fixture
directory is not configured. Confirm repository/fixture redistribution rights before committing
them. The MVP reuses the signed-in user's existing MCP authentication in an API-side coordinator;
no worker service credential is required. A real small-polygon `assemble_pack` call and bounded
pack-limit/trace-field fixtures remain external-execution gates.

## 1. Goal

Deliver an authenticated, asynchronous Coastal Zoning Assessment that accepts a bounded coastal AOI, executes a deterministic worker-side zoning pipeline, uses AI only for cited zone briefs, persists traceable artifacts, and presents a four-view atlas with receipt status resolved at view time.

The implementation must preserve existing GRP boundaries:

- FastAPI requests validate, authorize, enqueue, and read results; they do not perform GIS work.
- `worker/` claims and executes persistent jobs.
- `core/` owns models, pipeline rules, validation, GIS processing, and storage-neutral artifact logic.
- Routes remain under `/api/v1` and declare `x-grp-access`.
- The existing SERVIR login, Hub membership, audit log, rate limits, AI allowance, Langfuse integration, and `Storage` protocol are reused.
- Missing data remains unknown; it is never converted to zero or low risk.

## 2. Repository fit and corrections to the draft specification

The source specification describes a different repository layout. In this repository use the following mapping:

| Draft location or assumption | This repository |
|---|---|
| `apps/api/src/app/zoning/` | Domain code under `core/coastal_zoning/`; HTTP routes in `api/coastal_zoning.py` |
| `apps/web` React component | Static pages and modules under `web/coastal-zoning*.{html,js,css}`; reuse the existing Leaflet pattern |
| `/api/zoning/*` | `/api/v1/coastal-zoning/*` |
| New RQ/Arq/Celery queue | Extend the existing PostgreSQL job-claim/lease worker in `worker/main.py` |
| New artifact abstraction | Extend the existing `core.storage.Storage` protocol only if streaming is needed; use immutable generated keys under `coastal-zoning/{run_id}/` |
| In-process SIG platform tools | Not available in this repository; SIG is remote through `api.mcp_client.SigMcpClient` |
| User's MCP token for long jobs | Keep it in the API's existing in-memory session store. An API-side coordinator performs external stages; the GIS worker receives only immutable artifacts. Expiry/restart fails with sign-in-and-retry |
| New `zoning:run`/`zoning:review` roles | Prefer mappings onto current Hub roles rather than adding roles in the MVP |

Recommended initial role mapping, subject to product-owner approval:

- Run and view own Hub runs: `ndmo_planner`, `hub_expert`, `admin`; Platform Admin may operate across Hubs.
- Review: `hub_expert`, `admin`; Platform Admin may review.
- Retire: owner, Hub Admin, or Platform Admin.
- Ordinary users see only their own runs. Reviewers see runs in their Hub. Unknown, cross-Hub, and unauthorized IDs all return 404.

## 3. Phase 0 gates

Do not begin network-backed pipeline work until these gates are closed and recorded in an ADR.

1. **Obtain and inventory the starter kit.** The repository currently does not contain `mangrove360-zoning-starter-kit.zip`, `make_zones_winwin`, the atlas engine, fixtures, golden outputs, sample packs, or the complete `sites.json` contract. Record source, licence, checksums, and approved repository location. Do not commit large/raw source datasets.
2. **Freeze the SIG contracts.** Capture sanitized fixtures and schemas for `resolve_place_time`, `assemble_pack(geometry=...)`, `publish_answer`, receipt resolution, capabilities, layer identifiers, pack limits, and trace fields. Confirm that arbitrary polygon geometry is accepted.
3. **Confirm delegated MCP orchestration.** Reuse the signed-in user's existing MCP token only in
   the API process for read/assemble/publish calls. Never persist or forward it to the worker. If
   the token expires or the API restarts, mark the external checkpoint `SIG_SIGN_IN_REQUIRED` and
   let the owner sign in and retry.
4. **Approve legal configuration ownership.** Name the reviewer role and review date for Indonesia and Kenya. Unreviewed rows must render as “to confirm”; code must not imply legal approval.
5. **Approve quotas.** Confirm local/province AOI limits, maximum tiles, per-user daily runs, global concurrent runs, and artifact retention.
6. **Confirm evidence licences.** Verify that each remote layer may be processed, cached for the selected period, and included in derived downloads.
7. **Approve the AI boundary.** Confirm the configured model, AI allowance charging, prompt/content telemetry policy, two-retry ceiling, and behavior when AI is disabled or allowance is exhausted.
8. **Resolve product ambiguities.** Confirm whether there are five or six download groups, the exact meaning of “share inside the platform,” cancellation semantics, and whether SSE is required for MVP.

Deliverables:

- ADR-0070 covering queue reuse, delegated MCP orchestration, role mapping, storage/retention, AI
  boundary, and fail-closed behavior.
- Sanitized SIG contract fixtures in `tests/fixtures/`.
- Checked-in starter-kit code/assets permitted by its licence, with provenance and hashes.
- A short data-protection and licence checklist signed off before live pilot calls.

## 4. Delivery slices

Each slice should be independently reviewed and leave the main application usable.

### Slice 1 — Deterministic rules and golden baseline

Add `core/coastal_zoning/` with:

- `models.py`: typed enums/value objects for profiles, scales, zone codes, parameters, evidence state, and step state.
- `rules.py`: reviewed port of `make_zones_winwin`; preserve behavior before refactoring.
- `masks.py`, `zones.py`, and `rank.py`: pure functions with no database, network, or filesystem coupling.
- `config/country_reserves.yaml` and `config/winwin_defaults.yaml`, including review state/date and “to confirm” fallbacks.

Tests:

- Port starter-kit goldens to `tests/golden/test_coastal_zoning_rules.py` without changing approved expected outputs merely to pass.
- Unit tests for `None` versus zero, NaN hazards, DEM gaps, sea-mask bounds, profile-specific ranking, map-grid-only zones, stars, legal-risk unknown, and deterministic partner pairing.
- Confirm South Sumatra ≥0.999 and Lamu ≥0.996 only after reproducing the fixture provenance.

Exit criterion: deterministic outputs reproduce approved kit results offline.

### Slice 2 — Persistent run model, permissions, and lifecycle API

Add SQLAlchemy models, likely in `core/coastal_zoning/models.py`, and one Alembic migration for:

- `coastal_zoning_run`
- `coastal_zoning_step`
- `coastal_zoning_zone`
- `coastal_zoning_artifact`
- `coastal_zoning_review_log`

Use UUIDv7 IDs consistent with the repository. Include `hub_id`, `owner_id`, idempotency key/request hash, lease/attempt fields, support reference, cancellation request, review state, immutable version pins, and timestamps. Keep receipt verdict out of the database.

Add `api/coastal_zoning.py` and register it in `api/main.py`:

- create/list/status/trace
- cancel/retry
- artifact metadata and authenticated downloads
- review and retire

Start with polling rather than SSE; polling already matches repository patterns and is easier to operate. Add SSE only after persistent event behavior is proven necessary.

Rules:

- Create returns `202`, `Location`, `Retry-After`, `run_id`, state, support reference, and `trace_id`.
- Require `Idempotency-Key` and reject key reuse with changed content.
- Every documented route declares `x-grp-access: protected`.
- CSRF applies to state-changing browser requests.
- Every transition writes an `AuditEvent`.
- Retiring hides artifacts but never deletes or invalidates platform receipts.

Exit criterion: offline fake runs can be queued, claimed, failed, retried, cancelled, listed, and authorized correctly.

### Slice 3 — AOI ingestion and coverage planning

Implement worker-safe validation in `core/coastal_zoning/aoi.py` and `coverage.py`:

- GeoJSON Polygon/MultiPolygon and zipped Shapefile only.
- Reuse or extract hardened ZIP validation from the existing browser-upload path.
- Enforce 10 MB compressed and approved uncompressed/file-count limits; reject links, path traversal, executable files, extra formats, and multi-layer ambiguity.
- Reproject only when CRS is explicit; reject missing/ambiguous Shapefile CRS rather than assuming WGS84.
- Repair only explicitly safe geometry defects; otherwise return a precise validation error.
- Record original and normalized geometry hashes.
- Simplify over 5,000 vertices with a measured area-difference notice and retain the original private upload artifact if retention permits.
- Calculate geodesic area, tile estimate, coastal intersection, scale, country, layer coverage, gaps, and defaults server-side. Client checks are advisory only.

Place search must proxy a bounded SIG resolver result through the API and return only the fields needed by the UI. Coverage must fail closed if capabilities are stale or unavailable.

Exit criterion: adversarial upload and AOI-limit tests pass; coverage returns deterministic declarations from captured fixtures.

### Slice 4 — Worker orchestration, checkpoints, and trace

Add `core/coastal_zoning/jobs.py`, `pipeline.py`, and `tracing.py`; extend `worker/main.py` to claim one coastal-zoning job through the existing database lease pattern.

Implement P1–P10 as named, checkpointed steps. Each step:

- claims/renews a lease;
- checks cancellation between bounded work units;
- writes immutable outputs before marking completion;
- records duration on success and failure;
- records summary, attempts, cache hits, and safe external-call metadata;
- can be resumed without overwriting different bytes.

Do not store all detailed progress in a short text column. Keep the user summary bounded and place structured detail in JSON/artifact trace data. Ensure a worker crash leaves the job reclaimable after lease expiry.

Save trace JSON as an artifact and integrate metadata-only Langfuse spans. Tracing failure must never fail the zoning run. User AOI names and uploaded text must not become executable trace content.

Exit criterion: forced crashes at each step resume safely, cancellation is bounded, and trace duration exists on both success and failure.

### Slice 5 — SIG tile pull, cache, mosaic, and zoning

Add:

- `sig_client.py`: strict API-side adapter around the existing `SigMcpClient`, with retries,
  redaction, timeouts, delegated-session ownership, and no token persistence.
- `tiles.py`: bounded tile planner and 4–6-way concurrency only if approved by SIG; begin lower in staging.
- `cache.py`: immutable cache key containing stack, years, ordered layers, normalized bbox, layer versions, and contract version.
- `mosaic.py`: decode and align grids, preserve unknown masks, and compare mangrove area against a whole-AOI pack.
- `pipeline.py` P3–P6 integration.

A cache hit must still verify the artifact checksum and pinned layer versions. A mismatch, missing layer, invalid grid, >5% mosaic discrepancy, or invalid sea mask fails or declares the documented gap; it never silently substitutes data.

Exit criterion: captured packs reproduce offline mosaics and zones; staging smoke test uses a deliberately small AOI and records rate/cost behavior.

### Slice 6 — Per-zone evidence, AI briefs, receipts, and ranking

Add `evidence.py`, `briefs.py`, `prompts/brief_v1.md`, and final ranking integration:

- Assemble one full-resolution pack for each candidate ranked zone.
- Build citation maps by source content/identity, never array position.
- Draft only the brief through the existing AI gateway, reserving and finalizing the user's allowance consistently with current AI calls.
- Keep arithmetic, notes, stars, ranks, and partner selection deterministic.
- Call `publish_answer`; retain its full safe trace and IDs.
- Retry at most twice with targeted gate feedback.
- If the gate remains blocked, preserve the polygon as an unranked “Map-grid estimate” and store the decline cause.
- If AI is disabled/unavailable, complete deterministic mapping but leave all ungated candidates unranked; never fabricate receipts.

Do not persist a receipt “passed” flag. Store IDs only and resolve verdicts at report view time through a bounded server-side resolver proxy with an unverified fallback.

Exit criterion: blocked, timed-out, allowance-exhausted, malformed, and successful fixture paths all preserve honest output.

### Slice 7 — Packaging and authenticated artifacts

Add `shapefiles.py` and `atlas.py`:

- Generate `sites.json`, `codes.png`, GeoTIFF/GeoJSON only if approved, Shapefile groups, README, and a manifest containing version pins, byte lengths, MIME types, and SHA-256 hashes.
- Use an appropriate local UTM/metric CRS for areas and include WGS84 `.prj` or documented CRS per output contract.
- Validate `.shp/.shx/.dbf/.prj/.cpg` completeness.
- Verify `codes.png` red channel against the zone raster.
- Publish artifacts under immutable generated storage keys.
- Stream downloads through authorized API routes; never reveal filesystem paths or `file://` URLs.

Exit criterion: package contract tests pass and unauthorized/cross-Hub downloads return 404.

### Slice 8 — Static web MVP

Use the repository's existing static frontend rather than introducing React:

- `web/coastal-zoning.html`, `.js`, `.css` for list/new/run/report states, or separate pages if accessibility is clearer.
- Add navigation through the shared `grp-common.js` top bar/menu.
- Reuse Leaflet 1.9.4 and existing GRP CSS tokens.
- Wizard: place/draw/upload, server coverage, declared gaps, source-labelled defaults, ADJUSTED changes, review, submit.
- Progress: poll every three seconds, display P1–P10, retry/cancel, and “you may leave this page.”
- Report: zoning, win-win, resort, and mangrove tabs; layer toggles; accessible popups; partner lines; downloads; draft/reviewed banner; trace panel.
- Receipt status: request a server-side view-time resolution. Initial and failure state is unverified. Reserve success color only for resolver-confirmed state.
- Every report states: “A zone is a place to look, not a place you may build.”

Do not load `sites.json` or artifacts directly before authorization. Avoid putting sensitive geometry in query strings; deep links use the run ID and hash only.

Exit criterion: keyboard, phone, desktop, light/dark, no-horizontal-scroll, and fail-closed receipt checks pass in a real signed-in browser.

### Slice 9 — Review flow and pilots

Implement Hub-scoped review with field allowlists:

- Reviewers may edit only zone display names, approved note fields, and legal rows.
- Every edit stores old/new values, reviewer ID, role, timestamp, and support reference.
- Edits are labelled ADJUSTED and never mutate deterministic evidence, geometry, rank inputs, pack IDs, or receipt IDs.
- Reviewed status identifies the role by default, not a person's name.

Run pilots in order: smallest approved fixture, Demak, South Sumatra, then Lamu. For each, retain manifests and trace artifacts, record duration/tile count/cache behavior/tokens/cost, resolve every ranked receipt, and obtain domain/legal review.

Exit criterion: the specification's definition of done is met for Demak and the two reference runs without changing scientific goldens.

## 5. Proposed API contract

Use these repository-native paths:

- `GET /api/v1/coastal-zoning/places?q=`
- `POST /api/v1/coastal-zoning/coverage`
- `POST /api/v1/coastal-zoning/runs`
- `GET /api/v1/coastal-zoning/runs`
- `GET /api/v1/coastal-zoning/runs/{run_id}`
- `GET /api/v1/coastal-zoning/runs/{run_id}/trace`
- `POST /api/v1/coastal-zoning/runs/{run_id}/retry`
- `POST /api/v1/coastal-zoning/runs/{run_id}/cancel`
- `POST /api/v1/coastal-zoning/runs/{run_id}/review`
- `POST /api/v1/coastal-zoning/runs/{run_id}/retire`
- `GET /api/v1/coastal-zoning/runs/{run_id}/sites.json`
- `GET /api/v1/coastal-zoning/runs/{run_id}/codes.png`
- `GET /api/v1/coastal-zoning/runs/{run_id}/files/{group}.zip`
- `GET /api/v1/coastal-zoning/receipts/{receipt_id}` as an authorized, bounded view-time resolver proxy if direct browser resolution cannot satisfy CORS/security requirements.

All responses include `trace_id` and errors use existing GRP error envelopes/support references. Binary responses expose `X-Trace-ID` rather than changing their body.

## 6. Configuration and deployment changes

Add disabled-by-default settings with safe bounds, including:

- `COASTAL_ZONING_ENABLED=false`
- delegated-user MCP checkpoint timeout and sign-in/retry bounds
- AOI/tile/upload/run limits
- artifact retention and cache retention
- per-run remote concurrency
- resolver base URL, preferably derived from an approved SIG base configuration rather than hard-coded

Update `.env.example`, Desktop and Ubuntu Compose wiring, entrypoint secret-copy allowlists, deployment tests, and runbooks. The worker needs outbound access to approved SIG/model hosts and adequate disk-backed scratch space; the API must not gain GIS execution. Run Alembic separately during deployment.

## 7. Test matrix

- **Fast:** pure rules, masks, ranking, legal fallbacks, AOI limits, state transitions, idempotency, permission matrix, receipt default state, trace failure isolation.
- **Contract:** OpenAPI access labels, SIG fixtures, `sites.json` schema, pack parser, artifacts, MIME/disposition headers, checksums, route 404 behavior, no contribution tools.
- **Golden:** approved South Sumatra and Lamu outputs; changes require scientific approval.
- **Integration:** PostgreSQL lease/reclaim, worker restart, storage immutability, cancellation, retry from checkpoint, AI allowance, mocked SIG/model/resolver.
- **Browser:** wizard, progress polling, four report tabs, review, download, receipt fail-closed behavior at 1400×900 and 390×844 in light/dark modes.
- **Live:** opt-in staging only, bounded AOIs and credentials; no automatic public receipts or contributions.
- **Load:** quota enforcement, one active run per user, global worker cap, tile concurrency, large artifact streaming, and cache contention.

Always run at minimum:

```bash
python -m pytest
python -m ruff check .
git diff --check
docker compose --env-file .env -f deploy/compose.yml config
```

## 8. Security and governance checklist

- No raw upload, token, prompt secret, or private source bytes in Git, logs, traces, or errors.
- No GIS in API requests.
- No `contribute_*`, risk-weight mutation, or automatic public publication.
- No cross-Hub existence disclosure.
- No persisted verdict flag or client-created success state.
- No numbers in ranked cards unless receipt-bound; derived values say “about”; other values say “Map-grid estimate.”
- No legal assertion from an unreviewed config row.
- No place/town generated by the model.
- No overwrite of immutable artifacts or completed scientific outputs.
- Receipts outlive retirement and cleanup.

## 9. Recommended issue order

1. Alignment ADR and asset/licence intake.
2. Starter-kit rules plus goldens.
3. Run schema, migration, lifecycle, and permissions.
4. AOI upload/normalization and coverage contracts.
5. Worker checkpoints, cancellation, and trace.
6. Delegated MCP coordinator and strict client fixtures.
7. Tiles/cache/mosaic/zoning.
8. Evidence/brief/gate/ranking.
9. Packaging and authenticated download routes.
10. Wizard/list/progress UI.
11. Atlas/report and view-time receipts.
12. Review/audit flow.
13. Staging pilot traces and tuning.
14. Deployment/runbook/operational acceptance.

## 10. Implementation status — 23 October 2026

The map-grid MVP now completes the primary signed-in workflow for explicitly bounded Lamu and
South Sumatra profiles: map drawing, strict AOI validation, live delegated-user coverage,
immutable pack storage, worker-side alignment and pinned zoning rules, persistent P1–P10 progress,
and a reopenable four-view report. Live Docker runs completed for both profiles. Candidates with
no receipt remain unranked; P7–P9 are visibly skipped, gaps are preserved, and reports are labelled
map-grid estimates. Hub/platform admin review and retirement are audit-logged. Leaflet is vendored
rather than fetched as executable code at runtime.

The remaining critical path is **governed zone-level publish/receipt contracts, full-resolution
raster execution, and package/download contracts + approved fixture/licence use**. The current MVP
does not claim those capabilities: it does not mint receipts, rank receiptless zones, or package
the five shapefile groups. It reuses existing MCP authentication and fails closed to
sign-in-and-retry after token loss; a separate service credential is not required.
