# GRP MVP 1 Project Handover

**Updated:** 17 September 2026

**Repository:** <https://github.com/kovitad/ADPC_GRP>

**Baseline:** `GRP-ARC-001` v2.2 (secure copy `2026-09-15_GRP-ARC-001_MVP1_Solution_Architecture_Specification_v2.2.docx`, ignored by Git), plus the product-owner decisions and ADRs below.

**Latest branch:** `feat/planning-chatbot-ux`. It contains everything below and is pushed to GitHub. Nothing after Phase B is merged into `main` yet.

---

## 1. Where we are

| Increment (spec Section 16) | State | Where |
|---|---|---|
| 0 Servers ready | Done | `main` |
| 1 Golden assessment | **Built on a synthetic case.** Job, worker, locked result, API, screen and golden test work. Acceptance still needs the signed Chiang Yuen data (DEP-04, DEP-06) and method approval | stacked branches |
| 2 Access and Admin | **Complete in code.** Four roles, Hub admin, security log, CSRF, session revocation, rate limits, AI usage limit, AI gateway, Langfuse | stacked branches (Phases A and B on `main`) |
| Planner chat and map (ADR-0004) | **Built, Docker Desktop only.** Chat bot plus searchable OSM map, flood layer, evacuation centers, natural-language run, explain and SIG evidence | stacked branches |
| 3 SIG connection | Not started. Needs DEP-01, DEP-08, DEP-09, DEP-13 | — |
| 4 Review and download | Not started (full result table exists; downloads do not) | — |
| 5 More data (7 scenarios, uploads) | Not started | — |
| 6 Vulnerability and AI explain | AI explain of a stored result **exists early**; vulnerability is a placeholder (DEP-07) | stacked branches |
| 7 Pilot hardening | Not started | — |

**Nothing has been accepted in a browser by the product owner yet.** The last session stopped during browser testing: Docker needed a restart and the owner asked for this handover first.

---

## 2. Branches (stacked; merge in this order after acceptance)

| # | Branch | Adds |
|---|---|---|
| — | `main` | Increment 0, access foundation, Phase A (CSRF, session revocation, 404/Appendix D errors), Phase B (rate limit, permission matrix, sign-in tests), pending list removed, Docker Desktop stack |
| 1 | `feat/increment-2-complete` | Roles, SIG service login, Hub close/reopen, security log views, AI usage limit, manual reset (ADR-0003), AI gateway, Langfuse, `/platform.html` |
| 2 | `feat/planner-chat-map` | ADR-0004 chat on SIG generic evidence with area check and opt-in receipts |
| 3 | `feat/increment-1-assessment` | Assessment tables, storage, method, worker, API, synthetic seed and golden test, `/assessments.html` |
| 4 | `feat/planning-map-workspace` | Map layers API, flood overlay picture, center points, result explain API |
| 5 | `feat/planning-chatbot-ux` | Natural chat routing (run, explain, SIG, chat), chat-bot redesign, map search, Thai place names |

Each branch contains the ones above it, so merging branch 5 into `main` brings in all of them. Merging one at a time keeps review smaller. `experiment/planning-chat` is an old prototype, superseded by branch 2. **Do not merge it.**

---

## 3. How to run and test (Docker Desktop)

```powershell
# start (or rebuild after code changes)
.\scripts\docker-desktop.ps1 -AdminEmail kovitad.janlakhon@adpc.net -HubAdminEmail kovitad.janlakhon@adpc.net
# stop (data kept in Docker volumes)
.\scripts\docker-desktop.ps1 -Down
```

The script:
- creates ignored secrets under `.local/docker/secrets`;
- copies `OPENAI_API_KEY` and `LANGFUSE_SECRET_KEY` from the ignored `.env` into secret files without printing them;
- reuses the localhost SIG client from `.local/servir_auth_client_id`, then builds and starts `db`, `migrate`, `api` and `worker`;
- seeds the synthetic RP100 case and makes the given emails Platform Admin and Hub Admin of `adpc`.

**Known issue on this PC:** a full rebuild can take more than 10 minutes and was twice stopped for low memory. If only Python code changed, use:

```powershell
$env:SERVIR_AUTH_CLIENT_ID = (Get-Content .local\servir_auth_client_id -Raw).Trim()
docker compose -f deploy/compose.desktop.yml up -d --build api worker
```

Web files are mounted from disk, so HTML, JS and CSS changes need only a browser refresh. **API changes need an image rebuild.** A stale API image caused the old "Enter a Thailand district in the area box" reply on 17 Sep. After any API or worker restart, **sign in again**. The SIG MCP token is kept only in process memory (ADR-0002).

