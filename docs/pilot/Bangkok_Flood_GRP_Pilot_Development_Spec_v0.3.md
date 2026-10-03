# Bangkok Flood Decision-Support Pilot
## Development-Ready Pilot Specification for SERVIR Global Risk Platform (GRP)

**Status:** Draft v0.2 — Floodboard-integrated architecture  
**Target:** Bangkok Metropolitan Administration (BMA) pilot  
**Purpose:** Demonstrate a reusable, evidence-driven flood situation and decision-support capability that combines official sensors, citizen observations, CCTV, weather/hydrology, exposure data, and AI-assisted decision workflows.

---

## 1. Executive Summary

Bangkok already has substantial flood information: road flood sensors, water-level observations, rainfall data, CCTV, flood-risk points, Traffy Fondue citizen reports, and existing dashboards. The pilot should therefore **not build another map-only dashboard**.

The proposed pilot adds the missing operational layer:

> **Observe → Validate → Fuse → Assess Impact → Recommend/Support a Decision → Track Change**

The product should answer practical questions such as:

- Where is flooding happening **now**, and how fresh/reliable is the evidence?
- Which roads are passable by motorcycle, sedan, pickup, truck, or emergency vehicle?
- Which schools, hospitals, communities, shelters, transit nodes, and other critical assets may be affected?
- Which reports are corroborated by sensors, CCTV, multiple citizens, or official sources?
- What changed during the last 30 minutes / 3 hours / 6 hours?
- Which locations should an operator verify first?
- Where should preparedness or response resources be prioritized?
- What evidence supports each conclusion?

The pilot combines the simplicity of a crowdsourced flood application with the broader GRP architecture: hazard + exposure + vulnerability + consequence + decision.

---

# 2. Pilot Vision

## 2.1 Product statement

**For Bangkok flood operators and responders who need a rapidly changing operational picture, the Bangkok Flood Decision-Support Pilot combines authoritative observations, community reports, CCTV and exposure data into an evidence-backed map and decision workflow, so they can identify affected assets and access constraints without manually reconciling multiple systems.**

## 2.2 Design principles

1. **Decision first, map second.**
2. **Evidence before AI.**
3. **Every observation has time, source and confidence.**
4. **No permanent truth from transient flood reports.**
5. **Never hide uncertainty.**
6. **Official sources remain authoritative where applicable.**
7. **Citizen observations supplement rather than replace official observations.**
8. **AI summarizes and queries evidence; it does not invent flood conditions.**
9. **Every generated conclusion must be traceable to underlying evidence.**
10. **Build Bangkok as a configurable pilot, not a Bangkok-only codebase.**

---

# 3. Problem Definition

Bangkok flood information is distributed across multiple systems and data owners. Individual systems may answer parts of the problem, but operational users still need to mentally combine:

- rainfall,
- road flood sensors,
- canal/water levels,
- historical flood-risk locations,
- CCTV,
- citizen reports,
- road network conditions,
- critical assets,
- weather forecasts,
- district boundaries,
- shelters and response facilities.

The resulting problem is not simply “lack of data.” It is:

> **lack of a shared, current, evidence-linked interpretation of what the data means for a decision.**

---

# 4. Pilot Scope

## 4.1 Recommended geographic scope

Do not start with all 50 districts operationally.

Use a technically city-wide ingestion architecture but choose **2–3 operational validation districts/corridors** representing different flood patterns.

Selection criteria:

- recurring pluvial flooding,
- useful density of sensors/CCTV,
- meaningful road network,
- presence of schools/hospitals/communities,
- availability of historical Traffy reports,
- willingness of local operational stakeholders to validate.

The pilot configuration must allow districts to be changed without code changes.

## 4.2 Hazard scope

**MVP hazard: urban/pluvial flooding and road inundation.**

Explicitly out of MVP:

- full riverine hydraulic simulation,
- storm surge modeling,
- landslide,
- drought,
- earthquake,
- long-term climate adaptation modeling.

Architecture should remain multi-hazard compatible.

## 4.3 Primary personas

### P1 — BMA/District Flood Operator
Needs a consolidated live operational picture and prioritization.

### P2 — Emergency/Rescue Coordinator
Needs access/passability and affected-population/asset information.

### P3 — District Officer / Field Verifier
Needs a queue of uncertain/high-impact locations requiring verification.

### P4 — Public User
Needs simple flood condition, road access and reporting.

### P5 — GRP/Hub Analyst
Needs evidence, provenance, data quality and reusable workflows.

---

# 5. Core Decisions to Support

## D1 — Road accessibility

**Question:** Can vehicles safely use this road segment?

Inputs:
- road-water sensor,
- citizen depth report,
- CCTV,
- recent official report,
- terrain/context,
- vehicle category.

Output:
- Unknown
- Passable
- Passable with caution
- Likely impassable
- Confirmed impassable

Always show confidence and evidence.

## D2 — Critical asset exposure

**Question:** Which critical assets may currently be affected or lose access?

Assets:
- schools,
- hospitals/clinics,
- fire/rescue stations,
- shelters,
- transit stations,
- markets,
- government facilities,
- optionally vulnerable communities.

Output:
- asset,
- flood evidence nearby/intersecting,
- access status,
- latest evidence time,
- confidence,
- recommended verification/action.

## D3 — Verification prioritization

**Question:** What should field staff verify first?

Priority increases with:
- high potential impact,
- stale or conflicting evidence,
- critical asset proximity,
- rapidly rising observations,
- road-network importance,
- absence of CCTV/sensor confirmation.

## D4 — Operational change

**Question:** What changed since the previous operational period?

Examples:
- 12 newly affected road segments,
- 4 locations worsened,
- 7 locations receded,
- 2 hospital access routes changed,
- sensor/CCTV conflicts requiring verification.

---

# 6. Target User Journey

## 6.1 Operator

1. Open Bangkok situation view.
2. See active flood incidents ranked by operational significance.
3. Filter by district / time / severity / confidence / source.
4. Select an incident.
5. Inspect evidence timeline.
6. View nearby sensors, citizen photos, CCTV and official reports.
7. See affected roads/assets.
8. Request an AI-supported summary or question.
9. Verify/acknowledge/escalate incident.
10. Export/share situation snapshot.

## 6.2 Citizen report

1. Open report page without mandatory account.
2. Share GPS or select location.
3. Choose water-depth band.
4. Choose trend.
5. Choose vehicle passability.
6. Upload photo (optional but increases confidence).
7. Add short note.
8. Submit.
9. Report appears as **unverified observation**.
10. Confidence changes as corroborating evidence arrives.

