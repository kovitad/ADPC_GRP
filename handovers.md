# GRP MVP 1 Project Handover

**Updated:** 17 September 2026 (end of the Claude Code session; continue in Codex or any agent)

**Repository:** <https://github.com/kovitad/ADPC_GRP>

**Work branch:** `feat/planning-chatbot-ux`. It is pushed, contains all work, has a clean tree, **196 tests pass** and Ruff is clean.

**Baseline:** `GRP-ARC-001` v2.2. The secure copy `2026-09-15_GRP-ARC-001_MVP1_Solution_Architecture_Specification_v2.2.docx` is at the repo root and ignored by Git. On top of it sit the ADRs and product-owner decisions in Section 6.

> **Start here if you are a new agent:** read Sections 1, 3, 4 and 10, then `AGENTS.md`. Do not merge `experiment/planning-chat`. Do not store secrets, and do not print the `.env` values.

---

## 1. Where we are

| Area | State |
|---|---|
| Increment 0, servers ready | Done |
| Increment 2, access and admin | **Complete in code**: four roles, Hub admin, security log, CSRF, session revocation, rate limits, AI usage limit, AI gateway, Langfuse |
| Increment 1, golden assessment | **Built on a synthetic case**: job, worker, locked result, API, screen, golden test. Real acceptance needs DEP-04, DEP-06 and method approval |
| Planner assistant and map (ADR-0004) | **Built, Docker Desktop only**: chat bot plus OSM map, SIG MCP evidence, evidence panel, downloads, progress, Thai input |
| UI shell | Shared left-aligned top bar, SERVIR Global Collaborative logo, one palette from the logo |
| Increment 3, SIG connection | Not started (needs DEP-01, DEP-08, DEP-09, DEP-13) |
| Increment 4, review and downloads | Not started (the evidence downloads in chat are not the Increment 4 PDFs) |
| Increment 5, seven scenarios and uploads | Not started |
| Increment 6, vulnerability and AI explain | AI explain exists early; vulnerability is a placeholder (DEP-07) |
| Increment 7, pilot hardening | Not started |

**Product-owner browser testing is in progress.** The owner has seen and steered the Planning page (chat, SIG evidence, menu, theme). No branch has been formally accepted or merged after Phase B.

---

## 2. Branches

All feature branches are **stacked**: each contains the ones before it. `feat/planning-chatbot-ux` includes everything.

| # | Branch | Adds |
|---|---|---|
| — | `main` | Increment 0, access foundation, Phase A and B security fixes, Docker Desktop stack |
| 1 | `feat/increment-2-complete` | Roles, SIG service login, Hub close, security log views, AI limit, manual reset, AI gateway, Langfuse, `/platform.html` |
| 2 | `feat/planner-chat-map` | ADR-0004 chat on SIG evidence, area check, opt-in receipts |
| 3 | `feat/increment-1-assessment` | Assessment tables, storage, method, worker, API, synthetic seed and golden test, `/assessments.html` |
| 4 | `feat/planning-map-workspace` | Map layers API, flood overlay picture, center points, explain API |
| 5 | `feat/planning-chatbot-ux` | Natural chat routing, chat-bot UI, SIG evidence panel and downloads, progress and timings, Thai place names, state kept across pages, shared top bar, SERVIR logo and theme |

**Merge advice:** after the owner accepts, merge `feat/planning-chatbot-ux` into `main` (it brings in 1 to 4), push, and delete the stale branches. `experiment/planning-chat` is superseded; **never merge it**.

---

## 3. Run and test locally (Docker Desktop)

```powershell
# full start or rebuild (slow on this PC; was twice killed for low memory)
.\scripts\docker-desktop.ps1 -AdminEmail kovitad.janlakhon@adpc.net -HubAdminEmail kovitad.janlakhon@adpc.net

# faster: rebuild only API and worker after Python changes
$env:SERVIR_AUTH_CLIENT_ID = (Get-Content .local\servir_auth_client_id -Raw).Trim()
docker compose -f deploy/compose.desktop.yml up -d --build api worker

# stop (data stays in Docker volumes)
.\scripts\docker-desktop.ps1 -Down
```