### Browser test checklist

1. `http://127.0.0.1:8000/admin`: sign in with SERVIR
2. `/platform.html`: set a token limit (for example 50,000), AI **On**, Save; **Send test call**; usage table and **Reset now**; create, close and reopen a test Hub; full security log
3. `/workspace.html`: memberships, **My AI allowance**, members and access, Hub security log, Sign out
4. `/planning.html`:
   - **Where could people move?**: the result card shows 7 / 3 / 2 / 2 and dots turn orange, green and grey
   - "Which centers could not be assessed, and why?"
   - "Which schools and hospitals in Chiang Yuen, Maha Sarakham are exposed to flooding?" (or in Thai): SIG evidence, or a "stopped safely" reply if SIG did not use the admin boundary
   - **Publish public SIG receipt** (two-step confirm): receipt link and SIG hazard map
   - map search "Nan", **Layers** toggles
5. `/assessments.html`: run the synthetic case; totals, table, sources, gaps and limits
6. Langfuse Cloud: traces `platform-test-v1`, `planning-router-v1`, `planning-draft-v1`, `result-explain-v1`

---

## 4. What is built

### 4.1 Access, roles, sessions (Sections 9, 13)
- **Sign-in:** SERVIR OIDC/PKCE with ID-token checks (issuer, audience, signature, expiry, nonce, verified email). It uses the interim self-registered MCP client (ADR-0002).
- **Linking:** follows Section 9.2. Only a pre-added email links, a second login with the same email is never merged, and the email stays the same after later changes.
- **Four roles:** Planner and Hub Admin per Hub, Platform Admin flag, SIG service machine login (hashed bearer token, optional IP allowlist, `python -m grp.admin rotate-sig-token --hash-file …`).
- **Sessions:**
  - signed HttpOnly cookie; 60 minutes idle, 12 hours maximum;
  - membership reloaded on every request;
  - CSRF header on every state change;
  - POST sign-out, and any role or access change, revoke sessions server-side (`app_user.sessions_valid_after`).
- **Errors:** Appendix D format; other-Hub and unknown items return 404.
- **Rate limits (in process memory):** 60 requests per minute per person, 10 assessments per hour, 20 AI requests per hour, 30 SIG reads per minute.
- **Hub admin:** add by work email, change role, turn access on or off, last-Admin guard, access message with the GRP address. Disabling a member cancels their queued jobs.
- **Platform Admin:** create, close and reopen Hubs, full security log, system health.

### 4.2 AI usage limit, gateway, Langfuse (Section 10, ADR-0003)
- **Tables:** `ai_usage_setting`, `ai_allowance`, `llm_usage` (migration `0003`).
- **Limit:** one limit per person per Bangkok month. A row-locked reservation means two requests at once cannot both pass. Automatic reset at 00:00 Bangkok on the 1st. The worker releases stale reservations every minute. Section 10.6 messages are used.
- **Manual reset (ADR-0003):** a Platform Admin can reset one person's usage for the current month. It is logged, and the history is kept.
- **Gateway:** `api/ai_gateway.py` is the only code that calls a provider (OpenAI Responses, `store=false`, key file `AI_KEY_FILE_ADPC`).
- **Langfuse:** `api/langfuse.py` sends metadata and token counts only, with a hashed person reference. It is best effort.

### 4.3 Flood assessment (Increment 1, Sections 7, 8, 12, 15)
- **Tables:** `boundary`, `dataset`, `dataset_version`, `feature`, `method`, `assessment`, `assessment_feature` (migration `0004`). Geometry is GeoJSON with SHA-256.
- **Storage:** `core/storage.py` `LocalStorage` uses generated keys, never overwrites different bytes, and opens rasters for windowed reads.
- **Method:** `core/gis.py` `center-flood-overlay` 1.0.0, status **draft**. NoData and outside coverage give `unable_to_assess`, never not exposed.
- **API:**
  - `POST /assessments` (Section 8.2 order, pinned inputs, Idempotency-Key, 202);
  - status, result, paged centers, cancel, list;
  - `GET /catalog/boundaries|datasets|methods`.
  - The API never imports GIS libraries.
- **Worker:**
  - claims with `SKIP LOCKED` and a 15-minute lease, reclaiming expired leases;
  - rechecks membership and fingerprints;
  - writes the locked result in one transaction;
  - retries temporary errors up to 3 times;
  - a cancel that lands while the job runs wins.