Suggested depth bands:

- Dry / receded
- < 10 cm
- 10–30 cm
- 30–50 cm
- 50–100 cm
- > 100 cm
- Unknown depth / visual only

Trend:

- Rising
- Stable
- Falling
- Unknown

Passability:

- Motorcycle
- Sedan
- Pickup/SUV
- High-clearance/emergency vehicle
- Impassable
- Unknown

---

# 7. Information Architecture

Main navigation:

1. **Situation**
2. **Map**
3. **Incidents**
4. **Road Access**
5. **Critical Assets**
6. **Reports**
7. **Evidence / Data Sources**
8. **AI Assistant**
9. **Admin / Configuration**

Public mode can expose only Situation, Map, Road Access and Report Flooding.

---

# 8. Data Architecture

## 8.1 Canonical observation model

All sources should normalize into a common observation structure.

```json
{
  "observation_id": "uuid",
  "hazard_type": "flood",
  "observation_type": "road_water_depth",
  "source_type": "sensor|citizen|cctv|official|model|media",
  "source_name": "BMA_DDS",
  "source_record_id": "external-id",
  "observed_at": "ISO-8601",
  "ingested_at": "ISO-8601",
  "geometry": {},
  "value": 32,
  "unit": "cm",
  "category": "30-50cm",
  "trend": "rising",
  "quality_status": "raw|validated|rejected|expired",
  "confidence": 0.82,
  "provenance": {},
  "evidence": [],
  "license": "",
  "metadata": {}
}
```

## 8.2 Incident model

Observations are evidence. Incidents are interpreted operational objects.

```json
{
  "incident_id": "uuid",
  "hazard_type": "flood",
  "status": "active|monitoring|receded|closed",
  "severity": "minor|moderate|major|severe",
  "confidence": 0.87,
  "first_observed_at": "",
  "last_observed_at": "",
  "geometry": {},
  "observation_ids": [],
  "affected_road_ids": [],
  "affected_asset_ids": [],
  "district_ids": [],
  "summary": "",
  "verification_status": "unverified|corroborated|officially_verified"
}
```

## 8.3 Asset model

Use a generic critical-asset schema:

```text
asset_id
asset_type
name
geometry
source
source_id
district
attributes
criticality
opening_hours (optional)
capacity (optional)
vulnerability metadata (controlled)
```

## 8.4 Road segment model

Road analysis must use segments rather than points.

```text
road_segment_id
geometry
road_name
road_class
direction
criticality
current_status
max_depth_cm
confidence
last_updated
supporting_observations[]
```

---

# 9. Bangkok Data Sources

## Tier A — Authoritative / operational

### BMA road flood and water-level systems
Use BMA/DDS observations where public/API access and terms permit.

Potential information:
- road flood sensor depth,
- water levels,
- station metadata,
- timestamps,
- station status.

### BMA Open Data / data.go.th
Water level data is published at 5-minute intervals with historical records.

### BMA flood-risk points
Use official flood-risk/watch locations as contextual/prior-risk data, **not proof of current flooding**.

### BMA CCTV
Use camera metadata and approved image/view links where technically and legally permitted.

## Tier B — Government/civic operational reports

### Traffy Fondue
Potential fields:
- incident location,
- flood category,
- report time,
- text,
- status,
- photo,
- responsible organization.

Treat a complaint as an observation/report, not automatically as measured flood depth.

## Tier C — Environmental data

Candidate integrations:
- rainfall observations,
- weather radar,
- short-term precipitation forecast,
- ThaiWater/HII water observations,
- TMD products where available/licensed.

## Tier D — Exposure/reference data

- BMA district/subdistrict boundaries
- OpenStreetMap roads and POIs
- authoritative BMA facilities where available
- schools
- hospitals
- shelters
- emergency facilities
- transit infrastructure
- population/building datasets appropriate to SERVIR licensing/governance

---

# 10. Evidence Fusion

The system must not treat all sources equally.

## 10.1 Evidence dimensions

Each observation receives components:

- **source reliability**
- **freshness**
- **spatial relevance**
- **measurement quality**
- **corroboration**
- **internal consistency**

Example conceptual confidence:

```text
confidence =
  source_weight
  × freshness_factor
  × quality_factor
  × corroboration_factor
```

Do not expose this as scientifically calibrated probability until validated.

## 10.2 Initial source weighting

Configuration example only:

| Source | Initial trust behavior |
|---|---|
| calibrated official sensor | high |
| official field report | high |
| CCTV visually verified | high |
| multiple independent citizen reports | medium-high |
| citizen report + photo | medium |
| citizen report only | low-medium |
| social/media signal | low until verified |
| forecast/model | separate predicted-state confidence |

Weights must be configurable and validated with BMA/subject-matter experts.

## 10.3 Corroboration

Examples:

```text
Citizen report 40 cm
+ nearby road sensor 37 cm
+ CCTV shows inundation
= strongly corroborated incident
```

Conflict:

```text
Citizen report 80 cm
+ sensor 0 cm
+ CCTV appears dry
= conflict / verification required
```

Never silently average conflicting evidence.

---

# 11. Freshness and Expiry

Flood observations decay quickly.

Suggested MVP rules:

| Age | Display |
|---|---|
| 0–30 min | current |
| 30–120 min | recent |
| 2–6 hr | aging |
| 6–12 hr | stale |
| >12 hr | expired for live-state inference unless refreshed |

Different source types can have different TTLs.

An incident can remain open while individual observations expire.

The UI must display:
- observed time,
- source,
- freshness,
- last corroborated time.

---

# 12. Flood Severity and Road Passability

Do **not** universally map water depth to vehicle safety without validation.

For the pilot, implement a configurable rules engine:

```yaml
passability_rules:
  sedan:
    thresholds: TBD_BY_BMA
  pickup:
    thresholds: TBD_BY_BMA
  emergency_vehicle:
    thresholds: TBD_BY_BMA
```

Other factors may override depth:
- moving water,
- hidden potholes/manholes,
- underpass,
- current/flow,
- road closure,
- operator confirmation.

Safety language should say “reported/estimated passability,” not guarantee safe passage.

---

# 13. Critical Asset Impact Engine

## 13.1 Spatial relationships

Calculate:

- asset inside observed/estimated flood geometry,
- asset within configurable buffer,
- nearest affected road,
- access route intersects affected road,
- number of active incidents nearby.