**Important facts about the local stack:**
- `web/` is mounted from disk: HTML, JS and CSS changes need only a browser refresh. Pages are served with `Cache-Control: no-cache` in dev, and asset URLs carry `?v=20260917g`. **Bump that version when you change shared CSS or JS.**
- **Python changes need an image rebuild.** In this session several API files were copied straight into the running container (`docker compose cp` + `restart api`) to save memory. **The image `grp-api:desktop` is therefore older than the code. Rebuild `api` and `worker` before trusting a fresh container.**
- After any API restart, **sign in again**. The SIG MCP token lives only in process memory (ADR-0002).
- The script copies `OPENAI_API_KEY` and `LANGFUSE_SECRET_KEY` from the ignored `.env` into `.local/docker/secrets/` without printing them. `LANGFUSE_BASE_URL` and `LANGFUSE_PUBLIC_KEY` pass through as environment variables. The model comes from `OPENAI_MODEL` (currently `gpt-5.2`).
- Desktop-only switches in `deploy/compose.desktop.yml`: `GRP_ENV=dev`, `AI_FEATURE_ENABLED=true`, `PLANNING_CHAT_ENABLED=true`, `ALLOW_DRAFT_METHODS=true`, `AI_MAX_OUTPUT_TOKENS=900`.

### Browser checklist

1. `http://127.0.0.1:8000/admin`: sign in with SERVIR (`kovitad.janlakhon@adpc.net` is Platform Admin and Hub Admin of `adpc`)
2. `/platform.html`: set a token limit (for example 50,000), AI **On**, Save; **Send test call**; **Reset now**; create, close and reopen a Hub; security log
3. `/planning.html`:
   - **Where could people move?** runs the synthetic assessment; the card shows 7 / 3 / 2 / 2 and dots are coloured
   - "Which centers could not be assessed, and why?" explains the stored result
   - `where could people move if flood happen in บางบัวทอง นนทบุรี`: progress card with timer; status card with a note that this is not a GRP area; evidence panel opens (Evidence, What is missing, How it was produced, Download); Bang Bua Thong outlined
   - **Publish receipt & show SIG flood map** (two-step confirm, creates a public record): SIG hazard map over the map
   - switch to Assessments and back: the conversation is kept
4. `/assessments.html`, `/workspace.html`: same top bar, same order
5. Langfuse Cloud: traces `planning-router-v1`, `planning-draft-v1`, `result-explain-v1`, `platform-test-v1`

---

## 4. Architecture map (what lives where)

### 4.1 Backend (FastAPI, Python 3.12)

| Area | Files | Notes |
|---|---|---|
| App, errors, settings | `api/main.py`, `api/errors.py`, `api/settings.py` | Appendix D errors; dev-only no-cache middleware for web files |
| Sessions and access | `api/sessions.py`, `api/auth.py`, `api/oidc.py`, `core/identity.py`, `api/permissions.py`, `api/planning_access.py` | CSRF header `X-CSRF-Token`; POST sign-out; revocation via `app_user.sessions_valid_after` |
| Admin and platform | `api/admin.py`, `api/platform.py`, `api/audit.py`, `grp/admin.py` | CLI: `bootstrap-platform-admin`, `ensure-hub`, `assign-member`, `list-access-requests`, `rotate-sig-token` |
| AI | `core/ai_models.py`, `core/ai_allowance.py`, `api/ai_gateway.py`, `api/langfuse.py`, `api/ai.py` | The gateway is the only provider caller; reserve, call, settle; Langfuse is best effort |
| Assessment | `core/assessment_models.py`, `core/assessment_jobs.py`, `core/gis.py`, `core/result_rules.py`, `core/storage.py`, `core/validation.py`, `api/assessments.py`, `api/catalog.py`, `worker/main.py`, `grp/seed.py` | The API never imports GIS; the worker claims with `SKIP LOCKED` |
| Map | `api/maps.py`, `core/hazard_overlay.py` | Display-only flood PNG drawn at seed time |
| Planner assistant | `api/planning.py`, `api/sig_evidence.py`, `api/mcp_client.py`, `api/token_store.py` | See 4.3 |
| SIG service login | `api/integrations/sig.py` | Evidence endpoint returns 404 until Increment 3 |
| Migrations | `migrations/versions/20260916_0001`…`0004` | Forward-only |

