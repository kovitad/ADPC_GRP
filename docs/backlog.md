# GRP backlog

**Updated:** 25 September 2026. Ordered so the top item is always the next sensible one to pick up.

How to read this: **S** is about a day, **M** two to four days, **L** a week or more, for one developer who has read `handovers.md`. "Blocked by" names another team; do not start those without the answer. Every item must meet the definition of done in [`development-plan.md`](development-plan.md). The cross-cutting baseline/import/Hub-override design is in [`data-library-sig-assessment-design.md`](data-library-sig-assessment-design.md). ADR-0008 closes the P0 design choices for the bounded local baseline; execute [`baseline-data-library-implementation-plan.md`](baseline-data-library-implementation-plan.md) in order. Browser upload and server rollout remain gated by the senior review.

---

## Epic U — Planner workspace UX (owner report, 25 September 2026) — **do first**

Raised by the Product Owner while testing the Planning and Flood assessment pages. These are not
cosmetic: an inconsistent panel makes a planner distrust numbers that are correct, and that costs
more than a missing feature. Ordered so the top item is the next one to pick up.

| # | Item | Size | Blocked by | Done when |
|---|---|---|---|---|
| ~~U1~~ | ~~**People tab flaps between the real figures and the old raster page.** Owner: "sometimes people tab show stat sometime show the old page ... for some district or even from assessment then click". Five causes, diagnosed 25 Sep: the area profile is requested only inside `selectBoundary` and only when the id changes, so any panel render without a fresh selection shows the fallback; the load is fire-and-forget so a later re-render does not re-request it and the stale page sticks; the three panel modes pass different arguments so which data wins depends on call order; `setPanelMode` force-clicks the Summary tab on every mode change, throwing the user off People; and pending, empty and 404 states all fall through to the raster page. Fix by making the tab a pure function of `state.areaProfile` / `state.sigPopulation` / `state.areaProfileState`, showing GRP and SIG sections together rather than either-or, adding an idempotent `ensureAreaProfile()` called from all three panel modes, giving loading and unavailable their own honest text, demoting the rasters to a permanent one-line footer, and preserving the active tab across re-renders**~~ — **done 25 Sep**, commit `3652ad6` | M | — | Clicking any district, any sub-district, or opening an assessment then clicking, shows the same tab content and leaves the user on the tab they chose; no state shows the raster page as a stand-in for data |
| ~~U2~~ | ~~**Flood assessment "Pick an area" loads every district into one select.** Owner: "the page is heavy need to load all district and put one drop down box ... not good ux". Replace with province → district → sub-district cascading pickers plus a type-ahead search, fetching each level on demand instead of shipping 928 districts (and 7,436 sub-districts) to the browser. `/api/v1/catalog/boundaries` already takes `level` and `parent_admin_code`, so the server side exists~~ — **done 25 Sep**, commit `622f0f8`: the catalogue call went from 63,180,918 to 384,708 bytes; `/catalog/provinces` added; province query avoids grouping by a substr expression, which PostgreSQL rejects and SQLite accepts | M | — | The page loads without fetching every area; a planner can find an area by typing part of its name; picking a province narrows the district list |
| ~~U3~~ | ~~**Assessment history table is large and gives the planner nothing to do.** Owner: "the assssment history table is big and not sure what to do the". Decide the two or three actions a planner actually takes from a past assessment (reopen on the map, compare, publish receipt), show those as row actions, and collapse or paginate the rest~~ — **done 25 Sep**, commit `1c55d83`: rows now lead with the outcome in words, one prominent action each, latest five with a toggle | S | U2 helps but not required | Each row offers a clear next action; the table does not dominate the page |
| ~~U4~~ | ~~**Buttons are oversized and inconsistent with the rest of the workspace.** Owner: "the button very bug and uglis". Align the assessment page controls with the Planning workspace button scale and hierarchy: one primary action per view, secondary actions demoted~~ — **done 25 Sep**, commit `2d87f43`: `.button--compact` at 2.2rem matching Planning's toolbar, one primary per page | S | — | The page uses the shared button styles; only the primary action is visually prominent |
| ~~U5~~ | ~~**Switching from an assessment to Planning gives an unpredictable result.** Owner: "swich to planning unpredicable the result". Define and implement what carries across: the selected area, the pinned scenario, and whether the locked result stays on the map. Today the transition depends on which panel rendered last and whether `preserveAssessment` was passed~~ — **done 25 Sep**, commit `2d87f43`: the area is fetched and the level switched so the outline can be drawn, the previously selected area is dropped on arrival, the return period is aligned, and the carry-over is stated | M | U1 | Moving between Flood assessment and Planning keeps the selected area and states plainly on screen whether the locked result is still shown |

