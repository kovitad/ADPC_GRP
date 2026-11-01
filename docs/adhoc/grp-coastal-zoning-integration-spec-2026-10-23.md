# Coastal Zoning Assessment (Mangrove 360): integration requirements for the Global Risk Platform

| | |
|---|---|
| **Status** | Draft for review by the SIG platform team |
| **Version** | 0.1, 23 Oct 2026 |
| **Product owner** | Ole (Kovitad Janlakhon), ADPC |
| **Target app** | SERVIR Global Risk Platform (GRP): `apps/api` (FastAPI + LangGraph) and `apps/web` |
| **Source of the logic** | Claude skill `mangrove-winwin-zoning-atlas`, the Mangrove 360 Atlas Engine, and the South Sumatra and Lamu reference runs (22 Oct 2026) |
| **Companion** | `mangrove360-zoning-starter-kit.zip`: rules code, golden tests with fixtures, atlas engine, sample data |

---

## 0. Summary

Add one menu to the GRP, **Coastal Zoning Assessment**. A signed-in user (typically a coastal or resort developer) uses it to:

1. pick an area of interest (AOI);
2. generate an assessment;
3. open the report.

The report is the same win-win zoning atlas we built in Claude:

- what each zone means and why;
- coastal resort zones behind a public government coastal reserve;
- mangrove to protect and restore;
- ranked zones, each with a platform receipt;
- shapefile downloads.

The core design rule: the integration is **a deterministic pipeline inside the GRP backend**, with the LLM used only to draft the per-zone briefs that pass the platform's own gate. Do not run the Claude skill per request. The skill is the specification; this document turns it into product requirements.

---

## 1. Answers to the two setup questions

### 1.1 Do I need to publish the skill at org level for the app to use it?

**No. Publishing it would not help the app.**

- A Claude skill, whether personal, shared or provisioned for the org, exists only inside Claude's own apps: claude.ai, Cowork, and Claude Code via sync. Your GRP backend (LangChain/LangGraph) can never load it.
- Org-level publishing only matters for **colleagues using Claude** who want to run the skill themselves. See *Share the skill* in the earlier answer.
- For the GRP, **port the skill into the codebase**:
  - its rules become Python modules (Section 7, Appendix C);
  - its writing rules become a versioned prompt;
  - its atlas becomes a frontend component.
- Optionally, keep `SKILL.md` in the repo as `docs/skills/mangrove-winwin-zoning-atlas/SKILL.md`, so humans and AI coding tools have one written spec.
- If you later call the **Claude API** directly and want to use API-side Skills, those live in an **API workspace**. You upload them with an API key; they are not your claude.ai skills. Section 4.3 explains why that path does not fit this pipeline.

### 1.2 Authentication: existing login, LangChain and MCP

- **End users** sign in with the GRP's **existing login**, unchanged. The new menu is just another authenticated route (Section 9).
- **The backend reaches platform capabilities in one of two ways:**
  - **(a) Preferred:** call the same internal service functions that back the MCP tools (`assemble_pack`, `publish_answer`, `resolve_place_time`) **in-process**. The MCP server and `apps/api` live in the same repo, and the MCP server reports transport `stdio`.
  - **(b)** Call through an MCP client, e.g. LangChain's `langchain-mcp-adapters`, using a **service credential held only on the server**.
- **Never forward the user's browser token to the MCP server or an LLM provider.** Record the user's identity on the **run record** and in the **trace**.
- **LLM calls** use the platform's configured provider and key. The `compose_run` compositions already run with "the PLATFORM's model and key". There are no per-user model keys.

---

## 2. Scope

### 2.1 Users and roles

| Role | Can do |
|---|---|
| **Assessment user** (coastal or resort developer, planner, analyst) | Create assessments for an AOI, view their own reports, download files, share a report inside the platform |
| **Reviewer** (domain expert at a hub) | Approve or edit zone names, legal rows and notes before a report is marked *reviewed*; adjust country defaults |
| **Admin** | See all runs, set quotas, retire a report (never delete receipts) |

Roles map onto the GRP's existing role system. Section 15 lists this as an open decision.

### 2.2 In scope (MVP)

1. **Menu entry** "Coastal Zoning Assessment", with two items: **New assessment** and **My assessments**.
2. **New assessment wizard:**
   - AOI by place search, drawn polygon, or uploaded GeoJSON or shapefile;
   - the parameters shown with their defaults;
   - submit.
3. **Run progress page** with live step status and the execution trace.
4. **Report viewer**, a port of the atlas engine:
   - **Zoning map:** the short answer and what each zone means;
   - **Win-win plan:** the cross-section, the benefits for each side, the design rules, and the resort-to-restoration partner pairs;
   - **Resort zones**, with receipt status for each zone;
   - **Mangrove zones**;
   - **downloads:** zoning map, government reserve, coastal resort zones, inland alternatives, restoration zones, or all.
5. **Report list** with status, AOI, date and the lead picks.

### 2.3 Out of scope for the MVP (Phase 3+)