## 13.2 Impact states

```text
UNKNOWN
WATCH
POTENTIALLY_AFFECTED
ACCESS_CONSTRAINED
CONFIRMED_AFFECTED
RECOVERING
```

## 13.3 MVP consequence record

```json
{
  "asset_id": "...",
  "incident_id": "...",
  "impact_type": "direct_flood|access_constraint|nearby_flood",
  "impact_status": "potential|corroborated|confirmed",
  "confidence": 0.78,
  "evidence_ids": [],
  "computed_at": ""
}
```

---

# 14. Citizen Reporting and Anti-Abuse

MVP should minimize friction but protect data quality.

Controls:

- rate limiting,
- CAPTCHA/risk scoring where needed,
- image size/type validation,
- duplicate-location detection,
- repeated-device anomaly detection without invasive identity tracking,
- report flagging,
- moderator queue,
- profanity/content moderation for notes,
- EXIF handling policy,
- privacy warning before photo upload.

Do not publicly expose reporter identity.

Photos should avoid unnecessary faces/license plates where possible. Define retention and moderation policy before public launch.

---

# 15. CCTV Integration

MVP levels:

### Level 1
Show camera locations and link to official viewer.

### Level 2
Embed approved current feeds/snapshots.

### Level 3
Computer-vision assistance:
- water present/not present,
- approximate road inundation category,
- visibility/quality.

Level 3 must remain advisory until validated.

Every machine interpretation must preserve:
- camera,
- timestamp,
- model version,
- confidence,
- snapshot/evidence reference.

---

# 16. AI / GRP Assistant

AI is a query and synthesis layer over structured evidence.

## Allowed MVP questions

- “Which roads in District X have worsened in the last 2 hours?”
- “Which hospitals may have constrained access?”
- “Show evidence for Rama IX Road incident.”
- “What changed since 06:00?”
- “Which high-impact incidents have low confidence?”
- “Summarize current flood situation for the duty officer.”

## Required grounding

AI responses must retrieve from:
- incidents,
- observations,
- assets,
- road status,
- source metadata.

Response format should include:

```text
Answer
Confidence / uncertainty
Evidence
Observed time
Source(s)
Suggested next verification/action
```

## AI guardrails

The assistant must not:
- invent sensor readings,
- claim an asset is flooded solely from proximity without qualification,
- convert a forecast into an observed condition,
- hide conflicting evidence,
- issue evacuation orders,
- override official authority.

---

# 17. Proposed Technical Architecture

```text
                       DATA SOURCES

 BMA Sensors    Traffy    CCTV    Weather    ThaiWater
      |            |        |        |           |
      +------------+--------+--------+-----------+
                           |
                    Ingestion Adapters
                           |
                    Raw Evidence Store
                           |
                Validation / Normalization
                           |
                    Observation Store
                    PostGIS / Timeseries
                           |
              +------------+-------------+
              |                          |
        Evidence Fusion             Asset/Network
        Incident Engine             Impact Engine
              |                          |
              +------------+-------------+
                           |
                     Operational API
                           |
        +------------------+------------------+
        |                  |                  |
      Web Map         Operator UI        GRP AI/MCP
        |                  |                  |
    Public View       Verification        Q&A/Summary
```

---

# 18. Suggested Technology Stack

Keep components replaceable.

## Frontend
- Next.js / React
- TypeScript
- MapLibre GL JS or equivalent open mapping client
- responsive PWA design

## Backend
- Python FastAPI **or** TypeScript/NestJS
- REST API initially
- WebSocket/SSE for live updates if justified

## Spatial database
- PostgreSQL + PostGIS

## Cache/queue
- Redis
- lightweight job queue initially; Kafka only if scale requires it

## Object storage
- S3-compatible storage for citizen evidence/images

## Geospatial processing
- PostGIS
- GeoPandas/Shapely for offline/batch tasks
- optional GeoServer/QGIS Server only where OGC service publishing is required

## Observability
- structured logs
- metrics
- traces
- ingestion health dashboard
- source latency/failure monitoring

## Deployment
- containerized
- CI/CD
- staging + production
- infrastructure configuration separated from application code

---

# 19. API Design

Minimum endpoints:

```text
GET  /api/v1/situation
GET  /api/v1/incidents
GET  /api/v1/incidents/{id}
GET  /api/v1/observations
POST /api/v1/observations/citizen
GET  /api/v1/roads/status
GET  /api/v1/assets
GET  /api/v1/assets/{id}/impact
GET  /api/v1/cameras
GET  /api/v1/sources/status

POST /api/v1/incidents/{id}/verify
POST /api/v1/incidents/{id}/status

POST /api/v1/assistant/query
```

Filters:

```text
bbox
district
since
until
source
severity
confidence
freshness
status
asset_type
```

---

# 20. Provenance Requirements

Every derived object must be explainable.

Example:

```text
Road Segment R123
Status: Likely impassable
Updated: 14:35

Evidence:
1. BMA sensor S22 — 46 cm — 14:32
2. Citizen report C819 — 30–50 cm — photo — 14:29
3. CCTV C14 — visually corroborated — 14:31

Derived by:
RoadPassabilityRule v0.3

Confidence:
High

Known conflict:
None
```

This is a core GRP capability, not optional metadata.

---

# 21. Data Governance

For each source maintain:

```text
Source owner
Dataset name
Purpose
Access method
License/terms
Update frequency
Expected latency
Spatial coverage
Schema/version
Data steward
Quality notes
Retention
Redistribution permission
PII classification
```

Create a data-source registry before production deployment.

---

# 22. Security

MVP roles:

```text
PUBLIC
FIELD_REPORTER
OPERATOR
VALIDATOR
ADMIN
```

Controls:
- authentication for staff functions,
- RBAC,
- audit log,
- rate limits,
- secure secrets management,
- TLS,
- image upload validation,
- API input validation,
- dependency scanning,
- backups,
- rollback procedure.

Public reporting can be anonymous while privileged verification cannot.

---

# 23. Non-Functional Requirements

## Availability
Target pilot operational availability: **99.5% during monitored pilot periods**.

## Performance
- map initial useful render < 3 seconds on typical Bangkok mobile connection where practical,
- common API p95 < 1 second excluding upstream dependencies,
- citizen report acknowledgement < 3 seconds,
- upstream observation available internally within 5 minutes of source publication where source supports it.

## Scalability
Architecture should handle burst traffic during severe rainfall.

