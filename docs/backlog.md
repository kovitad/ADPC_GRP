# GRP backlog

**Updated:** 18 September 2026. Ordered so the top item is always the next sensible one to pick up.

How to read this: **S** is about a day, **M** two to four days, **L** a week or more, for one developer who has read `handovers.md`. "Blocked by" names another team; do not start those without the answer. Every item must meet the definition of done in [`development-plan.md`](development-plan.md).

---

## Epic A — Prove and load the real data

| # | Item | Size | Blocked by | Done when |
|---|---|---|---|---|
| A1 | ~~Prove the datasets on a real district~~ **done**, see [`dataset-proof-results.md`](dataset-proof-results.md) | S | — | — |
| A2 | ~~Nationwide quality report~~ **done** — the Admin **Source data** page (ADR-0006) runs it on demand: **1,139 of 10,303 shelters are in a different district from the one they name**, 255 of 928 districts hold no shelter, every flood tile is mostly no-value. What is left is to send these to DDPM and agree fixes | S | — | The Hub has taken the counts to the provider |
| A3 | Boundary geometry moves to PostGIS, with a simplified copy for the map | M | — | Migration runs on PostgreSQL; the map loads outlines without full detail; golden tests still pass |
| A4 | Boundary loader: `python -m grp.load boundaries --shapefile … --province …` with provenance (source, edition `2025-10`, licence, checksum) | M | Licence (DEP-04) | One province's districts are supported areas, each with admin code and fingerprint |
| A5 | Shelter loader for `ddpm_shelters` (**the 1,139 mismatches must be reported at load time, never silently accepted**): field mapping is in [`thailand-dataset-ingestion-plan.md`](thailand-dataset-ingestion-plan.md) §4.2, membership decided by geometry, mismatches reported not hidden | M | Meaning of `สถา` and `รอง` (DEP-06) | A district's shelters load with a stated count of rejected or suspicious points |
| A6 | Flood tiles to Cloud-Optimized GeoTIFF with overviews; registered as a dataset version with provenance | M | Licence (DEP-05) | Six tiles stored once, fingerprinted; the worker samples them unchanged |
| A7 | **No-data rule**: method version stating what an absent value means, with the modelled-area mask if one exists | M | **DEP-05 decision** | A new method version is recorded; Pua-style districts report a defensible status |
| A8 | Permanent-water handling: mask or flag depths over the agreed threshold | S | DEP-05 | Extreme depths are explained, not silently reported |
| A9 | First real assessment end to end on one district, compared with the proof tool | M | A3 to A7 | Numbers match the independent check; result carries pinned versions |

> **Before starting any of Epic A, open the Source data page and read the findings for the folder you are about to load.** It is faster than reading the file by hand and it names the decision each blocker waits on.

## Epic P — Preview the real data on the map now, with warnings (owner request, 19 Sep 2026)

The owner wants to **see** the delivered data on the map before the blockers are settled, with every known gap stated beside it. This is a preview, never a result: it reads the unapproved files, is Admin-only like the Source data page, carries a fixed "Unapproved preview — not a GRP assessment" label, and cannot start an assessment or reach SIG.

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
| D1 | PostgreSQL CI job: migrations from empty plus golden tests | S | — | CI runs on PostgreSQL, not only SQLite |
| D2 | Move rate limits and the SIG token out of process memory | M | — | Two API copies behave identically |
| D3 | Two-worker concurrency test in CI | S | D1 | No job is processed twice |
| D4 | Secret scan in CI | S | — | A pushed key fails the build |
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
| F2 | Upload, validate and accept one current local dataset per type | L | — | Invalid uploads are refused with clear reasons; replacement never changes old results |
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

1. **D1, D4** — CI on PostgreSQL with a secret scan. Everything else rests on this.
2. **A2 follow-up** — take the inspector's counts to DDPM; the report itself is built.
3. **A3, A4** — PostGIS geometry and one province of real districts.
4. **A5** — shelters for that province.
5. **D2** — shared state, so a second API copy is possible.

That leaves the team blocked on nothing, and by the end a planner can pick a **real** district in the app. The flood colours and real results follow as soon as DEP-05 answers the no-data question.
