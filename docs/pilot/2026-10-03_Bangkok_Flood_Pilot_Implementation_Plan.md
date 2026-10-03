# Bangkok flood pilot: implementation plan

**Date:** 3 October 2026
**Input:** [`Bangkok_Flood_GRP_Pilot_Development_Spec_v0.3.md`](Bangkok_Flood_GRP_Pilot_Development_Spec_v0.3.md). Its file name says v0.3 but its header still says "Draft v0.2"; the v0.3 content is the CCTV addendum.
**Status:** proposed. Nothing in this plan is built yet. Owner decisions are listed in section 7.

## 1. What the spec asks for, in one paragraph

A Bangkok flood decision-support pilot that does more than show a map. The chain is
**evidence → trusted incident → consequence → decision**. Observations from several sources
(Floodboard, BMA sensors, Traffy, citizens, CCTV, rainfall, GEOGLOWS) go through one canonical
observation model. They are given freshness and corroboration, grouped into incidents, related
to roads and critical assets, and explained with full provenance. A grounded AI answers
questions from that evidence only. Replay mode is essential, because development cannot wait
for rain. "MVP #1" (spec §36) is: *for a Bangkok corridor, is flooding affecting access now,
what is the evidence and confidence, which critical assets are nearby, and what changed?*

## 2. What we checked on 3 October (live probes)

| Source | Finding | Consequence for the plan |
|---|---|---|
| **Floodboard** `/api/export/roads.geojson` | Public, no key, **CC BY 4.0**, `Cache-Control: max-age=30`. 5,013 `MultiLineString` road segments with `name`, `nameEn`, `hw`, `depthCm`, `closedAll`, `closedSmall`, `cleared`, `conf`, `updated` (epoch ms), `verdict` per vehicle (`motorbike/sedan/pickup/truck` → `ok/caution/risky/blocked`) and `sources`. 660 segments were not cleared at the time. | Usable now. It is the first adapter. |
| Floodboard road identity | **No feature `id`.** Names repeat (two identical "Ratchawong Road" rows). A SHA-256 of the geometry was unique, and **5,002 of 5,013** hashes matched across two pulls a few minutes apart; 196 changed properties. | Use the geometry hash as `source_record_id`. Expect a little churn and treat an unmatched segment as new, not as the old one moved. |
| Floodboard `/api/export/reports.csv` | Public, CC BY 4.0 for the export, `max-age=14400`. About 710 reports covering **only the last ~24 hours**. Columns: `id,time_utc,lat,lon,source,tier,depth_cm,closed_all,closed_small_cars,cleared,current_weight,text,url`. Sources: `traffy` 494, `crowd` 206, `news` 5, `bma_sensor` 4, `bma_dds` 1. IDs are source-prefixed (`news:https://…`). | Usable now. The 24-hour window means **history is lost unless we capture it** (section 6). |
| Floodboard freshness | Road `updated` runs from 25 September to now. Features with `hw: "zone"`, `estimated`, `inferred` or `sources: ["cluster"]` are Floodboard's own derivations, not observations. | Freshness bands are needed from day one, and derived features must be labelled as such. |
| **BMA water levels** on data.go.th / data.bangkok.go.th (CKAN) | The "flood" dataset has **one resource, a data dictionary**. Licence: "not specified". Last modified in 2022 (portal mirror 2024). | The spec's "5-minute water-level open data" is **not available from the catalogue**. BMA direct ingestion is blocked until BMA gives access. |
| floodbangkok.bangkok.go.th | A Next.js app. No documented API. | Spec §3 forbids reverse-engineering. We will not mine its bundle. |
| `ipunn/BKK-Road-Flood-Checker-2026` | Active (pushed 2 October), but **no licence**. | Its ~230-camera catalogue cannot be copied. CCTV P0 needs BMA metadata or manual entries. |

## 3. Problems in the spec that the plan has to resolve

1. **Floodboard is already a fusion product.** Its roads and reports already include Traffy, crowd
   reports and BMA sensors. If GRP also ingests Traffy or BMA directly, the same report would
   count twice as "corroboration". **Rule:** corroboration counts independent *underlying*
   sources (`traffy`, `crowd`, `bma_sensor`…), not adapters. A Floodboard report with
   `source=traffy` and a direct Traffy record with the same Traffy ID are one piece of evidence.
   EPIC FB-3's "independent cross-check" is only independent for feeds Floodboard does not use.