Initial target:
- 10k concurrent public viewers,
- 100 reports/minute burst,
- millions of historical observations.

Load-test assumptions before launch.

## Resilience
Failure of one upstream source must not take down the application.

Show source health explicitly.

---

# 24. UX Requirements

## Situation page

Top cards:
- active incidents,
- severe/major incidents,
- roads constrained,
- critical assets potentially affected,
- reports last hour,
- sources degraded/offline.

Map colors must represent **operational state**, while confidence/freshness should have separate visual treatment.

Never use the same color dimension for severity and confidence.

## Incident drawer

Show:
1. current interpretation,
2. confidence,
3. latest observation,
4. trend,
5. evidence timeline,
6. nearby CCTV,
7. affected roads,
8. affected assets,
9. conflicts,
10. verify/escalate action.

---

# 25. MVP Backlog

## Epic A — Foundation
- repository and branching strategy
- CI/CD
- environments
- PostGIS
- base map
- authentication/RBAC
- audit logging

## Epic B — Bangkok reference data
- district boundaries
- road network
- critical assets
- source registry

## Epic C — BMA observations
- sensor ingestion
- water-level ingestion
- station metadata
- freshness monitoring
- ingestion failure handling

## Epic D — Traffy integration
- flood-report ingestion
- geometry normalization
- timestamp/status normalization
- image/evidence linking
- duplicate handling

## Epic E — Citizen reporting
- location
- depth
- trend
- passability
- photo
- report confirmation
- moderation

## Epic F — Incident engine
- spatial clustering
- temporal clustering
- freshness
- corroboration
- conflicts
- confidence
- incident lifecycle

## Epic G — Road access
- road segmentation
- observation-to-road association
- configurable passability
- road status API
- road status map

## Epic H — Critical assets
- asset ingestion
- proximity/intersection
- access constraints
- impact state

## Epic I — CCTV
- camera metadata
- camera map
- official viewer integration
- evidence linking

## Epic J — Operator workflow
- incident queue
- evidence view
- verify/reject
- notes
- status changes
- audit trail

## Epic K — GRP AI
- grounded retrieval
- operational questions
- evidence citations
- uncertainty
- change summary

## Epic L — Analytics and evaluation
- ground-truth sample
- precision/recall
- latency
- report usefulness
- operator feedback

---

# 26. Suggested 12-Week Pilot Plan

## Phase 0 — Week 1–2: Readiness

Deliver:
- decision/use-case confirmation,
- pilot geography,
- source agreements,
- data inventory,
- architecture C4,
- canonical schema,
- baseline UX,
- acceptance criteria,
- security/privacy review.

**Gate:** required data sources demonstrably accessible.

## Phase 1 — Week 3–4: Observe

Deliver:
- base map,
- BMA sensor integration,
- Traffy integration,
- source/freshness display,
- raw observation map,
- source-health monitoring.

**Demo:** “Show what is happening and where the evidence came from.”

## Phase 2 — Week 5–6: Community + Validation

Deliver:
- citizen reporting,
- photos,
- freshness/expiry,
- clustering,
- corroboration/conflict,
- operator verification.

**Demo:** “Combine independent evidence into an incident.”

## Phase 3 — Week 7–8: Consequence

Deliver:
- road-segment status,
- critical assets,
- access constraints,
- incident severity,
- prioritized incident queue.

**Demo:** “Tell me what the flood affects.”

## Phase 4 — Week 9–10: Decision Support

Deliver:
- AI evidence Q&A,
- change detection,
- duty-officer summary,
- evidence citations,
- export/share snapshot.

**Demo:** “What changed, what matters, and why?”

## Phase 5 — Week 11–12: Validation and Handover

Deliver:
- live-rain-event test or replay,
- performance/load test,
- accuracy evaluation,
- operator usability test,
- lessons learned,
- backlog,
- scale-out recommendation,
- reusable GRP configuration package.

**Gate:** pilot decision review.

---

# 27. Acceptance Criteria

The pilot succeeds only if it demonstrates decisions, not number of layers.

## AC1 — Evidence traceability
For 100% of system-derived live incident states, an operator can inspect source evidence and timestamps.

## AC2 — Freshness
Expired observations cannot silently drive a “current” state.

## AC3 — Conflicts
Conflicting evidence is visible and creates a verification need.

## AC4 — Road impact
The system can associate a flood incident with affected road segments.

## AC5 — Critical asset impact
The system can identify potentially affected critical assets with an explicit reason.

## AC6 — Citizen contribution
A valid citizen report appears within target latency and is clearly marked unverified until corroborated/verified.

## AC7 — AI grounding
Operational AI answers cite the internal evidence used and communicate uncertainty.

## AC8 — Source failure
Loss of one data feed does not break the platform and is visible to operators.

## AC9 — Replay
A historical/replayed flood event can reproduce the operational timeline for evaluation.

## AC10 — Configurability
At least one second district can be enabled largely through configuration/data rather than code branching.

---

# 28. Evaluation Framework

## Technical metrics
- ingestion latency,
- uptime,
- API latency,
- failed source pulls,
- duplicate rate,
- map performance.

## Data-quality metrics
- sensor completeness,
- timestamp validity,
- location accuracy,
- stale-data rate,
- citizen-report validation rate.

## Incident metrics
Against manually reviewed samples:
- true positive incidents,
- false positives,
- missed incidents,
- time-to-detection,
- time-to-corroboration,
- time-to-resolution.

## Decision metrics
Measure whether the pilot reduces:
- time to locate evidence,
- time to determine road condition,
- time to identify affected assets,
- number of systems an operator must manually inspect.

## User metrics
- task completion,
- operator confidence in evidence,
- usefulness rating,
- citizen reporting completion rate.

---

# 29. Pilot Test Scenarios

## Scenario A — Sensor + citizen corroboration
Sensor rises to flood threshold. Citizen submits photo and similar depth.

Expected:
- observations cluster,
- confidence increases,
- road state changes,
- evidence timeline visible.

## Scenario B — False citizen report
Citizen reports severe flooding but sensor and fresh CCTV indicate dry road.

Expected:
- no automatic road closure,
- conflict flagged,
- report enters verification queue.

## Scenario C — No sensor coverage
Multiple independent citizen reports + CCTV show flooding.

Expected:
- incident can become corroborated without a physical sensor,
- provenance clearly indicates evidence basis.

## Scenario D — Stale flooding
Severe report is six hours old with subsequent dry evidence.