> **Epic U is complete** (U1-U5, 25 September 2026). The owner has not yet re-tested U3-U5; treat their next report as the acceptance check.

## Epic A — Prove and load the real data

| # | Item | Size | Blocked by | Done when |
|---|---|---|---|---|
| A1 | ~~Prove the datasets on a real district~~ **done**, see [`dataset-proof-results.md`](dataset-proof-results.md) | S | — | — |
| A2 | ~~Nationwide quality report~~ **done** — the Admin **Source data** page (ADR-0006) runs it on demand: **1,139 of 10,303 shelters are in a different district from the one they name**, 255 of 928 districts hold no shelter, every flood tile is mostly no-value. What is left is to send these to DDPM and agree fixes | S | — | The Hub has taken the counts to the provider |
| A3 | Boundary geometry moves to PostGIS, with a simplified copy for the map | M | — | Migration runs on PostgreSQL; the map loads outlines without full detail; golden tests still pass |
| A4 | Boundary loader plus existing-source import job, with provenance (source, edition `2025-10`, licence terms, checksum) | M | A3 and import-job safeguards | One province's districts are supported areas, each with admin code and fingerprint |
| A5 | Shelter loader and Hub-override path for `ddpm_shelters` (**the 1,139 mismatches must be reported at load time, never silently accepted**): field mapping is in [`thailand-dataset-ingestion-plan.md`](thailand-dataset-ingestion-plan.md) §4.2, membership decided by geometry, mismatches reported not hidden | M | Meaning of `สถา` and `รอง` (DEP-06) | A district's shelters load with a stated count of rejected or suspicious points |
| A6 | Flood tiles to Cloud-Optimized GeoTIFF with overviews; registered as a dataset version with provenance | M | Licence (DEP-05) | Six tiles stored once, fingerprinted; the worker samples them unchanged |
| A7 | **No-data rule**: method version stating what an absent value means, with the modelled-area mask if one exists | M | **DEP-05 decision** | A new method version is recorded; Pua-style districts report a defensible status |
| A8 | Permanent-water handling: mask or flag depths over the agreed threshold | S | DEP-05 | Extreme depths are explained, not silently reported |
| A9 | First real assessment end to end on one district, compared with the proof tool | M | A3 to A7 | Numbers match the independent check; result carries pinned versions |

> **Before starting any of Epic A, open the Source data page and read the findings for the folder you are about to load.** It is faster than reading the file by hand and it names the decision each blocker waits on.

## Epic P — Preview the real data on the map now, with warnings (owner request, 19 Sep 2026)

The owner wants to **see** the delivered data on the map before the method blockers are settled, with every known gap stated beside it. The Data Science delivery is accepted source data under ADR-0007. This is still a preview, never a result: it reads files before ingestion, is Admin-only like the Source data page, carries a fixed "Delivered data preview — not a GRP assessment" label, and cannot start an assessment or reach SIG.

| # | Item | Size | Blocked by | Done when |
|---|---|---|---|---|
| P1 | **Built 19 Sep** (`/data-preview.html`, linked from Source data). "Show on map" from a Source data report: district outline, shelters (coloured by whether they sit in the district they name), province/sub-district outlines | M | — | An Admin sees one district's real outline and shelters over OSM |
| P2 | **Built 19 Sep.** Flood depth preview for that district: clip the RP100 tile, draw depth classes, draw no-value pixels as hatched "no data — meaning undecided (DEP-05)" | M | — | Real flood colours appear, no-value areas are visibly different from dry |
| P3 | **Built 19 Sep** (warnings are written by `core/district_preview.py`, not copied from the folder report). Warnings panel beside the map, taken from the inspector findings for the layers shown, each with **why** it matters and which decision it waits on | S | P1 | Every blocker/problem for the visible layers is listed in plain words |
| P4 | **Built 19 Sep**, checked against the proof tool for Pua (29 shelters, all on no-value). Preview counts per district ("n shelters on a flood pixel, n on no-value, n misplaced") labelled as preview | S | P2 | Counts match `tools/prove_dataset.py` for the same district |

## Epic B — Make the map show real flood depth

| # | Item | Size | Blocked by | Done when |
|---|---|---|---|---|
| B1 | Render a district-clipped flood picture at load time (Option A) | M | A6 | A supported district shows real flood colours with the existing legend |
| B2 | Legend and wording review with a planner (classes, "no data", hazard not risk) | S | B1 | Wording approved by the product owner |
| B3 | Optional: tile service for country-wide browsing (Option B) | L | Owner decision | Planners can pan and zoom the whole country without loading whole rasters |

## Epic C — Finish Increment 1 and 4 (what a planner needs)