### 4.2 Frontend (static, no build step)

| File | Role |
|---|---|
| `web/grp-common.js` | `window.GRP`: `request()` (CSRF, Idempotency-Key, typed errors), `me()` (cached identity), **shared top bar** (`<header data-grp-topbar>`; fixed order Planning · Assessments · My access · Administration · Platform), sign-out that clears `sessionStorage` keys starting with `grp.`, formatting helpers, §10.6 allowance text |
| `web/styles.css` | Global styles. The **SERVIR palette tokens** (`--servir-grey/blue/blue-dark/navy/green/green-soft`) are in `:root`; the older `--forest-*` and `--lime-*` names map to them. Top bar styles are under `/* Shared top bar */` |
| `web/planning.html/.css/.js` | Chat bot plus map (details in 4.3). `planning.css` tokens `--pw-*` follow SERVIR blue |
| `web/assessments.*` | Form-based assessment run and full result table |
| `web/platform.*`, `web/workspace.*` | Platform Admin page; My access, members and Hub security log |
| `web/index.html`, `register.html`, `admin-login.html` | Sign-in pages (photo plus card; SERVIR logo) |
| `web/assets/servir-global-collaborative.png` | Official logo (full colour, transparent) |

Rules: no `innerHTML` with server or user text (tests check this). Build DOM with `textContent`.

### 4.3 Planner assistant flow (`POST /api/v1/planning/chat`)

1. Checks: `PLANNING_CHAT_ENABLED` and `GRP_ENV=dev`; Planner or Hub Admin of the Hub; 20 AI requests per hour.
2. **Router** AI call (`planning-router-v1`):
   - Context sent: selected area, whether a result is shown, supported area names.
   - The model returns `{mode, reply, place (English romanized), return_period_years}`.
3. By mode:
   - `explain_result`: `explain_stored_result()` (`result-explain-v1`) using only stored result fields.
   - `run_assessment`: matches supported areas or the map selection, then `create_assessment()` and returns `assessment_started`.
     - **If the place is not a GRP area, it falls through to `sig_flood` with a `note`.**
   - `sig_flood`:
     - MCP `assemble_pack(risk, place, flood)`.
     - `check_area()` requires `aoi[...] via admin boundary` with a matching name; otherwise `area_rejected`.
     - Draft (`planning-draft-v1`).
     - If `publish_receipt`: `publish_answer`, then `ui_embed(hazard_map)`; a blocked draft is withheld.
     - Response includes `evidence` (see `evidence_bundle()`): citations, gaps, stats, SIG trace, GRP trace with `duration_ms`, `total_ms`, summary counts, receipt.
   - `chat` returns a reply; `cannot` returns server text (vulnerable people, investment brief and the red/yellow/green map are "coming next").
4. Frontend (`planning.js`):
   - progress card with timer (steps advance on typical timings);
   - status card (note, counts, timings, draft/receipt badge), with the brief rendered as headings and `[n]` citation buttons;
   - evidence panel with tabs and downloads (.md, .json, .txt);
   - SIG area outline from Nominatim (orientation only); SIG hazard map iframe after publish.
   - State (transcript, selection, result, pending job, open evidence) is saved in `sessionStorage["grp.planning.v1"]`, scoped to the user email and capped at 40 entries.

### 4.4 Tests

- `tests/fast`: sessions, OIDC rejections, identity, AI limit and gateway, Langfuse, SIG service, platform admin, planning chat with fake SIG and model, UI static checks.
- `tests/contract/test_permission_matrix.py`: every route × role.
- `tests/golden`:
  - `test_synthetic_rp100.py` compares against the hand-designed `synthetic_rp100/expected_*`;
  - `test_planning_map.py` covers layers, PNG, explain privacy and chat intents.
- Run: `python -m pytest` (needs `.[dev,gis]`) and `python -m ruff check .`.

---

## 5. What changed in the last session block (17 Sep)