Expected:
- old report loses influence,
- incident transitions to receded/monitoring.

## Scenario E — Hospital access
Flooded road intersects primary access to a hospital.

Expected:
- hospital marked access-constrained,
- system explains road/evidence relationship,
- operator sees alternate network context where available.

## Scenario F — Data source outage
BMA sensor feed stops updating.

Expected:
- feed health warning,
- timestamps remain visible,
- stale readings do not masquerade as live.

---

# 30. Replay / Simulation Mode

This is essential because development cannot depend on waiting for rain.

Build a replay mechanism that can ingest historical observations using simulated current time.

Capabilities:

```text
select historical event
start/pause
1x / 5x / 20x speed
jump to timestamp
inject synthetic citizen report
inject source outage
inspect resulting incidents
```

Replay becomes:
- development test harness,
- demo tool,
- training environment,
- regression suite.

---

# 31. What Not to Build in Pilot

Avoid:

- city-scale hydraulic digital twin,
- custom weather model,
- autonomous evacuation decisions,
- complex computer vision before data fusion works,
- blockchain,
- custom GIS server unless justified,
- separate mobile native apps,
- broad multi-hazard support,
- elaborate AI agent orchestration,
- dozens of dashboards.

The pilot must prove the chain:

> **evidence → trusted incident → consequence → decision**

---

# 32. GRP Reusability

Bangkok-specific values must live in configuration/adapters.

```text
/core
  observation
  incident
  confidence
  provenance
  impact
  assistant

/adapters
  bma_dds
  traffy
  thaiwater
  weather
  cctv

/config
  bangkok.yaml

/ui
  common components
```

A future hub should replace adapters/configuration rather than rewrite core logic.

Example:

```text
Bangkok
  BMA sensors + Traffy + CCTV

Cambodia
  national/local sources + community reports

South Asia
  local hydromet + flood model + exposure

Same:
  Observation → Incident → Impact → Decision
```

---

# 33. C4-Level Architecture to Produce

Before implementation, create:

## Context
GRP Bangkok Pilot, BMA operators, public reporters, BMA systems, Traffy, weather/hydrology sources.

## Container
- Web/PWA
- API
- ingestion workers
- evidence/incident engine
- AI service
- PostGIS
- object storage
- cache/queue
- observability

## Component
Especially:
- source adapters,
- normalizer,
- deduplicator,
- freshness evaluator,
- corroboration engine,
- incident lifecycle,
- road impact engine,
- asset impact engine,
- provenance service.

---

# 34. Key Risks

| Risk | Mitigation |
|---|---|
| upstream API changes | adapter isolation + contract tests |
| unclear redistribution rights | source registry/legal review |
| false citizen reports | corroboration + moderation + rate limiting |
| stale sensor data | explicit freshness/health |
| operator trusts AI too much | evidence-first UI + citations |
| flood depth ≠ safe driving | configurable rules + safety caveats |
| duplicated BMA products | focus on evidence fusion and decisions |
| scope explosion | strict urban-flood MVP |
| no rain during pilot | replay mode |
| Bangkok-specific architecture | configuration-driven core |

---

# 35. Open Decisions for Pilot Kickoff

1. Who is the primary operational owner?
2. Which 2–3 districts/corridors are validation areas?
3. Which exact decision is MVP #1?
4. Which BMA APIs/data feeds have approved production access?
5. Can Traffy data/photos be reused and displayed?
6. What CCTV usage is permitted?
7. What official vehicle/passability rules should be used?
8. Which critical asset datasets are authoritative?
9. What constitutes official verification?
10. What public information can be displayed?
11. Required Thai/English support?
12. Required retention period for citizen evidence?
13. Who owns moderation?
14. What is the incident escalation workflow?
15. What success threshold leads to city-wide/hub scale-out?

---

# 36. Recommended MVP #1

The strongest first end-to-end increment is:

> **“Given a Bangkok road/corridor, determine whether flooding is currently affecting access, show the evidence and confidence, identify nearby critical assets, and explain what changed recently.”**

This increment forces the platform to prove:

- live ingestion,
- geospatial normalization,
- freshness,
- citizen reporting,
- evidence fusion,
- road consequence,
- critical-asset exposure,
- provenance,
- AI grounding.

It is small enough to validate but deep enough to demonstrate GRP's value beyond a conventional flood map.

---

# 37. Definition of Done for the Pilot

The Bangkok pilot is complete when a BMA/GRP operator can:

1. open one interface,
2. see current flood incidents,
3. understand data freshness,
4. inspect supporting evidence,
5. identify conflicting evidence,
6. see affected road segments,
7. see potentially affected critical assets,
8. submit/receive a citizen observation,
9. verify or reject an incident,
10. ask a grounded operational question,
11. receive an evidence-linked answer,
12. replay a historical event,
13. export a situation snapshot,
14. audit how the system reached its state.

At that point, the product has demonstrated more than a map.

It has demonstrated a reusable **risk-to-decision capability**.

---

# 38. Public Sources / Initial Technical References

The pilot design should validate access conditions and technical contracts directly with each data owner before production use.

- Bangkok road flood monitoring system: https://floodbangkok.bangkok.go.th/road-flood
- Thailand Open Government Data — Bangkok water-level dataset: https://data.go.th/th/dataset/flood
- Bangkok flood-risk map: https://cpudgiportal.bangkok.go.th/
- Traffy Fondue / BMA public complaint data: https://policy.bangkok.go.th/traffy/
- Existing BMA Flood Risk Management Platform: https://floodmanagement.bangkok.go.th/
- Reference open-source Bangkok flood checker: https://github.com/ipunn/BKK-Road-Flood-Checker-2026
- Floodboard concept/reference: https://www.floodboard.org/en/about

**Important:** URLs and endpoints are discovery references, not an assumption of unrestricted production/API reuse. Confirm terms, authentication, service-level expectations and licensing with data owners.

---

## Appendix A — Minimal Event Taxonomy

```text
FLOOD_OBSERVED
FLOOD_REPORTED
WATER_LEVEL_CHANGED
ROAD_STATUS_CHANGED
ASSET_IMPACT_CHANGED
EVIDENCE_CORROBORATED
EVIDENCE_CONFLICT
OBSERVATION_EXPIRED
INCIDENT_CREATED
INCIDENT_VERIFIED
INCIDENT_RECEDING
INCIDENT_CLOSED
SOURCE_DEGRADED
SOURCE_RECOVERED
```