2. **Passability rules are "TBD_BY_BMA"** (spec §12). Until BMA supplies them, GRP shows
   Floodboard's `verdict` **labelled as Floodboard's assessment** ("Floodboard estimates…"). GRP
   computes no passability of its own and never guarantees safe passage.
3. **Stack.** The spec suggests Next.js, TypeScript and MapLibre. The repo uses FastAPI, a static
   `web/` folder, Leaflet, PostGIS and a worker. We keep the existing stack; the spec explicitly
   allows FastAPI and asks for replaceable parts. This deviation is recorded in the first ADR.
4. **Text and photos in reports.** The CC BY 4.0 licence covers Floodboard's export, but the
   `text` column quotes news articles and Traffy complaints, which may carry other terms and may
   contain personal details. We **store the ID, URL, time, position, depth and a hash of the text,
   and do not display or commit the text or photos** until this is cleared. This matches how the
   repo already withholds volunteer contact fields.
5. **Roles.** The spec lists PUBLIC, FIELD_REPORTER, OPERATOR, VALIDATOR and ADMIN. The Pilot tab is
   currently Admin-only (ADR-0036). We map onto the existing access model rather than add five
   roles. Public, anonymous pages and citizen POST are owner decisions (section 7).
6. **GEOGLOWS** stays forecast context only, as ADR-0036 decided: no thresholds and no warnings. It
   appears in an incident as "Forecast context", never as evidence of current flooding.

## 4. Architecture inside this repo

```text
worker (housekeeping tick, every N min)        api (read-only, /api/v1/pilot/bkk/...)
  adapters/floodboard.py  --fetch-->  raw store     GET situation, observations, roads,
        |  (bytes + sha256, retrieved_at)            incidents, incidents/{id}, assets,
        v                                            sources/status, cameras, replay
  core/bkk/normalise.py  -> pilot_observation        POST incidents/{id}/verify  (audited)
  core/bkk/freshness.py  -> band per source TTL
  core/bkk/incidents.py  -> cluster, corroborate, conflict   web/pilot.html "Bangkok flood" mode
  core/bkk/exposure.py   -> road/asset joins (PostGIS)         Leaflet map, incident drawer,
  config/pilots/bangkok.yaml (districts, TTLs, radii, weights)  evidence timeline, Thai/English
```

- **Web requests never do GIS work or upstream fetches** (AGENTS.md). Fetching, normalising,
  clustering and spatial joins run in the worker. API routes read stored results.
- **Core never names a provider.** Bangkok-specific values live in `config/pilots/bangkok.yaml`
  and `adapters/`, as spec §32 asks (AC10).
- **New tables, one migration (`20261003_0022_bkk_pilot`)**:
  - `pilot_source`: the registry, holding the spec §21 fields plus health;
  - `pilot_raw_fetch`: retrieved_at, URL, status, sha256, byte size and storage key;
  - `pilot_observation`: the canonical model from spec FB-2, with `freshness_state` computed at
    read time against `as_of`;
  - `pilot_incident`, `pilot_incident_observation`, `pilot_incident_event`: the lifecycle and
    Appendix A events;
  - `pilot_asset_impact`;
  - `pilot_camera`.
- **Every derived value carries `rule_version`** (for example `IncidentCluster v0.1`), as spec §20
  asks.
- **Time is a parameter.** Every engine function takes `as_of`. Live uses `now()`; replay uses the
  simulated clock. This makes replay (AC9) part of the design rather than an add-on.

## 5. Slices, in order

Each slice ends in something the owner can open and judge. It also comes with fast tests,
permission-matrix entries for new routes, Thai and English text, a handover update, and an ADR
where a decision is made.

### Slice 0: prerequisites (half a day)
- **Commit the existing Pilot work** (ADR-0036/0037, River Watch, HAND practice, Thai) on a branch
  first, so the new work has its own diff. Do the signed-in check of `/pilot.html` first.
- Start the **evidence capture** (section 6) if the owner agrees. It is time-sensitive.
- ADR-0038 records the decisions in sections 3 and 4.

### Slice 1: source registry and Floodboard adapter (spec Epic C/FB-1, FB-2; AC8)
- `pilot_source` rows for Floodboard roads, Floodboard reports and GEOGLOWS, each with licence,
  attribution, update frequency, TTL, PII class and redistribution note.