| Commit | Change |
|---|---|
| `e0b219e` | SIG answers: status card in chat; evidence panel (Evidence / What is missing / How it was produced); downloads; SIG area outline |
| `1d28bed` | "Where could people move" in a non-GRP area falls back to SIG evidence with a note; the brief says plainly when there are no evacuation centers |
| `ac1ec4e` | Progress card with timer; per-step durations from the API; formatted brief with citation buttons; dev no-cache for web files |
| `e174dfd` | Planning conversation kept when switching menu pages (`sessionStorage`) |
| `6832dbb` | One shared, left-aligned top bar for all signed-in pages |
| `54c29d5` | SERVIR Global Collaborative logo; one palette across the app and sign-in pages |
| (this commit) | Top bar tests updated; this handover; `AGENTS.md` pointer |

Earlier on 16–17 Sep: Increment 2 completion, ADR-0004 chat, Increment 1, map workspace, natural routing, chat-bot redesign and Thai romanization (see `git log`).

---

## 6. Decisions and ADRs

| Record | Decision | Status |
|---|---|---|
| ADR-0002 | Interim SERVIR sign-in via a self-registered SIG MCP client; MCP token kept in memory for local chat | Proposed; remove before Beta (DEP-01) |
| ADR-0003 | Platform Admin manual reset of current-month AI usage | Accepted by owner; spec AI-11 text to update |
| ADR-0004 | Interim Planner chat and map on SIG generic evidence, Docker Desktop only | Accepted for local testing; Technical Lead review pending |

Owner decisions (16–17 Sep):
- remove the pending access list;
- Increment 2 includes the AI limit, gateway and Langfuse;
- OpenStreetMap only;
- vulnerable people stays a placeholder;
- the Planning map before Increment 4;
- chat-bot UX with the opening question "What decision are you preparing for?";
- a natural language flow with no mode switches;
- SIG fallback for non-GRP areas;
- keep state across pages;
- fixed left-aligned menu;
- the SERVIR Global Collaborative logo and palette.

---

## 7. Known gaps, risks and technical debt

- **Docker image is stale** versus code (Section 3). Rebuild before relying on a new container.
- **Live end-to-end not formally confirmed:** OpenAI, Langfuse and SIG MCP work was observed by the owner in the browser but is not captured in tests; there is no recorded SIG fixture for the chat.
- **Area check** relies on SIG trace wording `via admin boundary` (from the 14 Sep capture).
- **Progress steps are estimated.** The API answers in one response; true streaming (SSE) is not built.
- **SIG flood cells** appear only after publishing a receipt (the pack has no geometry). The outline before that comes from Nominatim, for orientation only.
- **External browser calls:** `unpkg.com` (Leaflet) and `openstreetmap.org` (tiles, Nominatim). Acceptable for local use only; vendor Leaflet and use a contracted tile and geocoder before staging.
- **Real data missing:** the only GRP assessment area is synthetic; the method is draft; geometry is GeoJSON, not PostGIS.
- **Single-process memory** holds rate limits and the SIG token store; there is no lease renewal for long jobs.
- `web/planning.js` (~1,200 lines) and `api/planning.py` (~650 lines) are large. Split them before adding much more.
- **Spec text** needs updating for ADR-0003, ADR-0004 and the Increment 2 scope change.
- **Phone layout** of the new top bar and sign-in pages is not visually verified.

---

## 8. Dependencies to chase

| ID | Needed | Owner | Blocks |
|---|---|---|---|
| DEP-01 | GRP registered as its own app in SIG WorkOS | SIG platform owner | Removing ADR-0002; Beta |
| DEP-04, DEP-06 | Chiang Yuen boundary, center dataset, signed golden result | Scientific and Data Authority | Increment 1 acceptance |
| DEP-05 | JRC flood layers for seven return periods, licence | Scientific and Data Authority | Increment 5, real flood map |
| DEP-07 | Vulnerability layer and meaning | Scientific and Data Authority | Vulnerable people layer |
| DEP-08, DEP-09, DEP-13 | Risk pack `assessment_ref`, SIG machine login | SIG platform owner | Increment 3 |
| DEP-11 | AI key per Hub, starting token limit | Product Owner, Technical Lead | AI outside local |
| DEP-12 | Summary and map download templates | Product Owner with planners | Increment 4 |

---

## 9. What to build next (recommended order)