## Appendix B — Minimum Provenance Fields

```text
source_id
source_owner
source_record_id
source_url/reference
observed_at
retrieved_at
processing_steps
rule/model_version
license
confidence
validation_status
```

## Appendix C — First Sprint Candidate Stories

### Story 1
As an operator, I can see BMA road flood observations on a Bangkok map with reading time and source so that I can distinguish live from stale data.

### Story 2
As an operator, I can overlay Traffy flood reports and inspect their evidence so that I can compare sensor and citizen/complaint information.

### Story 3
As a citizen, I can submit a geolocated flood-depth/trend report so that field information becomes available quickly.

### Story 4
As an operator, I can see when multiple observations refer to the same likely incident so that I do not manually reconcile duplicate points.

### Story 5
As an operator, I can inspect an evidence timeline for an incident so that I understand why its current status was assigned.

### Story 6
As a system, I expire stale evidence according to configurable rules so that old reports do not appear current.

### Story 7
As an operator, I can see nearby critical assets and affected road segments so that I can assess consequences.

### Story 8
As an operator, I can ask “what changed in the last two hours?” and receive a grounded summary with evidence references.

---

**End of specification**


# Appendix H — v0.2 Implementation Delta: Floodboard Integration

## H.1 New Epics

### EPIC FB-1 — Floodboard Evidence Adapter
**Goal:** Ingest Floodboard open outputs without coupling GRP domain logic to Floodboard.

Acceptance criteria:
- scheduled and on-demand retrieval;
- CORS/server-side retrieval supported as appropriate;
- schema validation and graceful failure;
- original payload hash retained for audit;
- `source=floodboard` and attribution metadata retained;
- retrieval and observation timestamps are distinct;
- duplicate observations are idempotently handled;
- stale feed does not masquerade as current truth.

### EPIC FB-2 — Canonical Evidence Normalization
Map Floodboard road/report states into canonical GRP concepts:

```text
Observation
  id
  source
  source_record_id
  observed_at
  retrieved_at
  geometry
  phenomenon
  value
  unit
  categorical_state
  vehicle_class
  source_type
  source_confidence
  freshness_state
  evidence_uri
  license
  attribution
  raw_payload_hash
```

### EPIC FB-3 — Independent Authoritative Cross-Check
For a limited pilot geography, ingest selected BMA/HII/forecast feeds independently. Compare them with Floodboard-derived conditions. The purpose is not to second-guess Floodboard; it is to evaluate GRP provenance, resilience and confidence behavior.

### EPIC FB-4 — Exposure & Accessibility
Intersect affected road geometries with critical assets and road-network accessibility. Calculate direct intersection and access consequences separately. A hospital is not considered “flooded” merely because its access road is affected.

### EPIC FB-5 — Consequence Ranking
Generate ranked *attention candidates*, not automated emergency orders. Each item must expose evidence, calculation basis, uncertainty and last-update time.

### EPIC FB-6 — Forecast/Scenario Enrichment
Add rainfall/hydrologic forecast evidence as a separate future-looking layer. Never mix observed condition and forecast condition without explicit labels.

### EPIC FB-7 — Grounded AI/MCP Decision Interface
AI answers must be generated from structured GRP evidence. Every material answer should return source IDs/timestamps and distinguish observation, inference, forecast and recommendation/support text.

## H.2 Revised 12-Week Delivery Sequence

| Weeks | Outcome |
|---|---|
| 1–2 | Confirm decision users/questions; Floodboard adapter spike; licensing/attribution review; canonical schema |
| 3–4 | Evidence gateway + PostGIS store + provenance/freshness; ingest critical assets |
| 5–6 | Road/asset spatial joins + access consequence prototype; historical/replay fixtures |
| 7–8 | Independent BMA/HII checks + confidence rules + operator evidence panel |
| 9–10 | Forecast enrichment + consequence ranking + grounded AI/MCP query path |
| 11 | Operational scenario exercises, false-positive/false-negative review, performance/NFR tests |
| 12 | Pilot demo, evidence-based evaluation, hub portability test, scale/no-scale decision |

## H.3 Demo Scenario
The steering demo should avoid a generic “show me the flood map” flow. Demonstrate a decision chain:

1. Select an actively affected Bangkok corridor from Floodboard evidence.
2. Show source provenance and freshness.
3. Show nearby critical assets and affected access paths.
4. Show population/community exposure where data supports it.
5. Add forecast context, explicitly labelled as forecast.
6. Ask GRP: “What requires attention in this corridor and why?”
7. GRP returns ranked consequences with evidence links and uncertainty.
8. Operator opens the evidence panel and verifies the answer.
9. Replay an updated observation and show the consequence/priority change.
10. Switch configuration to a mock second hub adapter to demonstrate portability.

## H.4 Key Evaluation Metrics
- Evidence ingestion latency (p50/p95).
- Percentage of decision claims with traceable provenance.
- Stale-evidence detection rate.
- Spatial join precision on test fixtures.
- Access-impact precision/recall against manually reviewed scenarios.
- AI grounded-claim rate.
- Operator time to answer the selected decision question vs current workflow.
- Number of Bangkok-specific components required to change for second-hub deployment.

## H.5 Strategic Positioning

```text
Floodboard:   What is happening on the ground?
GRP:          What is exposed, what are the consequences, what may happen next,
              and what evidence should the decision-maker examine?
SERVIR value: Reusable regional capability that can combine local operational
              evidence with EO, forecasts, exposure and decision workflows.
```

This separation should be maintained in product messaging, architecture and backlog prioritization.

---

# v0.3 Addendum — Live CCTV Visual Corroboration

## 1. Purpose

CCTV is promoted from a passive external link to a first-class **visual evidence source** in the Bangkok pilot. Its primary purpose is corroboration: confirm or challenge road-flood observations from BMA sensors, Floodboard, citizen reports, rainfall/water-level feeds, and model outputs.

CCTV must not be treated as ground truth by itself. A camera can be offline, stale, obstructed, pointed away from the road, too dark, or unsuitable for estimating depth. Every CCTV-derived observation therefore carries freshness, visibility, provenance and confidence metadata.

## 2. Verified Bangkok CCTV/Data Situation

As of the v0.3 design update:

