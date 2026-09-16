# GRP MVP 1 Project Handover

**Updated:** 16 September 2026 (Increment 2 complete, Planner chat and map, Increment 1 built on the synthetic case; all awaiting browser acceptance)

**Repository:** <https://github.com/kovitad/ADPC_GRP>

**Branches (stacked, merge in this order after acceptance):** `feat/increment-2-complete` → `feat/planner-chat-map` → `feat/increment-1-assessment`. `main` holds Phases A and B. `experiment/planning-chat` is superseded by `feat/planner-chat-map` and must not be merged.

**Baseline:** `GRP-ARC-001` v2.2 plus product-owner scope change of 16 Sep: Increment 2 also delivers the Section 10 AI usage limit, AI gateway and Langfuse (spec places them in Increment 6).

## Current position

Increment 0 is complete. **Increment 1 is built on the synthetic case** (see below). **Increment 2 is complete in code** on `feat/increment-2-complete` (all four roles, Hub administration, security log, AI usage limit with automatic and manual reset, AI gateway, Langfuse). It still needs your browser acceptance test and the DEP-01 SIG app registration. The Alpha gate still needs the signed Chiang Yuen golden case (DEP-04) and Increment 3 (SIG connection).

| Area | Current state on `main` |
|---|---|
| Sign-in | SERVIR OIDC/PKCE, ID-token checks (issuer, audience, signature, expiry, nonce, verified email). Uses an interim dynamically registered MCP client; see [ADR-0002](docs/adr/0002-interim-sig-mcp-client-login.md) |
| Linking | Matches Section 9.2: only a pre-added email links; otherwise denied, logged, nothing created |
| Sessions | Signed HttpOnly cookie, 60 min idle / 12 h max, membership reloaded every request. **New:** CSRF token on every state change; sign-out and any role/access change end the person's sessions on the server (`app_user.sessions_valid_after`) |
| Hub administration | Platform Admin and Hub Admin member list, add, role change, enable/disable; last-Admin guard with row lock; audited changes; setup CLI (`bootstrap-platform-admin`, `ensure-hub`, `assign-member`) |
| Errors | **New:** Appendix D format `{error: {code, message, support_ref}}` on sessions and admin routes; other-Hub and unknown items return 404 |
| Roles (branch) | All four Section 9.3 roles: Planner, Hub Admin, Platform Admin, SIG service. Permission matrix test covers every route for every role (61 cases) |
| Platform Admin (branch) | `/platform.html`: system health, AI usage setting, test AI call, per-person usage with **Reset now**, create/close/reopen Hubs, full security log |
| AI usage limit (branch) | Section 10: one limit per person per month, row-locked reservation, automatic reset 00:00 Bangkok on the 1st, stale reservations released by worker each minute, Section 10.6 messages. Manual current-month reset by Platform Admin, logged ([ADR-0003](docs/adr/0003-manual-ai-allowance-reset.md)) |
| AI gateway (branch) | `api/ai_gateway.py` is the only provider caller (OpenAI Responses, key file `AI_KEY_FILE_ADPC`, `store=false`). Only a Platform Admin test call uses it; no chat on `main` |
| Langfuse (branch) | `api/langfuse.py` sends model, prompt version, token counts, outcome, Hub code and a hashed person reference to Langfuse Cloud. No prompts, answers or emails. Best effort; the database is the record |
| SIG service login (branch) | Hashed bearer token (`python -m grp.admin rotate-sig-token --hash-file ...`), optional IP allowlist, 30 reads/min; evidence endpoint returns 404 until Increment 3 |
| Database | Migrations `0001` (access), `0002` (session revocation), `0003` (AI usage: `ai_usage_setting`, `ai_allowance`, `llm_usage`; branch). 8 of 16 spec tables exist |
| Rate limits | **Phase B:** 60 API requests per person per minute, in process memory (`api/rate_limits.py`); returns 429 `RATE_LIMITED`. Must move to a shared store before a second API worker |
| Local run | **New:** `.\scripts\docker-desktop.ps1 -AdminEmail <email>` starts PostGIS, migrations, API with web screens, and worker shell in Docker Desktop at `http://127.0.0.1:8000`. Verified 16 Sep: both migrations apply on PostgreSQL 16/PostGIS 3.4, pages load, `/api/v1/me` returns Appendix D 401, sign-in redirects to SERVIR |
| Tests | 155 offline tests on the branch (72 on `main`), Ruff clean. Session security (CSRF, revocation, sign-out replay); **Phase B:** full permission matrix through real sessions (`tests/contract/test_permission_matrix.py`), ID-token rejection cases (`tests/fast/test_oidc_rejections.py`), identity-link rules |

## Work done on 16 September

Commits:

| Commit | Branch | What |
|---|---|---|
| `ff084c7` | experiment | Snapshot of the uncommitted chat prototype, preserved as-is |
| `3f3db5c` | main | Hub administration plus review fixes #6 to #8 (CSRF, session revocation, 404 and Appendix D errors) |
| `3e0fe24` | experiment | Merge of main; public SIG receipts now opt-in only; Platform Admin without membership blocked from SIG evidence |
| `3e8f91f` | main | ADR-0002 and this handover |
| `7ebc57e` | main | Phase B: rate limit, identity merge fix, permission matrix and sign-in tests |
| `2da45d9` | main | Remove self-service pending access list |
| `e9f3357` | main | Docker Desktop stack, README and this handover |
| `0672b47` | feat/increment-2-complete | Complete Increment 2: roles, SIG service login, Hub close, security log views, AI usage limit, manual reset, AI gateway, Langfuse, platform page |
| (this commit) | feat/increment-2-complete | Handover update |

## What you can see today

Start Docker Desktop, check out `feat/increment-2-complete`, then run:

```powershell
.\scripts\docker-desktop.ps1 -AdminEmail kovitad.janlakhon@adpc.net -HubAdminEmail kovitad.janlakhon@adpc.net
```

The script copies `OPENAI_API_KEY` and `LANGFUSE_SECRET_KEY` from the ignored `.env` into ignored secret files and turns the AI build switch on for this local stack only.

| Page | What to check |
|---|---|
| `http://127.0.0.1:8000/admin` | Sign in with SERVIR |
| `http://127.0.0.1:8000/workspace.html` | Memberships, **My AI allowance** card, **Members and access**, **Hub security log**, Sign out button |
| `http://127.0.0.1:8000/platform.html` | System health; set token limit and AI on; **Send test call**; usage per person and **Reset now**; create, close and reopen a Hub; full security log |
| Langfuse Cloud project | Trace `grp-ai-call` with model and token counts after a test call |

Acceptance checklist for the browser test:

- [ ] Sign in and sign out work; after sign-out `/workspace.html` sends you back to sign-in
- [ ] AI card shows "AI features are turned off" before the limit is set
- [ ] Setting limit and AI on changes the card to "AI allowance: … tokens left"
- [ ] Test call returns a reply and token counts; usage table and Langfuse show it
- [ ] Reset now returns usage to 0 and adds `ai allowance reset` to the security log
- [ ] Closing a test Hub and reopening it are logged

Not visible yet: assessments, maps, results, downloads, SIG sharing. Those are Increments 1, 3, 4 and 5.

## Code review findings (16 September)

Reviewed against `GRP-ARC-001` v2.2.

| # | Finding | Status |
|---|---|---|
| 1 | Sign-in requests a token addressed to SIG's MCP resource via self-registered client (Sections 9.1, 9.6) | Open, recorded as interim exception in ADR-0002; needs DEP-01 |
| 2 | Chat issued a public SIG receipt on every flood question (Checklist I.2, Section 15.4) | Fixed on experiment branch: `publish_receipt` must be explicitly true |
| 3 | Chat calls `assemble_pack` by free-text place with no area-match check (AD-03; the Ku Thong fallback-box failure) | Open, experiment only. Do not reuse this path in product code |
| 4 | Platform Admin without Hub membership could run the SIG path (Section 9.4) | Fixed on experiment branch, with test |
| 5 | Chat bypasses `AI_FEATURE_ENABLED`, allowance, usage records and per-Hub key (Section 7.5, AI-12/13) | Open, experiment only; ADR-0001 remains Proposed |
| 6 | No CSRF protection (Section 13.1) | Fixed on main |
| 7 | No new session after role change; sign-out left a copied cookie valid (Section 9.1) | Fixed on main |
| 8 | 403/400 instead of 404 for other Hubs; errors not in Appendix D format | Fixed for sessions and admin routes; apply to every new route |
| 9 | No rate limits (settings exist, not enforced) | Fixed for the per-person API limit; assessment, SIG evidence and AI limits land with those routes |
| 10 | Pending-request list scans the whole audit log and lists any SERVIR account; spec has no self sign-up queue | Fixed: route and UI removed (owner decision, 16 Sep). Admins add people by work email; server command `list-access-requests` stays as a support fallback |
| 11 | In-memory MCP token store is unbounded | Experiment only |
| 12 | No permission-matrix, cross-Hub contract, or full Section 15.3 sign-in tests | Fixed for existing routes: 30-case matrix, wrong audience/issuer/nonce/key/expiry, unverified email, userinfo subject mismatch, email change, disabled user |
| 13 | A second SERVIR login with the same email was linked to an already linked person (Section 9.2: never merge by email) | Fixed in `core/identity.py`, with test |
| 14 | Access message said "Open the GRP address" instead of the address (Section 9.5) | Fixed |