- The adapter fetches both exports on the worker tick (roads every 5 minutes, reports every 15).
  It keeps the raw bytes and SHA-256, checks the schema, and fails closed on unknown shapes.
- Normalisation produces one `pilot_observation` per report and per road segment, with
  `source_type`, the **underlying source** (`traffy`, `crowd`…) and `derived=true` for
  zone/estimated/inferred/cluster features. It is idempotent on `(source, source_record_id,
  observed_at)`.
- Source health: last success, last failure, age of the newest observation, and states
  `ok/degraded/offline`. A failed fetch leaves the last good data in place, marked by its age.
- **Done when:** fixture tests cover parsing, duplicates, schema drift and an outage; a live pull
  stores rows; `GET /pilot/bkk/sources/status` shows health.

### Slice 2: observe map (spec Phase 1, Stories 1, 2 and 6; AC2)
- A new mode on the Pilot page, "Bangkok flood · กรุงเทพฯ น้ำท่วมถนน", next to the existing River
  Watch modes.
- Leaflet map of road segments coloured by **Floodboard's verdict** for a chosen vehicle, with
  report points. **Freshness is drawn separately** (line opacity or dash), never as a second use
  of the colour (spec §24).
- Freshness bands from spec §11 (current, recent, aging, stale, expired), with a TTL per source in
  config. Expired observations are greyed out and cannot make a segment "current".
- Top cards: segments affected, reports in the last hour, sources degraded. Each card links to
  its evidence.
- Floodboard attribution is shown on the map and in the footer, as CC BY 4.0 requires.
- **Done when:** a headless render shows current and stale states in both languages, and a test
  proves an expired report never sets a current state.

### Slice 3: exposure and access (spec Epic H/FB-4; AC4, AC5; Story 7)
- Assets come from **data already in the repo**: Bangkok shelters (evacuation centres), villages
  and district/sub-district boundaries from the Thailand bundle.
- **Schools, hospitals, clinics and transit are a data gap.** OSM is the candidate. Its ODbL
  licence and the "authoritative datasets" question (spec §35 Q8) need an owner decision before
  import.
- The worker computes impact states from spec §13: `nearby_flood` (within a configurable buffer)
  and `access_constraint` (the nearest road segment is affected) are kept **separate from**
  `direct_flood`. A hospital is never called "flooded" because its road is (FB-4).
- Every impact row lists its evidence IDs, distance and rule version.
- **Done when:** golden-style fixture tests (fixtures we write, not scientific golden values) show
  the right assets and reasons for a hand-made flooded segment.

### Slice 4: incidents, corroboration and verification (spec Epic F/J, §10; AC1, AC3; Stories 4 and 5)
- Clustering by space and time with configurable radius and window. A road segment and the
  reports near it form one incident.
- **Corroboration counts independent underlying sources** (section 3.1).
- **Conflicts:** fresh "dry or cleared" evidence next to fresh "flooded" evidence marks the
  incident `conflict` and puts it in the verify queue. Conflicting evidence is never averaged
  (spec §10.3).
- Confidence uses the spec §10.1 product with **configurable, uncalibrated weights**. The UI shows
  it as low, medium or high plus the reasons it changed, never as a probability.
- Incident drawer, following spec §24: interpretation, confidence, latest observation, trend,
  evidence timeline, affected roads and assets, conflicts, forecast context (GEOGLOWS for the
  district, labelled as forecast), and verify/reject/escalate.
- Verify and status changes are `protected` POSTs written to the existing audit log, with notes.
- Lifecycle events from Appendix A are stored in `pilot_incident_event`.
- **Done when:** scenarios A, B, C and D from spec §29 pass as fast tests.

### Slice 5: replay (spec §30; AC9)
- Replay reads captured raw fetches (section 6) or redacted fixtures in time order and runs the
  same engines with a simulated `as_of`.
- Controls: choose an event, start, pause, 1×/5×/20× speed and jump to a time. Inject a synthetic
  report or a source outage (scenario F).
- Replay output is kept apart from live data: a `run_id`, with nothing written to live tables.
- **Done when:** one captured window replays to the same incident timeline twice, and an injected
  outage shows the health warning.