| # | Item | Size | Blocked by | Done when |
|---|---|---|---|---|
| C1 | Signed Chiang Yuen golden case beside the synthetic one | M | DEP-04 | CI fails if the result differs from the signed values |
| C2 | Job trace screen for Admins (`GET /admin/assessments/{id}/trace`) | M | — | Every step, time, safe error and identifier is visible |
| C3 | One-page summary PDF export job | L | DEP-12 templates | The download matches the locked result exactly |
| C4 | Evacuation map export (PDF and PNG) | L | DEP-12 | Same |
| C5 | Lease renewal for long jobs | S | — | A job running longer than the lease is not claimed twice |

## Epic D — Hardening before any server

| # | Item | Size | Blocked by | Done when |
|---|---|---|---|---|
| D1 | **Built 19 Sep.** PostgreSQL CI job: migrations from empty plus golden tests | S | — | CI runs migrations on PostGIS and the golden suite on every pull request |
| D2 | Move rate limits and the SIG token out of process memory | M | — | Two API copies behave identically |
| D3 | Two-worker concurrency test in CI | S | D1 | No job is processed twice |
| D4 | **Built 19 Sep.** Secret scan in CI | S | — | Gitleaks checks full history and fails the build on detected secrets |
| D5 | Vendor Leaflet; contracted tile and geocoding provider | M | Provider choice | No public CDN in the served page |
| D6 | Split `api/planning.py` and `web/planning.js` by concern | M | — | No file over about 400 lines; tests unchanged |
| D7 | Real streaming progress (server-sent events) replacing estimated steps | M | — | The progress card shows true steps and durations |
| D8 | Container build, image scan and versioned release from `main` | M | — | Staging deploys an exact built image, not source |

## Epic E — SIG connection (Increment 3)

| # | Item | Size | Blocked by | Done when |
|---|---|---|---|---|
| E1 | Admin sharing approval per assessment | M | — | Private by default; sharing is logged |
| E2 | Evidence endpoint returning the public field set only | M | — | Private and uploaded-data assessments return 404 |
| E3 | SIG machine login (client credentials) replacing the staging token | M | DEP-09, DEP-13 | A token for SIG's own MCP is refused |
| E4 | `assessment_ref` in the risk pack, receipt linking, retry for 24 hours | M | DEP-08 (SIG team) | Pack numbers equal the golden result; one receipt issued by hand |
| E5 | Contract tests against recorded SIG responses | S | E4 | Tests fail if SIG's shape changes |

## Epic F — More data and scenarios (Increment 5)

| # | Item | Size | Blocked by | Done when |
|---|---|---|---|---|
| F1 | Seven return periods with a golden case each | L | DEP-05 layers | Each scenario passes its own case |
| F2 | Browser upload, quarantine, validate and Hub Admin acceptance for one current local dataset per type (ADR-0008; existing-source import is built first) | L | Security review | Invalid uploads are refused with clear reasons; replacement never changes old results |
| F3 | Widen supported districts province by province | S each | Review | Only reviewed districts are selectable |
| F4 | Data-help request flow | S | — | A planner can ask for help preparing data |

## Epic G — Vulnerability and the second planner question (Increment 6)

| # | Item | Size | Blocked by | Done when |
|---|---|---|---|---|
| G1 | Reproject and register the vulnerability rasters as an unapproved layer | M | — | Visible on the map, never in a result, clearly labelled |
| G2 | Approved vulnerability method version 2 | L | **DEP-07 meaning** | Vulnerability golden case passes |
| G3 | "Which vulnerable people need support?" answered from the stored result | M | G2 | No number appears that is not in the result |
| G4 | Preparedness investment brief, exportable and traceable | L | G3, C3 | Every figure traces to a result or declared gap |

## Epic H — Pilot operations (Increment 7)

| # | Item | Size | Blocked by | Done when |
|---|---|---|---|---|
| H1 | Load test: two jobs at once, 50 readers | M | D1 to D3 | Service targets met |
| H2 | Restore rehearsal from backup | M | — | Restore within eight hours, proven on staging |
| H3 | Alerts and runbook | M | Monitoring service | Alerts reach a named person; runbook approved |
| H4 | Security review and sign-off | M | — | Findings closed or accepted in writing |

---

## Suggested first sprint (two weeks, one or two developers)

1. ~~**D1, D4** — CI on PostgreSQL with a secret scan.~~ **Built 19 Sep.**
2. **A2 follow-up** — take the inspector's counts to DDPM; the report itself is built.
3. **A3, A4** — PostGIS geometry and one province of real districts.
4. **A5** — shelters for that province.
5. **D2** — shared state, so a second API copy is possible.

That leaves the team blocked on nothing, and by the end a planner can pick a **real** district in the app. The flood colours and real results follow as soon as DEP-05 answers the no-data question.