- BMA Drainage and Sewerage Department's road-flood system exposes a CCTV layer alongside road/tunnel flood sensors.
- Individual BMA flood-sensor pages can identify associated CCTV camera IDs and names. Example: sensor `FL.YNW.02` is associated with `CM2-YW-32-C1` and `CM2-YW-32-C2`.
- BMA camera status can be unavailable/broken; this must be represented explicitly rather than silently interpreted as no flooding.
- A public community implementation, `BKK-Road-Flood-Checker-2026`, catalogs roughly 230 BMA public CCTV locations and links to BMA's viewer. Its documented limitation is that the BMA viewer does not expose a stable per-camera deep link known to that project.
- Therefore the pilot MUST support multiple camera access modes rather than assume a raw video URL is always available.

## 3. CCTV Access Modes

Each camera is assigned one of these access modes:

| Mode | Meaning | GRP behavior |
|---|---|---|
| `LIVE_STREAM` | Authorized/public stream endpoint available (e.g. HLS/WebRTC/MJPEG) | Render live player and optionally sample frames |
| `SNAPSHOT` | Authorized/public current-image endpoint | Refresh image at policy-compliant interval |
| `EMBED` | Provider permits embedding a viewer | Embed provider viewer; CV only if technically and legally permitted |
| `EXTERNAL_VIEWER` | Only provider viewer/page is available | Open viewer with camera metadata; no claim of direct live ingestion |
| `METADATA_ONLY` | Camera location/ID known but image unavailable | Show camera location/status only |
| `OFFLINE` | Provider reports camera unavailable | Exclude from visual confirmation; retain outage evidence |

Raw stream URLs MUST NOT be reverse-engineered around access controls or provider restrictions. Only documented/public/authorized delivery mechanisms are eligible for automated ingestion.

## 4. Camera Registry

Create a provider-neutral `camera_registry`.

```json
{
  "camera_id": "bma:CM2-YW-32-C1",
  "provider": "BMA_DSD",
  "provider_camera_id": "CM2-YW-32-C1",
  "name": "สะพานลอยแยกพระราม 3 - สะพานภูมิพล CAM1",
  "latitude": 13.0,
  "longitude": 100.0,
  "access_mode": "EXTERNAL_VIEWER",
  "viewer_url": "provider-page-or-viewer",
  "stream_url": null,
  "snapshot_url": null,
  "status": "online|offline|unknown",
  "status_checked_at": "ISO-8601",
  "source": "BMA",
  "license_or_terms": "reference",
  "ingestion_allowed": false,
  "cv_allowed": false
}
```

Required registry fields:

- canonical camera ID
- provider and provider camera ID
- name/location
- latitude/longitude
- heading/FOV when available
- access mode
- viewer/stream/snapshot endpoint when authorized
- health status
- last successful frame timestamp
- provider terms/attribution
- whether automated sampling is permitted
- whether CV processing is permitted

## 5. Camera Adapter Interface

```text
CameraProviderAdapter
  listCameras()
  getCamera(cameraId)
  getHealth(cameraId)
  getViewer(cameraId)
  getLatestFrame(cameraId)      # only where authorized
  getStreamDescriptor(cameraId) # only where authorized
```

Initial adapters:

1. `BMA_DSD_CameraAdapter`
2. `BMA_Traffic_CameraAdapter` if stable public access is verified
3. `DOH_CameraAdapter` if relevant cameras/terms are verified
4. `FloodboardCameraReferenceAdapter` for camera references surfaced through Floodboard

The GRP core must never contain provider-specific camera URL logic.

## 6. Spatial Camera Matching

When a road-flood observation or incident is created:

1. Search cameras within a configurable radius (initially 250–500 m).
2. Prefer cameras whose FOV/heading intersects the affected road segment when heading metadata exists.
3. Rank by:
   - distance
   - provider health
   - image freshness
   - FOV relevance
   - access mode
   - historical reliability
4. Attach the top cameras as candidate corroboration sources.

Example:

```text
Flood observation FL.YNW.02
        |
        +-- 42 m --> CCTV A (online, relevant FOV)
        +-- 95 m --> CCTV B (offline)
        +--310 m --> CCTV C (online, uncertain FOV)
```

## 7. Visual Observation Pipeline

Where automated image access and processing are permitted:

```text
Authorized CCTV stream/snapshot
            |
            v
      Frame sampler
            |
            v
   Image quality gate
            |
      +-----+------+
      |            |
   usable       unusable
      |            |
      v            v
 Visual flood     record reason
 inference        (dark/blurred/
      |            blocked/etc.)
      v
Structured CCTV Observation
      |
      v
Evidence Fusion Engine
```

Do NOT run continuous full-video AI analysis for MVP. Prefer event-triggered or interval snapshots, for example:

- normal conditions: no CV or low-frequency sampling
- nearby road sensor changes to `slight/flood`: sample immediately
- new Floodboard/citizen incident: sample nearest cameras
- active incident: sample every configurable 2–5 minutes if provider terms permit
- incident resolved: retain only required evidence/metadata according to retention policy

## 8. CCTV Observation Schema

```json
{
  "observation_id": "uuid",
  "observation_type": "CCTV_VISUAL",
  "camera_id": "bma:CM2-YW-32-C1",
  "observed_at": "ISO-8601",
  "frame_captured_at": "ISO-8601",
  "location": {"lat": 0, "lng": 0},
  "flood_visible": true,
  "water_presence_confidence": 0.91,
  "estimated_depth_band": "UNKNOWN|LT_10|10_30|30_50|GT_50",
  "depth_confidence": 0.31,
  "vehicle_passability_evidence": "UNKNOWN|NORMAL_VISIBLE|HIGH_CLEARANCE_ONLY_SUSPECTED|IMPASSABLE_SUSPECTED",
  "trend": "UNKNOWN|RISING|STABLE|RECEDING",
  "visibility": "GOOD|FAIR|POOR",
  "occlusion": 0.12,
  "night": false,
  "quality_flags": [],
  "model_id": "vision-model-version",
  "human_verified": false,
  "source_url": "provider reference",
  "provenance": {"provider": "BMA", "method": "authorized_snapshot"}
}
```

Depth estimation must default to `UNKNOWN` unless the scene has sufficient calibration/reference evidence. The system must never manufacture a centimeter value from an uncalibrated monocular image.

## 9. Confidence Fusion

CCTV adds corroboration; it does not overwrite sensor data.

Illustrative evidence logic:

```text
BMA road sensor:       22 cm, fresh           HIGH
Floodboard reports:    3 recent reports       MEDIUM
CCTV:                  visible road flooding  MEDIUM/HIGH
Rainfall:              heavy                  CONTEXT
GEOGloWS:              elevated river flow    FORECAST CONTEXT
----------------------------------------------------------
GRP Incident:          CONFIRMED / HIGH confidence
```