Not yet covered by tests: two different logins linking the same person at the same instant (needs PostgreSQL), the SERVIR outage message, and "no token or cookie in logs" (needs log capture). Known limits of the Phase A fixes: sign-out is still a GET link and ends the person's sessions on all devices; migrations upgrade cleanly on PostgreSQL in Docker Desktop, but downgrade is not tested.

## Experiment branch rules

`experiment/planning-chat` holds the local chat (`/planning.html`, `api/ai.py`, `api/mcp_client.py`, `api/openai_gateway.py`, `api/token_store.py`, ADR-0001). It passes 40 offline tests. It must not be merged into `main`: general chat, token storage and place-name pack calls conflict with the spec. Keep it `GRP_ENV=dev` only, never enable receipt publishing with private data, and keep the OpenAI key out of Git and logs. Revisit it in Increment 6, rebuilt to explain a stored GRP result.

## Architecture guardrails

- The GIS worker is the only calculator. Screens, SIG, downloads, and AI read the same locked result.
- Every assessment is a background job with pinned boundary, dataset, method, and SHA-256 fingerprints.
- Stop safely with typed errors. Never substitute a fallback area, dataset, route, or provider.
- SERVIR sign-in proves identity; GRP membership decides Hub and role.
- Nothing goes to SIG unless an Admin shares it. Receipts are issued by hand during acceptance only.
- AI explains stored results only and stays off until Increment 6 is accepted.

Any change to these rules needs an ADR and the approvals in Section 17.

## Planning map workspace (branch `feat/planning-map-workspace`, on top of Increment 1)

Owner decisions 16 Sep: OpenStreetMap (no Google), vulnerable people as a placeholder, build this before Increment 4.

- `/planning.html`: chat on the left; OSM map on the right. Click a district to select it, choose the scenario, **Run assessment**
- Layer panel: district outlines, flood depth (5 depth classes plus No data, legend), evacuation centers (white = not assessed yet, then orange / green / grey by result), **Vulnerable people** switched off with the note "Not available yet … Increment 6 (DEP-07)"
- Chat switch: **This result** uses `POST /assessments/{id}/explain` (AI gets only stored result fields, Section 10.5; counts tokens, Langfuse). **General or SIG evidence** uses the ADR-0004 chat
- New API: `GET /maps/layers`, `GET /maps/hazard/{id}/overlay.png`, `GET /maps/datasets/{id}/features`
- The flood picture is drawn next to the data at seed time and served as a stored file. The API never reads rasters (AD-03), and the pinned fingerprint is unchanged
- Tests: `tests/golden/test_planning_map.py` (layers, PNG, GeoJSON, access, explain prompt contains no emails, keys or file links). 189 tests pass
- Verified in Docker 16 Sep: overlay stored with bounds `[[14.99, 100.0], [15.11, 100.12]]`, pages load; browser test pending

Browser test: sign in → **Planning** → the synthetic district is preselected → **Run assessment** → dots turn coloured and totals show 7/3/2/2 → chat switches to **This result** → ask "Which centers could not be assessed, and why?"

## Increment 1 status (branch `feat/increment-1-assessment`)

Built and tested on the **synthetic** RP100 case (risk R-02). The signed Chiang Yuen case
(DEP-04, DEP-06) is still missing; `tests/golden/chiang_yuen_rp100` stays empty on purpose.

| Part | State |
|---|---|
| Tables | Migration `20260916_0004`: `boundary`, `dataset`, `dataset_version`, `feature`, `method`, `assessment`, `assessment_feature`. 15 of 16 spec tables exist (`assessment_export` is Increment 4). Geometry is GeoJSON with SHA-256, not PostGIS columns yet |
| Storage | `core/storage.py` `LocalStorage`: generated keys, fingerprint on put, never overwrites different bytes, windowed raster open |
| Method | `core/gis.py` `center-flood-overlay` 1.0.0, status **draft**. In boundary only; one-pixel windowed read; NoData and outside coverage are `unable_to_assess`, never not exposed |
| Result rules | `core/result_rules.py` Section 8.4 checks before saving |
| API | `POST /assessments` (Section 8.2 order, pinned inputs, Idempotency-Key, 202 + Location + Retry-After, 10/hour), `GET /assessments`, `/{id}`, `/{id}/result`, `/{id}/centers`, `POST /{id}/cancel`, `GET /catalog/boundaries|datasets|methods`. Other Hubs 404. API never imports GIS libraries |
| Worker | `SKIP LOCKED` claim, 15-minute lease with expired-lease reclaim, membership and fingerprint recheck, locked result in one transaction, temporary-error retry up to 3, cancel wins over a running job. Disabling a member cancels their queued jobs |
| Golden test | `tests/golden/test_synthetic_rp100.py` compares the API result to hand-designed `expected_summary.json` and `expected_centers.csv` exactly, plus stop-safely, idempotency, cancel and cross-Hub tests. CI installs the `gis` extra |
| Screen | `/assessments.html`: choose area, scenario, centers (platform vs saved local), method; watch job; totals, map by status, center table with reason meaning, trust labels, sources, gaps, limits; recent jobs with cancel. Yellow SYNTHETIC banner |
| Verified 16 Sep | 184 offline tests pass; on Docker Desktop PostgreSQL the worker claimed a queued job and saved 7 in scope, 3 exposed, 2 not exposed, 2 unable, 1 excluded — equal to the golden file. That check left one local job with support ref `GRP-E2E-CHK` |

