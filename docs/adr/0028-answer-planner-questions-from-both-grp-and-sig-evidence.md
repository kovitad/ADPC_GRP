# ADR-0028: Answer planner questions from both GRP and SIG evidence

## Status

Proposed. Nothing in this ADR is implemented yet.

## Context

A Planner asked whether six questions are answerable today:

1. Which evacuation centres are good candidates as a safe evacuation place?
2. How many people in Chiang Yuen District are in the RP100 flood zone?
3. How many evacuation centres are schools, temples, stadiums?
4. What weights are used for each risk indicator?
5. What areas are good to install early-warning sensors?
6. How many buildings will be affected by RP100 flood?

Only question 4 is answerable from GRP's own data. The reasons differ by question, and
conflating them leads to the wrong fix:

- The chat assistant never sees GRP data. `api/planning.py` routes a message into exactly one
  mode, and the `sig_flood` prompt carries only `question`, `place`, `required_sections`, SIG
  `citations`, `declared_gaps` and `approved_risk_recipe`. `AreaPopulationSummary` is not
  referenced anywhere in `api/planning.py`, so the population counts a Planner can see in the map
  popup are invisible to the assistant.
- Question 2 has both inputs present and no product. Village points and the RP100 raster are both
  imported; nothing intersects them.
- Question 3 has the answer inside a string. The facility type is the Thai name prefix (`วัด`,
  `โรงเรียน`, `ศาลา`); there is no `facility_type` field.
- Question 6 has no local source at all. There is no building-footprint dataset category.
- Questions 1 and 5 ask for a suitability recommendation. `api/assessments.py` states that centre
  capacity, building condition and route safety are not assessed, and `DRAFT_INSTRUCTIONS`
  forbids inventing recommendations or safety claims. These are method decisions, not data gaps.

## Decision

### 1. Retrieval is deterministic pre-retrieval, not RAG

These questions are numeric aggregations over structured rows. A retrieval layer that returns
prose chunks by embedding similarity would supply approximate text where a Planner needs an exact
count, which is the one thing GRP refuses to guess. **No vector store, no embeddings, no
document chunking.**

The router already extracts `place`. The assistant therefore does not need to decide to look
anything up. In the `sig_flood` branch, before `run_ai_call`, GRP resolves that place to a
`Boundary`, reads its own rows for that area, and appends them to `citations` as further numbered
entries marked as GRP-sourced. The existing rule that every paragraph ends in a numeric citation
then covers GRP's own data unchanged.

Local resolution fails closed exactly as SIG's does: if the resolved boundary is not the same area
as the requested place, no local evidence is attached, matching `check_area`.

### 2. Tool calling is deferred, because it is an allowance change

Letting the model choose its own lookups needs a provider loop. `run_ai_call` reserves against a
monthly allowance keyed by one `request_id`, makes one `call_openai`, and settles that same
`request_id`; its contract is that every path leaves the allowance consistent (AI-09, AI-12). N
provider calls per user message has no representation in that ledger. Tool calling is therefore
not adopted here. It may be revisited once AI-09 states how many settled calls one reservation
may cover.

### 3. New tables, each tied to one question

| Table | Unlocks | Computed |
| --- | --- | --- |
| `area_flood_exposure` — area x return period, villages/people/households inside the zone, split by depth band | Q2 | Worker job at activation; village points sampled against the pinned raster with `rasterio.sample()` |
| `facility_type` on `Feature`, plus per-area counts by type | Q3 | Import time, from the Thai name prefix, same pattern as `AreaPopulationSummary` |

`area_flood_exposure` records `counted`, `excluded` and `no_data` village counts so a partial
sample is visible rather than silently low, matching ADR-0027's handling of unusable rows.

Aggregation stays out of the request path: a web request must never sample 80,397 points.

### 4. Question 6 needs a Data Library category, not a table

Building exposure needs a `building_footprints` import category before any table is worth
designing. Until a delivery exists, the honest answer stays that SIG is the only path and its
coverage decides.

### 5. Questions 1 and 5 get no schema

No table makes a siting or safety recommendation defensible. They stay refused until a method
owner approves a documented suitability method, which is a DEP-07 style decision.

## Consequences

- A Planner asking about population or shelters gets GRP's own cited figures in the same brief as
  SIG's, from one provider call, with the allowance model untouched.
- GRP states its own numbers, so a wrong local number is now visible in a brief rather than only
  in a popup. Local evidence therefore carries its source label and ADR-0027 caveat verbatim.
- No new runtime dependency. `rasterio`, `pyogrio` and `shapely` are already the `gis` extra.

## Slices

1. Attach existing `AreaPopulationSummary` and district shelter counts to the `sig_flood`
   citations, behind the same-area check. No migration.
2. `facility_type` at import time plus per-area counts. One migration, one importer change.
3. `area_flood_exposure` worker job. One migration, one job, golden cases for the depth bands.
4. Revisit tool calling once the AI-09 reservation question is settled.

## References

- ADR-0015 and DEP-07 (vulnerability stays outside the flood recipe)
- ADR-0025 (background SIG lookups)
- ADR-0027 (registered village population labelling)
- `docs/vulnerable-people-data-proof.md`