Counter-evidence is equally important:

```text
Citizen report:        severe flood           LOW/MEDIUM
BMA sensor:            0 cm, fresh             HIGH
CCTV:                  road appears dry        MEDIUM
----------------------------------------------------------
GRP: CONFLICTING EVIDENCE — human review required
```

The UI must expose why confidence changed.

## 10. UI / UX

### Map

Add CCTV icons with health/access state:

- online/viewable
- offline
- metadata only
- evidence attached to incident

### Incident drawer

```text
Prachachuen Road — Flood Incident

Current depth        18 cm
Trend                Rising
Confidence           HIGH
Updated              4 min ago

Evidence
[x] BMA road sensor       4 min ago
[x] Floodboard reports    3 reports / 18 min
[x] CCTV                  visual flooding confirmed
[ ] CCTV #2               offline
[x] Rainfall              31 mm / 1h

Nearby CCTV
[ Live / Latest frame ]  Camera CM...
[ Open official viewer ]

Affected
- 2 schools
- 1 clinic
- 3 road segments

Forecast / context
- rainfall continues
- hydrologic pressure elevated
```

The UI must label whether imagery is **live**, **latest snapshot**, **embedded provider viewer**, or merely an **external viewer link**. Never label a camera "live" based only on its existence in a directory.

## 11. Human Verification

Authorized operators can mark CCTV evidence:

- `CONFIRMS_FLOOD`
- `CONTRADICTS_FLOOD`
- `INCONCLUSIVE`
- `CAMERA_NOT_RELEVANT`

Human verification is stored separately from model inference and becomes training/evaluation data for future CV improvements.

## 12. Privacy, Safety and Governance

The pilot's CV scope is environmental/road-state analysis only.

Explicitly out of scope:

- face recognition
- identity inference
- license-plate recognition
- individual tracking
- behavioral profiling

Where frames are processed, minimize retention. Prefer derived structured observations and provider references over retaining continuous footage. Respect provider terms, licensing, attribution, robots/access restrictions, and applicable privacy requirements.

## 13. CCTV MVP Acceptance Criteria

The CCTV capability is accepted when:

1. At least one Bangkok camera provider is represented through the common registry.
2. Cameras can be spatially associated with flood sensors/incidents.
3. Camera health/access mode is visible to users.
4. An operator can open the authoritative provider viewer from the GRP incident.
5. Where an authorized snapshot/live mechanism exists, GRP can retrieve a current frame without bypassing controls.
6. A retrieved frame can produce a structured visual observation with timestamp, provenance and confidence.
7. CCTV evidence participates in incident confidence fusion.
8. Offline/stale cameras never count as confirmation.
9. Conflicting CCTV/sensor/citizen evidence is surfaced rather than hidden.
10. All AI-derived visual claims can be traced to camera, frame time and model version.

## 14. Revised Bangkok Pilot Evidence Stack

```text
                     BANGKOK GRP

 Floodboard -----------------------------+
 BMA road flood sensors -----------------|
 Traffy / citizen evidence --------------|
 BMA CCTV / authorized visual evidence --+--> Evidence Gateway
 Rain gauges / BMA / HII ----------------|
 Canal / Chao Phraya levels -------------|
 GEOGloWS --------------------------------+
                                             |
                                             v
                                      Evidence Fusion
                                             |
                          +------------------+------------------+
                          |                                     |
                          v                                     v
                   Current Incident                       Forecast Context
                          |                                     |
                          +------------------+------------------+
                                             v
                                      Exposure Engine
                                schools / hospitals /
                                population / roads
                                             |
                                             v
                                     Consequence Engine
                                             |
                                             v
                                     Decision Intelligence
                                             |
                                             v
                                         AI / MCP
```

## 15. Revised Pilot Demo Story

**Question:** "What is happening around this flooded Bangkok corridor, is the report credible, what is affected, and what needs attention?"

Demo sequence:

1. BMA/Floodboard detects or reports road flooding.
2. GRP creates/updates an incident.
3. GRP finds the nearest relevant CCTV cameras.
4. The UI shows camera availability and authoritative viewer/live/snapshot mode.
5. Where permitted, a recent frame is sampled and analyzed.
6. CCTV confirms, contradicts or cannot determine flooding.
7. GRP fuses visual evidence with road depth, citizen reports and rainfall.
8. Exposure analysis identifies schools, health facilities, population and affected access routes.
9. GEOGloWS/weather/local water levels provide forecast context.
10. AI/MCP answers with evidence-linked claims and confidence, not unsupported narrative.

This makes the Bangkok pilot a proof of **multi-source, evidence-grounded operational decision support**, rather than another flood map.

## 16. Implementation Backlog Additions

### EPIC-CCTV-01 Camera Registry
- ingest BMA camera metadata
- normalize IDs/location/provider
- health/access-mode model
- attribution/terms metadata

### EPIC-CCTV-02 Camera-to-Incident Association
- PostGIS nearest-camera query
- FOV/heading scoring when available
- incident-camera relationship

### EPIC-CCTV-03 Viewer Integration
- provider viewer launch
- embed where explicitly supported
- clear live/snapshot/external labels

### EPIC-CCTV-04 Authorized Frame Acquisition
- snapshot adapter
- HLS/MJPEG/WebRTC adapter only where authorized
- retry/timeout/rate limits
- freshness checks

### EPIC-CCTV-05 Visual Flood Inference
- quality gate
- water-presence classification
- optional calibrated depth-band estimation
- vehicle-passability visual clues
- model/version provenance

### EPIC-CCTV-06 Evidence Fusion
- positive corroboration
- contradiction handling
- stale/offline exclusion
- confidence explanation

### EPIC-CCTV-07 Human Verification
- operator review states
- audit trail
- evaluation dataset

### EPIC-CCTV-08 Governance
- provider terms register
- retention policy
- privacy controls
- disable prohibited person/vehicle identity analytics

## 17. Development Priority

For the first pilot increment, prioritize:

**P0:** camera registry + nearest camera + provider viewer + health state + provenance.

**P1:** authorized snapshot ingestion for any provider that clearly permits it + visual flood presence classification.

**P2:** calibrated depth/passability inference and automated event-triggered sampling.

This ordering allows GRP to use CCTV as evidence immediately without making the pilot dependent on obtaining raw stream access.