- PDF or DOCX export.
- Translations (Indonesian and Thai first).
- Public share links outside the platform.
- Bulk runs.
- Exposing the pipeline as a new MCP tool or `compute_run` job (Section 14, Phase 3).
- New datasets. The feature uses **existing platform layers only** and never submits contributions.

---

## 3. What already exists (checked live on 23 Oct 2026)

These come from `platform_capabilities`, `ui_catalog`, `ui_design` and the `trace-emit` skill resource on the live MCP server, version `0.2.0-phase1`. Re-check them at build time, because they come from the live registry.

| Asset | Fact | How we use it |
|---|---|---|
| **Platform contract** | Evidence attached to every insight; declines say why; everything replayable via a receipt; human input declared (ADJUSTED, target-pinned); verdicts server-bound; receipts outlive everything | These are non-negotiable requirements (Section 10) |
| **Canonical loop** | `assemble_pack` → model drafts with [n] citations in `required_sections` → `verify_groundedness` → publish only on pass → `record_receipt` (`publish_answer` does verify + record) | Step P8 of the pipeline |
| **Bones** | resolve, fetch, context, assemble, verify, record and contribute are *available*; **compute (`compute_run`) is *planned (phase2)*** | The zoning pipeline is a compute capability. Build it so it can become a `compute_run` job later |
| **Compositions** | `landcover.brief` and `risk.brief` run the LLM **server-side with the platform's model and key** | Same model and key path for our zone briefs |
| **Builder requirements** | Every run must emit an execution trace: `trace_id`, `duration_ms` per step, a one-line summary per step, and token usage for model steps. Show `publish_answer`'s own `trace`. A finished build includes one real captured trace | Section 11 |
| **Backend layout** (from `trace-emit`'s reference map) | `apps/api/src/app/graph/graph.py` (LangGraph nodes), `apps/api/src/app/graph/tracing.py`, `apps/api/src/app/api/routes/chat.py`, `apps/api/tests/…` | Where the new module and routes go (Appendix C) |
| **Frontend** (`ui_catalog`) | `apps/web` components: `ChatArea/`, `EmbedMap` (risk pack), `Provenance/`; embed mode `/?embed={component}&receipt_id=…` | Reuse the header, embeds and trust chrome |
| **Required header** | `platform_header` (SERVIR logo + domain name) is required on every page | Report and wizard pages |
| **Receipt-bound UI** | `provenance_graph` (embed, binds `receipt_id`); `groundedness_strip` (embed, binds `report_id`); `source_card` and `decline_card` (recipes) | Zone receipts and declines |
| **Resolver** | `https://servirplatform.sig-gis.com` with `/api/resolve/receipt/{id}`, `/api/resolve/report/{id}`, `/api/resolve/pack/{id}` | Verdicts resolve at **view time**; never stored as a flag |
| **Theme** | `grp` v0: daisyUI/Tailwind tokens and `--grp-*` CSS; success colour reserved for server-verified state; default *unverified* | App chrome. Zone colours are data colours (Appendix A) |
| **Mangrove 360 assets** | Rules code (`make_zones_winwin`, tested), atlas engine (`app.js`/`app.css`), `sites.json` contract, default texts, golden fixtures | Starter kit |

---

## 4. Architecture

### 4.1 Decision: a deterministic pipeline, with the LLM for briefs only

- **Most of the work is fixed computation:**
  - pulling map tiles;
  - mosaicking;
  - zoning;
  - picking zones;
  - shapefiles;
  - atlas data.

  Code does this faster, more cheaply and repeatably, and it can be tested against the golden runs.
- **The model writes only** the cited brief for each zone, from that zone's evidence pack. The platform gate (`publish_answer`) decides whether the brief passes.
- **Ranking, stars and partner pairs are arithmetic** on gated numbers. The notes come from templates filled with gated numbers, so the model does not write them.

### 4.2 Component view

```mermaid
flowchart LR
  subgraph web[apps/web]
    M[Menu: Coastal Zoning Assessment] --> W[New assessment wizard]
    M --> L[My assessments]
    W -->|POST /api/zoning/runs| API
    L --> R[Report viewer - atlas engine port]
    R -->|GET sites.json, codes.png, zips| API
    R -->|view-time verdicts| RES[/api/resolve/*]
    P[Run progress + trace] -->|SSE or poll| API
  end
  subgraph api[apps/api]
    API[routes/zoning.py] --> Q[(job queue)]
    Q --> WK[zoning worker]
    WK --> PIPE[zoning/pipeline.py]
    PIPE -->|in-process| T1[resolve_place_time]
    PIPE -->|in-process| T2[assemble_pack]
    PIPE -->|LLM, platform key| D[brief drafter]
    PIPE -->|in-process| T3[publish_answer]
    PIPE --> ST[(run store + artifact storage)]
  end
```

### 4.3 Why not the alternatives

| Option | Verdict |
|---|---|
| Run the Claude skill per request (Claude Agent SDK on the server) | Fine for an **internal analyst prototype** only. Each run takes minutes of agent time, costs more, is less repeatable, and adds a second agent stack beside LangGraph |
| Claude API with uploaded Agent Skills | **Poor fit.** The code-execution container has **no network access** and no package installs, so the tile pull cannot run in it. Pack results would also flood the context |
| Call `compose_run("landcover.brief")` per zone | **Not enough.** The composition parses a *place* from a question, but zones are custom polygons. Use the loop (`assemble_pack` with `geometry` → draft → `publish_answer`) |

---

## 5. User experience requirements

### 5.1 Navigation

- **Main nav:** "Coastal Zoning Assessment", with sub-items **New assessment** and **My assessments**.
- **Pages:**
  - `/zoning` (list)
  - `/zoning/new` (wizard)
  - `/zoning/runs/{run_id}` (progress, which becomes the report when done)
  - `/zoning/runs/{run_id}#<view>`, where `<view>` is `zones` | `winwin` | `resort` | `restoration`, for deep links
- Every page shows `platform_header` (required by the platform).

### 5.2 Wizard: New assessment

**Step 1: Where.**

- **Search a place.** Use `resolve_place_time` via `GET /api/zoning/places?q=`, showing candidates with their admin level.
- **Draw on the map.** Polygon or rectangle.
- **Upload.** GeoJSON, or a zipped shapefile (`.shp/.shx/.dbf/.prj`).
- **Validation, shown inline:**
  - one polygon or multipolygon;
  - WGS 84 (reproject if a `.prj` says otherwise);
  - valid geometry;
  - at most ~5,000 vertices (simplify with a notice);
  - area within the limit (Section 9.4);
  - touches a coastline.
- **Coverage check** on the client side, before submit. Call `GET /api/zoning/coverage?aoi=` and show:
  - which mangrove map, elevation, population, land cover and hazard layers cover the AOI;
  - the **profile** that follows (hazard rules or no-hazard rules);
  - the **scale** (local or province).
- **Missing layers are shown as declared gaps**, for example "No flood or fire hazard layer covers this area: resort zones will rely on land cover and height only."

**Step 2: Settings.** Show each default with its source:

| Setting | Default | Source shown |
|---|---|---|
| Government coastal reserve | Country table (Appendix B), e.g. Indonesia 100 m from the highest tide; Kenya 100 m on the map (legal minimum 60 m) | "hub default configuration" |
| Coastal resort band | 5 km (province scale) or 1 km (local scale) | hub default |
| Mangrove buffer | 100 m | hub default |
| Inland alternatives | On at province scale with hazards; off otherwise | hub default |

- Any change is labelled **"ADJUSTED by the requester (not the hub default)"**. This is the platform voice, and it is stored on the run and printed on the report.
- For countries outside the table, the reserve shows **"100 m planning default, not law: to confirm with the coastal/planning authority"**.

**Step 3: Review and submit.**

- Show a summary, the declared gaps, and what the report will and will not check.
- Submit returns a `run_id` and goes to the progress page.

### 5.3 Run progress page

- **A step list** (Section 7), each step showing its status (`queued`, `running`, `done`, `failed`, `skipped`), duration, and a one-line summary from the trace.
- **Expected duration:** minutes. The reference runs pulled 72–87 tile packs per site, plus one evidence pack per zone. Show "You can leave this page; the report will appear in My assessments."
- **Failures:**
  - If a step fails, show the reason and a **Retry from this step** action. Steps are idempotent (Section 7.3).
  - If no coastal resort zone is found, the run still completes. The resort tab shows a **decline card** with the cause (e.g. "every coastal cell is deep-flood or settlement").

### 5.4 Report viewer (atlas port)

Port `web/engine/app.js` and `app.css` from the starter kit into an `apps/web` component, for example `ZoningAtlas`, keeping the same data contract (`sites.json`). The current engine is plain JS with Leaflet 1.9.4, so it ports directly into React with `react-leaflet` or a thin wrapper.

The viewer must have these, all of which already exist in the engine:

- **Four tabs:**
  - **Zoning map:** the short answer, plus **what each zone means**, with colour, name, area, *what you can do* and *why*. Each zone has a show/hide toggle, and clicking the map gives a popup.
  - **Win-win plan:**
    - the cross-section (sea → mangrove → government reserve → coastal resort zone → village);
    - four stat tiles;
    - what each side gets and commits to;
    - design rules;
    - the partner-pairs table, with dashed lines on the map;
    - the country rules to check.
  - **Resort zones:** coastal C1–C6 (recommended), plus inland A1–A6 as the second choice when present. Cards show stars, facts and notes.
  - **Mangrove zones:** R1–R4.
- **Downloads** as normal authenticated HTTP downloads. This replaces the Claude-only downloads capability.
- **Light and dark modes**, a phone layout, and keyboard focus states.

**Changes required for the GRP:**

1. **Receipts:**
   - Each zone card shows its receipt through a **receipt-bound component**. Use the resolver, or the `provenance_graph` / `groundedness_strip` embeds.
   - Never show a stored "passed" flag. The default chip state is *unverified* until the resolver answers.
   - A zone without a receipt shows "Map-grid estimate" and stays unranked.
2. **Header:** `platform_header`, with the domain name from the pack manifest (Land Cover).
3. **Theme:** the GRP theme tokens drive the app chrome. Zone colours stay the data palette in Appendix A.
4. **Trace panel:** a collapsible "How this report was made" panel shows the run trace, including each `publish_answer` trace.
5. **Status banner:** *Draft* until a reviewer approves, then *Reviewed by <role> on <date>*. Use the role only, not a personal name, unless the reviewer opts in.

---

## 6. API (apps/api)

All routes need the existing auth dependency. Every response includes a `trace_id`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/zoning/places?q=` | Place search via `resolve_place_time`; returns candidates with id, name, level and a simplified geometry |
| POST | `/api/zoning/coverage` | Body: AOI geometry. Returns layers covering it, profile, scale, country, default parameters, area, and an estimated tile count |
| POST | `/api/zoning/runs` | Creates a run. Body below. Returns `201` with `run_id` |
| GET | `/api/zoning/runs` | Lists the caller's runs (admins: filter `owner=`) |
| GET | `/api/zoning/runs/{id}` | Run status, steps, parameters (with `source`: default or adjusted), lead picks, and errors |
| GET | `/api/zoning/runs/{id}/events` | SSE stream of step events (fallback: poll the route above every 3 s) |
| POST | `/api/zoning/runs/{id}/retry` | Retry from the failed step |
| POST | `/api/zoning/runs/{id}/cancel` | Cancel a queued or running run |
| POST | `/api/zoning/runs/{id}/review` | Reviewer approves or edits names, notes and legal rows (audit-logged) |
| GET | `/api/zoning/runs/{id}/sites.json` | Atlas data (Appendix C contract) |
| GET | `/api/zoning/runs/{id}/codes.png` | Zoning grid image (R = zone code) |
| GET | `/api/zoning/runs/{id}/files/{group}.zip` | `group` is `zones`, `reserve`, `coastal`, `inland`, `restoration` or `all` |
| GET | `/api/zoning/runs/{id}/trace` | The run's execution trace (JSON) |

Create-run request:

```json
{
  "aoi": {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[110.45,-6.95],[110.70,-6.95],[110.70,-6.75],[110.45,-6.75],[110.45,-6.95]]]},
          "properties": {"name": "Demak coast", "source": "drawn"}},
  "site_name": "Demak",
  "country": "ID",
  "params": {"reserve_m": 100, "coast_band_m": 1000, "mangrove_buffer_m": 100, "inland": false},
  "language": "en"
}
```

The coordinates above are a placeholder shape, not a site recommendation. Any `params` key that differs from the server's default is stored as `ADJUSTED`.

Run status response (abridged):

```json
{
  "run_id": "zr_01J…", "status": "running", "owner": "user_123", "created_at": "2026-10-23T09:00:00Z",
  "profile": "no_hazard", "scale": "local",
  "params": [{"name": "reserve_m", "value": 100, "source": "hub_default"}],
  "steps": [{"key": "P3_tiles", "status": "running", "done": 41, "total": 72, "duration_ms": null, "summary": "41 of 72 tile packs"}],
  "versions": {"rules": "1.0.0", "prompt": "brief-v1", "engine": "1.0.0", "model": "<platform model id>", "platform": "0.2.0-phase1"},
  "trace_id": "tr_…"
}
```

---

## 7. Pipeline specification (`apps/api/src/app/zoning/`)

### 7.1 Steps

Each step is one trace step, as the `trace-emit` rule requires: a step is something a user would name.

| # | Step | Does | Platform calls | Output |
|---|---|---|---|---|
| P1 | Resolve | Normalise the AOI, detect the country, check coverage, pick profile and scale | `resolve_place_time` (if a place) | `aoi.geojson`, profile, scale, country |
| P2 | Inventory | List the layers and years covering the AOI; record licence and vintage gaps | registry or `platform_capabilities` (cached) | `inventory.json` |
| P3 | Pull tiles | Tile the AOI bbox (0.03° local, 0.15° province); one `assemble_pack` per tile with ≥5 layers; 4–6 in parallel; latest and earliest mangrove years | `assemble_pack` ×N | `raw/*.json` (cached) |
| P4 | Mosaic | Decode grids; build one grid (cell = the stack's own cell rounded down); check mangrove area against a whole-AOI pack (±5%) | `assemble_pack` ×1 | `inputs.npz`, mosaic check |
| P5 | Zone | Build masks; run `make_zones_winwin`; sanity checks | none | `zoning.tif`, class areas |
| P6 | Pick zones | Pick C1–C6 coastal, A1–A6 inland (if enabled) and R1–R4 restoration; build polygons (full and simplified); name zones; pair partners | `resolve_place_time` for nearby towns | `zones.json` |
| P7 | Evidence | One full-resolution `assemble_pack(geometry=zone)` per ranked zone | `assemble_pack` ×(≤16) | `packs/*.json` |
| P8 | Brief and gate | Draft a brief per zone (LLM) → `publish_answer`; ≤2 targeted retries; a still-blocked zone becomes unranked | LLM, `publish_answer` | receipts, `publish_results.json` |
| P9 | Rank | Stars, scores, lead picks, template notes from gated numbers | none | ranked `zones.json` |
| P10 | Package | Shapefiles + README; `sites.json`; `codes.png`; zips; manifest with sha256 | none | artifacts |

### 7.2 Rules (port from the skill and starter kit)

- **`zoning/rules.py`:** `make_zones_winwin`, copied verbatim from the starter kit. **Golden tests must pass:** South Sumatra ≥ 99.9% of cells, Lamu ≥ 99.6%.
- **Zone codes, rule order and parameters:** as in the skill and Appendix A.
- **Missing layers are `None`, never zero arrays.** NaN hazard means *unknown* and is not eligible for resort zones. DEM gaps become code 9 (not assessed).
- **Sea mask:** prefer a water layer. Otherwise use outside-AOI cells connected only to the seaward edges, then clear neighbouring land. This needs an automated check: sea must touch the bbox edge and must not exceed the mapped water by a threshold.
- **Brief prompt** (`zoning/prompts/brief_v1.md`):
  - use the pack's own `required_sections`;
  - every paragraph ends with [n] citations;
  - no bullet lists;
  - quote only numbers present in the pack. Derived numbers such as people = mean × cells are **blocked** by the gate, so the arithmetic happens in P9, labelled "about".
  - Map citation numbers **by content per pack** (`cite_map` in the skill), never by position. One reference pack had 14 sources instead of 13.
  - Before writing "no Moderate or higher" fire, check the per-mangrove-class breakdown.
  - Name flood class 0 as "not in the legend".
- **Ranking:**
  - **Hazard profile:** deep-flood share ×3, fire Very-Low share ×2, people ×2, closeness to the sea ×1.
  - **No-hazard profile:** legal or heritage risk ×3 (only from cited constraints; otherwise drop it and say "legal risk unknown"), ground height ×2, people ×2.
  - **Stars:** ranks 1–2 get ★★★, 3–4 ★★, 5–6 ★.
  - **Restoration:** fastest governed loss, then plantable area, then map-grid-only zones.

### 7.3 Job behaviour

- **Queue:** use the platform's worker if it has one; otherwise a Python queue such as RQ, Arq or Celery (Section 15). One run is one job, and steps are checkpointed.
- **Idempotent and resumable.** Each step writes its outputs under `runs/{run_id}/` and a `step_state` row. A retry skips completed steps. Tile packs are cached by (stack, year, layers, tile bbox, layer version).
- **Cancellation** is checked between tile batches and between zones.
- **Timeouts:** per platform call, with backoff (≤3 attempts, recorded in the trace as one step with an attempt count).
- **Concurrency:**
  - a global cap on concurrent runs;
  - per-run parallelism of 4–6 tile calls;
  - per-user limit of one running run, configurable.

---

## 8. Data model and storage

These tables use SQLite/Postgres-compatible types. Use the platform's existing database; receipts already live in the platform's litestream-backed store.

```sql
CREATE TABLE zoning_run (
  run_id        TEXT PRIMARY KEY,
  owner_id      TEXT NOT NULL,            -- from the existing login
  site_name     TEXT NOT NULL,
  country       TEXT,                     -- ISO 3166-1 alpha-2, nullable = unknown
  aoi_geojson   TEXT NOT NULL,
  aoi_source    TEXT NOT NULL,            -- place | drawn | upload
  profile       TEXT NOT NULL,            -- hazard | no_hazard
  scale         TEXT NOT NULL,            -- local | province
  params_json   TEXT NOT NULL,            -- [{name, value, source: hub_default|adjusted}]
  status        TEXT NOT NULL,            -- queued|running|failed|done|cancelled|retired
  review_state  TEXT NOT NULL DEFAULT 'draft',  -- draft|reviewed
  versions_json TEXT NOT NULL,            -- rules, prompt, engine, model, platform
  lead_json     TEXT,                     -- lead resort and restoration picks
  error_json    TEXT,
  trace_id      TEXT,
  created_at    TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE zoning_step (
  run_id TEXT, step_key TEXT, status TEXT, attempts INTEGER, started_at TEXT, finished_at TEXT,
  duration_ms INTEGER, summary TEXT, detail_json TEXT, PRIMARY KEY (run_id, step_key)
);
CREATE TABLE zoning_zone (
  run_id TEXT, zone_id TEXT, kind TEXT,     -- coastal|inland|restoration
  rank INTEGER, score INTEGER, area_km2 REAL, geom_geojson TEXT, facts_json TEXT, note TEXT,
  pack_id TEXT, receipt_id TEXT,            -- receipt_id NULL = unranked map-grid estimate
  partner_zone TEXT, partner_km REAL, PRIMARY KEY (run_id, zone_id)
);
CREATE TABLE zoning_artifact (
  run_id TEXT, kind TEXT, path TEXT, bytes INTEGER, sha256 TEXT, PRIMARY KEY (run_id, kind)
);
CREATE TABLE zoning_review_log (
  run_id TEXT, reviewer_id TEXT, at TEXT, field TEXT, old_value TEXT, new_value TEXT
);
```

- **Storage:** artifacts go in the platform's object store or volume under `zoning/{run_id}/`, with a manifest of sha256 hashes.
- **Retention:** runs can be *retired* (hidden), but their receipts are never deleted ("receipts outlive everything").
- **Verdicts are not columns.** Receipt status is resolved at view time via `/api/resolve/receipt/{id}`.

---

## 9. Authentication, permissions and security

### 9.1 Login

- **Reuse the existing GRP login and session.** No new identity system.
- Every `/api/zoning/*` route uses the existing current-user dependency. The exact mechanism (session cookie or JWT) is to be confirmed with the platform team.
- The frontend menu shows only for roles allowed to run assessments.

### 9.2 Authorization

| Action | Rule |
|---|---|
| Create a run | role `zoning:run`, mapped onto existing roles |
| View a run | owner, or users the owner shared with, reviewers, admins |
| Review | role `zoning:review` |
| Retire | owner or admin |
| Download | anyone who can view |

### 9.3 Secrets and service access

- Platform tools are called in-process, or by MCP with a **server-side service credential**.
- LLM calls use the platform's key.
- No user tokens or keys go to the browser, the LLM, or the MCP server.
- Keep resolver and embed hostnames exactly as configured. A localhost vs 127.0.0.1 mismatch is a CORS failure that fails closed to *unverified*.

### 9.4 Input limits and abuse controls

- **AOI area cap.** Start with ≤ 2,500 km² at local scale. Province scale (up to ~25,000 km²) is allowed only for the reviewer and admin roles. Tune after the first traces.
- **Maximum tile count per run.** Reject at the coverage check with a clear message.
- **Uploads:**
  - size ≤ 10 MB;
  - parse only GeoJSON or shapefile, with no other formats;
  - reject a multi-layer zip that contains executable files;
  - never run code from uploads.
- **Rate limits** per user and globally. Record each user's runs per day in the trace for cost tracking.
- **No end-user text reaches tracing in executable form.** This is a `trace-emit` rule.

---

## 10. Governance and honesty (must-have)

These come from the platform contract and the skill's ground rules. Each one is a test case.

1. **Existing data only.** The pipeline calls read and governed-loop tools only. It never calls `contribute_*` and never changes `risk_weights`.
2. **Every number on a zone card** comes from that zone's receipt, or is labelled "map grid". Arithmetic on governed numbers is labelled "about".
3. **Declines say why.** Show the cause when there are no coastal zones, a layer is missing, or a gate stays blocked. Never fill a gap with zeros: "No data is not low risk." Show honest zeros as "0 matched — declared as a gap".
4. **No client-set verdicts.** There is no green tick unless the resolver says so. The default is *unverified*.
5. **Human input is declared.** Any non-default parameter and every reviewer edit is labelled ADJUSTED and audit-logged.
6. **Never fabricate:**
   - site coordinates beyond data-derived zone outlines;
   - towns not from `resolve_place_time`;
   - jobs, prices, occupancy, ROI or carbon yields;
   - officials or endorsements;
   - legal widths outside the reviewed country table.
7. **People and rights.**
   - Community participation is not consent. Show FPIC/PADIATAPA wording where relevant.
   - A zone is "a place to look, not a place you may build". This sentence appears on every report.
8. **Legal content is reviewed.** The country table (Appendix B) and the per-country "rules to check" rows are config files with a named reviewer role and a review date. Reports built from unreviewed rows show "to confirm".

---

## 11. Observability (platform builder requirement)

- **One trace per run, `trace_id` on the run.** Steps P1–P10 each record:
  - `duration_ms` (including failures; "both paths emit");
  - a one-line summary;
  - cache hits;
  - external calls with attempt counts;
  - for P8, **tokens and cost for each model call** (null when no model ran, not 0).
- **Attach each `publish_answer` `trace`** to its P8 sub-step and show it in the trace panel. Do not swallow it.
- **Tracing is never load-bearing.** It is wrapped so that a tracing bug cannot fail a run.
- **Save trace JSON** under the run's artifacts so traces can be diffed and attached to issues.
- **Acceptance:** the release includes one real captured trace from a real run.

Implement this by following the platform's `trace-emit` skill (MCP resource `servirplatform://skill/trace-emit`). Its mapping row for a **queue worker** applies: unit of work = each stage, state = job-local, boundary = task completion (persist).

---

## 12. Performance and cost

- **The cost is dominated by** the tile packs (P3: 72–87 per site in the reference runs), plus up to 16 zone packs and up to 16 short LLM drafts with up to 2 retries each.
- **Cache tile packs** per (stack, year, layers, tile, layer version). Re-running the same AOI with new parameters must skip P3 and P4 entirely.
- **Targets are set from the first traced pilot runs.** Record p50/p95 run time and tokens per run, then fix the SLOs. Until then the UI says "minutes".
- **Use prompt caching** for the brief system prompt and pack instructions on the platform's model, where supported.

---

## 13. Testing and acceptance

| Level | Test |
|---|---|
| Unit | `rules.py` golden tests (starter kit `tests/test_rules_golden.py`: South Sumatra ≥ 0.999, Lamu ≥ 0.996, passing today); `cite_map` on 13- and 14-source packs; parsers on real pack text (labels with brackets, e.g. "Lower slope (flat)") |
| Contract | `sites.json` validates against a JSON Schema; `codes.png` R channel equals the raster; zips contain .shp/.shx/.dbf/.prj/.cpg and a README; areas use UTM |
| Governance | No route calls `contribute_*`; a blocked brief yields an unranked zone; receipts resolve; no "passed" strings in rendered HTML; ADJUSTED labels appear when parameters differ |
| UI | Playwright: four tabs × light/dark × 1400×900 and 390×844; no horizontal scroll; zone key count equals class count; popup text; downloads return 200 with the right type |
| Pilot | **Demak** (the Mangrove 360 target site), **South Sumatra** and **Lamu**. A reviewer signs off names, legal rows and lead picks for each |

**Definition of done (MVP):**

- A signed-in user can create an assessment for Demak from the menu.
- The user can watch it run, open the four-tab report, and download all five shapefile groups.
- Every ranked zone has a resolving receipt.
- The run has a saved trace, and a reviewer has approved it.

---

## 14. Delivery plan (GitHub issues for the platform repo)

**Phase 0: alignment.** Agree with the SIG platform team:

- where the module lives;
- the queue and storage;
- the auth dependency and role mapping;
- the model;
- in-process tool calls vs MCP.

The decisions in Section 15 are closed here.

**Phase 1: backend MVP.**

1. `zoning/rules.py` and golden tests (starter kit).
2. Tile pull, cache and mosaic (P3–P4) with tracing.
3. Zone picking, polygons and partners (P5–P6).
4. Evidence, briefs and gate (P7–P8): prompt v1, `cite_map`, retry policy.
5. Ranking and packaging (P9–P10): shapefiles, `sites.json`, `codes.png`, zips, manifest.
6. Routes, job runner, run store (Sections 6–8).
7. Trace persistence and endpoint (Section 11).

**Phase 2: frontend MVP.**

1. Menu, list and wizard (AOI search, draw and upload; coverage; settings with ADJUSTED labels).
2. Progress page (SSE or polling, retry, cancel).
3. `ZoningAtlas` port (four tabs), receipt-bound chips and embeds, `platform_header`, trace panel, downloads.
4. Review flow (approve or edit names, notes and legal rows; audit log).
5. Pilot runs: Demak, South Sumatra, Lamu.

**Phase 3: extensions.**

- PDF report.
- Indonesian and Thai.
- Share links.
- Expose the pipeline as a platform capability (a `compute_run` job when phase 2 compute ships, or an MCP tool `zoning_assessment(aoi, params)`), so other agents and the Claude skill can call the same code instead of re-implementing it.

---

## 15. Open decisions

| # | Decision | Options | Owner |
|---|---|---|---|
| D1 | Where the code lives | `apps/api/src/app/zoning/` (recommended) or a separate service | SIG platform team |
| D2 | Tool access | In-process service functions (recommended) or an MCP client with a service credential | SIG platform team |
| D3 | Job runner | Existing worker, or RQ/Arq/Celery | SIG platform team |
| D4 | Artifact storage | Existing volume or object store | SIG platform team |
| D5 | Auth mapping | Which existing roles get `zoning:run` and `zoning:review` | Product owner + SIG |
| D6 | Model | The platform's configured model; whether one model serves all compositions | SIG platform team |
| D7 | AOI limits and quotas | Area cap, tiles per run, runs per user per day | Product owner |
| D8 | Legal tables | Who reviews the country reserve table and rule rows per country; review cadence | Hub domain leads |
| D9 | Report sharing | Within the platform only (MVP) or public links | Product owner |
| D10 | Organisation boundaries | SIG (sig-gis.com, for-profit LLC) and SIG-NAL (sig-nal.org, 501(c)(3)) are separate legal entities. Agree who owns the code, hosting and model costs for this feature | Leadership |

---

## Appendix A: zone codes and default texts

| Code | Zone | Colour | What you can do | Why (template) |
|---|---|---|---|---|
| 12 | Coastal resort zone: standard build | `#08519c` | First place to look for a coastal resort. Low-rise, behind the public reserve, with paths to the beach | Within ‹band› of the sea, outside the reserve. With hazards: flood class Low, Very Low or 0 (class 0 is not in the legend: check on the ground), and fire Very Low or Low. Without hazards: open bush, grass or bare ground, ≥5 m |
| 13 | Coastal resort zone: raised build | `#4292c6` | Only on raised floors or stilts, with drainage that lets water through, and flood insurance | Within ‹band›; flood class Moderate; fire Very Low or Low |
| 11 | Government coastal and mangrove reserve | `#f4d35e` | Public land: open beach and shore access, green belt, landings, boardwalks. No hotels, walls or fences | ‹law sentence›; this map uses ‹width›; keeps the mangrove edge free of building |
| 1 | Protect existing mangrove | `#1b7837` | No building or clearing; boardwalks, boat trips and traditional use | Shields the coast, feeds fisheries, stores carbon, and is the scenery a resort sells |
| 2 | Restore mangrove lost ‹years› | `#d95f02` | Reopen tidal flow; replant only where it will not regrow by itself | Mangrove in ‹old›, not in ‹new› |
| 3 | Reconnect or plant next to mangrove | `#66c2a4` | Check tides and history, then restore | Wetland or ground ≤2 m within ~1 km of mangrove |
| 7 | Inland resort alternative | `#9ecae1` | Second choice: a quieter inland lodge | Same hazard limits, ≥5 m, ≤15 km from mangrove, beyond the band |
| 6 | Existing settlement or town | `#8c6bb1` | Do not displace; hire and buy locally; agree changes first (FPIC) | ≥5 people per 100 m cell, or built-up land cover |
| 5 | No-build | `#bdbdbd` | Do not build | Deep flood or high fire, wetland, or ground ≤2 m |
| 8 | Zone B: conditional | `#d8cfb5` | Possible only with extra engineering, insurance and checks | Everything else |
| 10 | Sea, creeks and tidal flats | `#dbe9f6` | Boats and fishing; jetties with permits | Open water |
| 9 | Not assessed | `#f3f2ee` | Unknown: get data first | Outside the mangrove map, or a DEM gap |

The default "sides" (what government, communities, developer and nature get and commit to) and the seven design rules are in the skill and in `web/engine/data/sites.json` (Lamu demo). Move them to `zoning/config/winwin_defaults.yaml`.

## Appendix B: country reserve table (config, reviewed)

| Country | Law (summarised, to be confirmed by the reviewer role) | Map value |
|---|---|---|
| Indonesia | Coastal border (*sempadan pantai*) at least 100 m from the highest tide (Presidential Regulation 51/2016); local plans may set more | 100 m (drawn as ≥1 grid cell) |
| Kenya | At least 60 m above the high-water mark is reserved | 100 m (wider than the legal minimum; say so) |
| Others | Unknown until reviewed; check the platform corpus first | 100 m **planning default, not law** |

Rows to check per country, shown in the Win-win tab:

- **Indonesia:** RTRW and the coastal zone plan; *kawasan hutan* and national parks; AMDAL/UKL-UPL; PADIATAPA.
- **Kenya:**
  - mangroves are gazetted forest (Kenya Forest Service licence);
  - the UNESCO heritage buffer, where relevant (National Museums of Kenya);
  - NEMA EIA licence;
  - county spatial plan;
  - land title.

## Appendix C: skill-to-code map and the `sites.json` contract

| Skill section | Module |
|---|---|
| 1 Resolve and profile | `zoning/aoi.py`, `zoning/coverage.py` |
| 2 Tiles and mosaic (`decode`) | `zoning/tiles.py`, `zoning/mosaic.py` |
| 3 Masks | `zoning/masks.py` |
| 4 Zoning (`make_zones_winwin`) | `zoning/rules.py` (verbatim from the kit) |
| 5 Zones (`clusters`), polygons, partners | `zoning/zones.py` |
| 6 Evidence, `cite_map`, drafts, gate | `zoning/evidence.py`, `zoning/briefs.py`, `zoning/prompts/brief_v1.md` |
| 7 Ranking and notes | `zoning/rank.py` |
| 8 Shapefiles (`write_shp`) | `zoning/shapefiles.py` |
| 9 Atlas data | `zoning/atlas.py` (writes `sites.json` and `codes.png`) |
| Orchestration and tracing | `zoning/pipeline.py`, `zoning/tracing.py` (the `trace-emit` pattern) |
| Routes | `apps/api/src/app/api/routes/zoning.py` |
| Viewer | `apps/web/…/ZoningAtlas/` (port of `web/engine/app.js` and `app.css`) |

**`sites.json` contract:** the starter kit's `web/engine/data/sites.json` is a complete worked example, and the skill's Section 9 documents every field. The GRP version serves **one site per run**. `receipt` fields hold ids only; status always comes from the resolver.

## Appendix D: references

- Platform: `platform_capabilities`, `ui_catalog`, `ui_design`, and the MCP resources `servirplatform://how-to-use` and `servirplatform://skill/trace-emit` (live, read 23 Oct 2026).
- Claude skill `mangrove-winwin-zoning-atlas` (claude.ai; shareable to colleagues who use Claude).
- Mangrove 360 Atlas Engine (claude.ai artifact) and the Mangrove 360 Zoning Atlas, South Sumatra and Lamu (reference outputs).
- Project records: `claude/mangrove360-winwin-coastal-zoning-2026-10-22.md` and `claude/SERVIR-Master-Platform-Architecture.md`.
- Claude API notes (only if the Claude API path is reconsidered):
  - Agent Skills in the API run in a code-execution container with no network access: https://platform.claude.com/docs/en/build-with-claude/skills-guide
  - MCP connector: https://platform.claude.com/docs/en/agents-and-tools/mcp-connector
  - Agent SDK skills: https://code.claude.com/docs/en/agent-sdk/skills