- **Synthetic seed:** `python -m grp.seed synthetic-rp100`. Invented, clearly labelled data (7 in-scope centers, 1 outside, NoData patch, partial raster coverage).
- **Golden test:** `tests/golden/test_synthetic_rp100.py` compares against the hand-designed `tests/golden/synthetic_rp100/expected_*`. **The Chiang Yuen folder stays empty on purpose.**
- **Verified on Docker PostgreSQL (16 Sep):** 7 / 3 / 2 / 2 / 1 excluded, equal to the golden file. That check left one local job with support ref `GRP-E2E-CHK`.

### 4.4 Map and Planner assistant (ADR-0004, Docker Desktop only)
- **Map API:**
  - `GET /maps/layers`;
  - `GET /maps/hazard/{id}/overlay.png`: a display-only flood picture drawn at seed time and stored as a file, so the API never reads rasters and the pinned fingerprint is unchanged;
  - `GET /maps/datasets/{id}/features`.
- **Explain:** `POST /assessments/{id}/explain`. The AI gets only stored result fields (Section 10.5).
- **Chat:** `POST /planning/chat` and `GET /planning/status`, enabled only when `PLANNING_CHAT_ENABLED=true` **and** `GRP_ENV=dev`.
  - The model proposes one of `chat`, `explain_result`, `run_assessment`, `sig_flood`, `cannot` and extracts `place` (English romanized, including from Thai input) and `return_period_years`.
  - `run_assessment` matches supported areas or the map selection, picks current data and starts the job.
  - `sig_flood` runs `assemble_pack`, then the area check (`aoi[...] via admin boundary` must match the requested district), then a gateway draft. `publish_answer` and `ui_embed` run only after a two-step Publish confirm, and a blocked draft is withheld.
  - Not-yet-available requests (vulnerable people, investment brief, red/yellow/green map) get a server-written reply.
- **Screen `/planning.html` (with `planning.css`):**
  - chat-bot pane with the owner's opening question "What decision are you preparing for?", suggestions, bubbles, typing indicator, action chips, one composer (Enter to send), context chips and allowance pill;
  - OSM map with search (supported areas, then Nominatim places for orientation), floating layers panel (areas, flood depth legend, centers by status, vulnerable people placeholder), result card with progress, SIG map overlay;
  - Chat/Map tabs on mobile.
- **External browser calls:** openstreetmap.org tiles and Nominatim, and Leaflet from unpkg.com. Local testing only.

### 4.5 Tests and CI
- **193 offline tests pass;** Ruff is clean.
- **Coverage:** fast tests, contract permission matrix (every route × role), golden and stop-safely tests, planning chat with fake SIG and model, map layers, explain prompt privacy.
- **CI:** installs `.[dev,gis]`.
- **Not in CI:** a PostgreSQL migration job and a two-worker concurrency test.

---

## 5. Decisions and ADRs

| Record | Decision | Status |
|---|---|---|
| ADR-0001 | Local AI chat routing | Superseded by ADR-0004 (only on the experiment branch) |
| ADR-0002 | Interim SERVIR sign-in via a self-registered SIG MCP client; MCP token in memory only for local chat | Proposed; remove before Beta (DEP-01) |
| ADR-0003 | Platform Admin manual reset of current-month AI usage | Accepted by owner; spec AI-11 must change |
| ADR-0004 | Interim Planner chat and map on SIG generic evidence, Docker Desktop only | Accepted by owner for local testing; Technical Lead review pending |

Owner decisions on 16–17 Sep:
- remove the pending access list;
- Increment 2 also delivers the AI limit, gateway and Langfuse;
- OpenStreetMap, not Google Maps;
- vulnerable people as a placeholder;
- the combined Planning map before Increment 4;
- chat-bot style UX with the planner opening question.

---

## 6. Code review findings

| # | Finding | Status |
|---|---|---|
| 1 | Sign-in token addressed to SIG MCP (9.1, 9.6) | Open: ADR-0002, needs DEP-01 |
| 2 | Automatic public SIG receipts | Fixed: two-step opt-in |
| 3 | Place-name pack calls could use a fallback area | Fixed for chat: admin-boundary area check |
| 4 | Platform Admin without Hub could use SIG path | Fixed |
| 5 | Chat bypassed AI rules | Fixed: all calls through the gateway |
| 6–9 | CSRF, session revocation, 404/Appendix D, rate limits | Fixed |
| 10 | Pending access list | Removed |
| 11 | Unbounded token store | Bounded to 500 |
| 12 | Missing permission and sign-in tests | Fixed |
| 13 | Second login merged by email | Fixed |
| 14 | Access message lacked GRP address | Fixed |
| 15 | Centers fingerprint depended on row order | Fixed |
| 16 | API imported GIS libraries; image missing `libexpat1` | Fixed |
| 17 | Thai place names failed the English area check | Fixed: router returns romanized English names. Not yet verified against live SIG |