### Slice 6: CCTV P0 (v0.3 addendum §17 P0)
- Provider-neutral `pilot_camera` registry and `CameraProviderAdapter` interface.
- The camera source is **blocked** (section 2). Until BMA provides metadata, the only allowed path
  is cameras entered by hand from the official BMA viewer, as `EXTERNAL_VIEWER` or `METADATA_ONLY`
  with `cv_allowed=false`.
- Nearest-camera ranking (250–500 m, configurable). Offline or stale cameras never count as
  confirmation.
- An operator can mark a camera CONFIRMS, CONTRADICTS, INCONCLUSIVE or NOT_RELEVANT. That mark is
  a human observation in fusion, kept separate from any model output.
- **Explicitly not built:** snapshot or stream ingestion, computer vision, and any URL discovery
  (P1 and P2 wait for authorisation).

### Slice 7: grounded questions and change summary (spec §16, Epic K/FB-7; AC7; Story 8)
- Built on the existing AI gateway and its allowance and Langfuse tracing (ADR-0035). There is no
  new agent framework.
- Retrieval first: the question is answered from a structured bundle of incidents,
  observations, impacts and source health at `as_of`. The model only phrases the answer. Every
  claim cites observation or incident IDs and times, and labels it as observation, inference,
  forecast or suggestion.
- "What changed since T" is computed **deterministically** from incident events. The AI only
  summarises it.
- Guardrail tests: the answer has no reading that is absent from the bundle, never reads a
  forecast as observed, and never uses evacuation-order language.
- **Done when:** the six example questions in spec §16 return cited answers on a replay fixture.

### Deferred (needs owner or partner decisions)
- Citizen report POST, photos and moderation (spec §6.2, §14), because it needs anonymous public
  access, a retention policy and a moderation owner.
- Direct BMA sensors, water levels and Traffy, which need access agreements.
- CCTV P1 and P2 and computer vision.
- Rainfall and radar (TMD/HII).
- Public mode.
- Snapshot export (DoD 13) could follow slice 4 cheaply if wanted.

## 6. Time-sensitive: capture the current flood now

Bangkok is flooding as of 2–3 October: Floodboard shows 660 uncleared segments, and its reports
include coverage of the Prime Minister's flood meeting. The reports export **only holds about 24
hours**. Replay (AC9), the evaluation metrics (spec §28) and the scenario tests all need a real
event, and this one disappears day by day.

Proposal: from today, a small capture script (`grpcli/floodboard_capture.py`) saves both exports
every 15–30 minutes into the ignored `.local/capture/floodboard/<UTC timestamp>/`, with response
headers and SHA-256.
- The fetches are polite: one request per export per interval, well within the 30-second and
  4-hour cache headers.
- Nothing is committed. Redacted fixtures, with no `text`, are made later from this capture.

## 7. Owner decisions

**Answered on 3 October 2026:**
- **Capture: yes, start now.** `grpcli/floodboard_capture.py` has run every 20 minutes since
  09:28 Bangkok time on 3 October, into `.local/capture/floodboard/`. That is about 2.8 MB per
  pull, roughly 200 MB a day. It is a detached local process; stop it from Task Manager or with
  `Stop-Process`.
- **Exposure assets: import OSM now.** Schools, hospitals and clinics come from OpenStreetMap with
  ODbL attribution and are labelled as OSM. Authoritative BMA lists replace them when they arrive.
- **Access: add Hub operators.** Hub members can view the Bangkok flood mode and verify incidents.
  Admins keep configuration. This needs an ADR and permission-matrix changes in slice 1. The
  River Watch and HAND sections stay Admin-only.
- **First build: slices 1 and 2**, after the existing Pilot work is committed (slice 0).

**Still open:**

The original questions, kept for the record:

1. **Start the capture now?** (Section 6.) Recommended: yes.
2. **Validation corridor (spec §35 Q2).** Which 2–3 districts or corridors? The capture covers all
   of Bangkok either way, so this only shapes testing and the demo.
3. **Exposure data.** May we import OSM schools, hospitals and clinics (ODbL, attribution) for
   slice 3, or wait for authoritative BMA lists?
4. **Who sees it.** Keep it Admin-only, like the rest of the Pilot tab, or add an "operator" view
   for Hub members?
5. **Report text.** Confirm we keep Traffy and news text out of the display until its terms are
   checked.