Synthetic design: 7 centers in a 0.15° × 0.1° box near lon 100.0–100.15, lat 15.0–15.1. The flood depth is 1.2 m and 0.6 m in the west and 0 m in the east. There is one NoData patch, the raster stops at lon 100.12, and one center sits outside the district. It is not a real place or scientific data.

Remaining for Increment 1 acceptance:

- [ ] DEP-04 and DEP-06: signed Chiang Yuen boundary, flood layer, centers, method approval and expected result. Then add `tests/golden/chiang_yuen_rp100` and a real seed
- [ ] Method approval (`status: approved`); drafts run only where `ALLOW_DRAFT_METHODS=true` (Docker Desktop)
- [ ] PostGIS geometry columns and a boundary loader for real admin data
- [ ] Lease renewal for long jobs (current jobs finish in well under a minute)
- [ ] PostgreSQL CI job for migrations and two workers claiming at once

Browser test for Increment 1 (Docker Desktop):

1. Sign in at `http://127.0.0.1:8000/admin`, open **Assessments**
2. Keep Synthetic Test District, RP100, Synthetic evacuation centers, center-flood-overlay 1.0.0 (draft) → **Run assessment**
3. Within a few seconds the state becomes `succeeded`: totals 7 / 3 / 2 / 2, map with orange, green and grey dots, and a table with reasons
4. Check the yellow SYNTHETIC banner, "Scientifically approved: no", and the Sources, gaps and limits section
5. Run again and cancel it quickly from Recent assessments (may already be finished)

## Known gaps after Increment 2

- Browser acceptance not yet done; a live OpenAI call and a Langfuse trace have not been verified by the team
- DEP-01: sign-in still uses the interim SIG MCP client (ADR-0002)
- ADR-0003 needs the AI-11 wording change in the next spec version
- The spec puts the AI gateway in Increment 6; only the Platform Admin test call exists. AI explain for results waits for Increment 1 results
- Rate limits and the in-memory limiter are single-process only
- Concurrent reservation proven with sequential tests on SQLite; add a PostgreSQL two-connection test
- Hub Admin security log shows only events tagged with the Hub (member changes); sign-in events have no Hub

## Refined plan

**Phase B: Increment 2 security (done 16 September, except below)**
- Remaining: make sign-out a POST; PostgreSQL-backed test for concurrent linking; cancel queued jobs on disable once jobs exist

**Phase C: Increment 1, golden assessment (main work, 2 to 3 weeks)**
- Remaining tables and migrations, storage interface, Chiang Yuen seed, validation and result rules
- `POST /assessments` with idempotency and 202; PostgreSQL `SKIP LOCKED` queue; worker with 15-minute lease; locked result
- Golden test in CI (synthetic case until DEP-04 arrives); CI blocks merges on golden, migration, permission, contract and secret-scan failures

**Phase D: Increment 3, SIG connection**
- Sharing approval, evidence endpoint (rejects MCP-audience tokens), SIG machine login, contract tests, one receipt by hand

## Dependencies to chase this week

| ID | Needed | Owner | Blocks |
|---|---|---|---|
| DEP-01 | GRP registered as its own app in SIG WorkOS (Sandbox, staging, production) | SIG platform owner | Removing ADR-0002 exception; Beta |
| DEP-04, DEP-06 | Approved Chiang Yuen boundary, signed golden result, evacuation-center dataset | Scientific and Data Authority | Increment 1 acceptance |
| DEP-08, DEP-09, DEP-13 | Risk pack `assessment_ref`, SIG machine login and how it is issued | SIG platform owner | Increment 3 |

## Resume commands

```powershell
git pull --ff-only
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m ruff check .
python -m pytest
alembic upgrade head
docker compose --env-file .env -f deploy/compose.yml config
```

Read [`README.md`](README.md), [`AGENTS.md`](AGENTS.md), [`docs/access-management.md`](docs/access-management.md), and the secure copy of `GRP-ARC-001` v2.2 before changing application behavior.