---

## 7. Known gaps and risks

- **Browser acceptance not done.** Live OpenAI, Langfuse and SIG MCP calls from this code have not been confirmed end to end.
- **Real data missing** (DEP-04, DEP-05, DEP-06). The only supported area is synthetic.
- **Method** is draft. `ALLOW_DRAFT_METHODS=true` only in Docker Desktop.
- **Geometry** is GeoJSON; PostGIS columns and a boundary loader are still needed.
- **Rate limits and the SIG token store** are single-process memory.
- **Leases** are not renewed for long jobs (current jobs take under a second).
- **Area check wording** (`via admin boundary`) is inferred from the 14 Sep live capture and may change on SIG's side.
- **Spec text** needs updates for ADR-0003, ADR-0004 and the Increment 2 scope change.
- **Docker Desktop on this PC** is memory-constrained; full rebuilds may be killed.

---

## 8. Dependencies to chase

| ID | Needed | Owner | Blocks |
|---|---|---|---|
| DEP-01 | GRP registered as its own app in SIG WorkOS | SIG platform owner | Removing ADR-0002; Beta |
| DEP-04, DEP-06 | Chiang Yuen boundary, center dataset, signed golden result | Scientific and Data Authority | Increment 1 acceptance |
| DEP-05 | JRC flood layers for seven return periods, licence | Scientific and Data Authority | Increment 5, real flood map |
| DEP-07 | Vulnerability layer and meaning | Scientific and Data Authority | Vulnerable people layer |
| DEP-08, DEP-09, DEP-13 | Risk pack `assessment_ref`, SIG machine login | SIG platform owner | Increment 3 |
| DEP-11 | AI key per Hub, starting token limit | Product Owner, Technical Lead | AI outside local testing |
| DEP-12 | Summary and map download templates | Product Owner with planners | Increment 4 |

---

## 9. Next steps

1. Restart Docker (`docker-desktop.ps1`), sign in, run the Section 3 checklist, and record the results here.
2. Fix anything found, then merge the stacked branches into `main` in order and push.
3. Next track:
   - **Increment 4:** job trace, summary PDF, map exports;
   - **Increment 3:** sharing approval, evidence endpoint, recorded SIG contract tests;
   - **Real-data readiness:** PostGIS geometry, boundary loader, PostgreSQL CI.
4. Send the DEP-01, DEP-04, DEP-05 and DEP-06 requests.

---

## 10. Key files

| Area | Files |
|---|---|
| Sessions and access | `api/sessions.py`, `api/auth.py`, `api/oidc.py`, `core/identity.py`, `api/permissions.py`, `api/planning_access.py` |
| Admin and platform | `api/admin.py`, `api/platform.py`, `api/audit.py`, `grp/admin.py` |
| AI | `core/ai_models.py`, `core/ai_allowance.py`, `api/ai_gateway.py`, `api/langfuse.py`, `api/ai.py` |
| Assessment | `core/assessment_models.py`, `core/assessment_jobs.py`, `core/gis.py`, `core/result_rules.py`, `core/storage.py`, `api/assessments.py`, `api/catalog.py`, `worker/main.py`, `grp/seed.py` |
| Map and planning | `api/maps.py`, `core/hazard_overlay.py`, `api/planning.py`, `api/sig_evidence.py`, `api/mcp_client.py`, `api/token_store.py` |
| Web | `web/planning.html/js/css`, `web/assessments.*`, `web/platform.*`, `web/workspace.*`, `web/grp-common.js` |
| Migrations | `migrations/versions/20260916_0001` … `0004` |
| Deployment | `deploy/compose.desktop.yml`, `scripts/docker-desktop.ps1`, `deploy/Dockerfile`, `deploy/compose.yml` (servers) |
| Tests | `tests/fast`, `tests/contract/test_permission_matrix.py`, `tests/golden` |

## Resume commands

```powershell
git fetch; git switch feat/planning-chatbot-ux
python -m venv .venv; .\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,gis]"
python -m ruff check .
python -m pytest
.\scripts\docker-desktop.ps1 -AdminEmail <you> -HubAdminEmail <you>
```

Read `README.md`, `AGENTS.md`, `docs/adr/` and the secure copy of `GRP-ARC-001` v2.2 before changing application behaviour.