Each item has a clear "done when". Keep the spec guardrails (Section 11).

1. **Stabilise and merge** (small)
   - Rebuild the Docker `api` and `worker` images; run the Section 3 checklist; fix findings.
   - Merge `feat/planning-chatbot-ux` into `main`, push, delete stacked branches.
   - *Done when* `main` has everything, CI is green, and the owner has accepted the checklist.
2. **Record a SIG contract fixture for the chat** (small)
   - Capture one real `assemble_pack` and `publish_answer` response (public area, no secrets) under `tests/fixtures/sig/`, reviewed as a diff.
   - Replay it in a test of `sig_evidence` and `evidence_bundle`.
   - *Done when* area check, counts and trace are tested against real SIG shapes.
3. **Real streaming progress** (medium)
   - Server-Sent Events for `/planning/chat` (router done, pack gathering, area checked, draft, publish), replacing estimated steps.
   - *Done when* the progress card shows true step states and durations live.
4. **Increment 4: review and download** (medium to large; spec Section 16)
   - Job trace screen for Admin (`GET /admin/assessments/{id}/trace`).
   - One-page summary PDF and evacuation map PDF/PNG as export jobs (`assessment_export` table, `POST/GET /assessments/{id}/exports`).
   - *Done when* the synthetic case downloads match the locked result exactly (templates need DEP-12).
5. **Real-data readiness** (medium)
   - PostGIS geometry columns and a boundary loader (admin level, source, edition, fingerprint).
   - A PostgreSQL CI job for migrations and two workers claiming at once.
   - Lease renewal.
   - *Done when* a real Thailand district can be loaded and assessed once DEP-04/05/06 arrive.
6. **Increment 3: SIG connection** (medium; waits on SIG)
   - Sharing approval (Admin), evidence endpoint with the public field set, SIG machine login (client credentials), `assessment_ref` call, receipt linking, retry every 15 minutes for 24 hours, contract tests.
   - *Done when* the pack numbers equal the golden result, private items return 404, and one receipt is issued by hand.
7. **Planner assistant extensions** (as the owner prioritises)
   - "Which vulnerable people need support?" once DEP-07 lands.
   - Preparedness investment brief (a traceable document from the result and evidence; export .md/.pdf).
   - Red/yellow/green risk map (needs a risk-level method; SIG says L1/L2 is not in the pack yet).
8. **Hardening before any server**
   - Vendor Leaflet; move to a contracted tile and geocoder.
   - Replace in-memory limits and token store.
   - Split `planning.js`/`planning.py`.
   - Update spec text for the ADRs.

---

## 10. Working rules for the next agent

- Follow `AGENTS.md`. Every route declares `x-grp-access`; the permission matrix test must cover new routes.
- Every new route uses the Appendix D error format, 404 for other Hubs, the CSRF header for state changes, and security log events where Section 13.3 requires.
- AI calls go **only** through `api/ai_gateway.run_ai_call`, and prompts contain only the fields allowed by Section 10.5.
- Numbers come from the worker's locked result (AD-03, AD-04). Never present SIG generic evidence as a GRP assessment. Never say "safe"; say "not exposed under this scenario".
- Never invent golden or scientific values; synthetic data must be labelled.
- Never commit `.env`, keys, tokens, `.local/`, captures with secrets, or the spec `.docx`.
- Commit messages: `feat:`, `fix:`, `docs:`, `test:`.

## 11. Architecture guardrails (spec summary)

- The GIS worker is the only calculator; every assessment is a background job with pinned inputs and fingerprints.
- Stop safely with typed errors; never substitute a fallback area, dataset, route or provider.
- SERVIR sign-in proves identity; GRP membership decides Hub and role; a Platform Admin flag is not a Hub role.
- Nothing goes to SIG unless an Admin shares it (Increment 3); receipts are public and prove traceability only.
- AI explains; it never decides. AI is off unless the build switch and the Platform Admin setting allow it.

## Resume commands

```powershell
git fetch; git switch feat/planning-chatbot-ux
python -m venv .venv; .\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,gis]"
python -m ruff check .
python -m pytest            # expect 196 passed
.\scripts\docker-desktop.ps1 -AdminEmail <you> -HubAdminEmail <you>
```
