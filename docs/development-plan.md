# Development plan: how GRP stays good as it grows

**Status:** Proposed for the Technical Lead and architecture owner.
**Date:** 18 September 2026.
**Read with:** [`architecture-scaling-design.md`](architecture-scaling-design.md) (shape of the system), [`thailand-dataset-ingestion-plan.md`](thailand-dataset-ingestion-plan.md), [`thailand-dataset-inventory.md`](thailand-dataset-inventory.md) and [`dataset-proof-results.md`](dataset-proof-results.md) (real data), [`backlog.md`](backlog.md) (the ordered work items), and `handovers.md` (current state).

This plan is about *how we work*, not only what we build. It exists so a new developer or agent can join, change something real in a day, and not break the promises the platform makes to planners.

---

## 1. What "good" means here

GRP is decision-support for flood preparedness. A wrong but confident answer is worse than no answer. Everything below serves five promises:

1. **One number, one source.** Every figure a planner sees comes from one locked result with pinned inputs.
2. **Stop safely.** When something is missing or mismatched, the system stops and explains; it never substitutes.
3. **Traceable.** Each result can be replayed: inputs, versions, fingerprints, method, who ran it, when.
4. **Least privilege.** Sign-in proves identity; GRP membership decides what you may see and do.
5. **Honest words.** "Not exposed under this scenario", never "safe". Hazard exposure is not risk; a receipt is not scientific approval.

A change that weakens one of these is not an improvement, however elegant.

---

## 2. Engineering standards (apply to every change)

### 2.1 Definition of done
- Behaviour covered by tests for success, failure **and** permission.
- Route declares `x-grp-access`; the permission matrix test covers it.
- Errors use the Appendix D shape; other Hubs and unknown items return 404.
- Security log events written where Section 13.3 requires.
- Migration included and forward-only, if the schema changed.
- No secret, key, personal data or private geometry in logs, fixtures or errors.
- `handovers.md` updated when the state of the work changes.

### 2.2 Tests: what belongs where
| Layer | Covers | Speed |
|---|---|---|
| `tests/fast` | Rules in isolation: allowance maths, result invariants, identity linking, sessions, UI static checks | Seconds |
| `tests/contract` | Every route against every role, error shapes, cross-Hub denial | Seconds |
| `tests/golden` | End-to-end through API and worker against hand-checked expected values | Seconds |
| `tests/live` | Real SIG and provider calls, run by a person with credentials | Minutes |
| `tests/load` | Concurrency, queue depth, restore rehearsal | Increment 7 |

Rules: never edit a golden expected value to make a test pass; never let tests reach the network; record external fixtures deliberately and review them as a diff.

### 2.3 CI gates to add (in this order)
1. **PostgreSQL job** running migrations from empty plus the golden tests (SQLite today hides PostGIS and locking differences).
2. **Secret scan** on every push.
3. **Two-worker concurrency test**: two workers, one queue, no double-processing.
4. **Front-end syntax and asset-version check**, so a shared file change cannot ship without a cache bump.
5. **Container build and image scan** on merge to `main`.

### 2.4 Observability (before the pilot)
- Structured JSON logs with `trace_id`, `support_ref`, `hub_id`; never tokens, cookies, prompts or uploads.
- The metrics in the spec: queue depth and age, worker heartbeat, job durations, SIG errors, AI tokens, blocked AI, backup age.
- Alerts that wake someone: health failing, queue older than 30 minutes, worker silent, backup older than 26 hours, AI usage unrecordable.
- One dashboard a Hub Admin can read without a developer.

### 2.5 Security habits
- Re-check membership and role on every request from the database, never from the request body.
- Anything from a model, a browser or SIG is data, not instruction; the server decides what may run.
- Publish, share and receipt actions always need an explicit human confirmation.
- Rotate the SIG service token and AI keys on a schedule, and log the rotation.

### 2.6 Documentation habits
- A decision that changes roles, permissions, sharing, AI rules, methods or the SIG contract gets an ADR **before** the code.
- `handovers.md` is the single "where are we" document; update it at the end of every working session.
- Every design note states what is *not* covered, so a reader knows the edges.

---

## 3. Phased plan

Each phase has a purpose, the work, and a clear finish line. Dependencies on other teams are named.

### Phase 0 — Prove the data before building on it (done, half a day)
*Purpose: find out whether the delivered files behave, before anyone writes a loader against them.*
- `tools/prove_dataset.py` reads the files directly, outside the product, and writes nothing.
- Results and the four data-quality problems are in [`dataset-proof-results.md`](dataset-proof-results.md).
- **Outcome:** the three datasets line up, but the no-data rule (DEP-05) is now a proven blocker, not a theoretical one, and shelter district names cannot be joined. Both change the loader design in Phase 2.
- **Rule this establishes:** prove a dataset on one real area with a throwaway script before committing to a loader. Half a day here saved rewriting the shelter join twice.

### Phase 1 — Trust the foundation (now, 1 to 2 weeks)
*Purpose: make what exists provable and repeatable.*
- Browser acceptance of the publish flow, the district confirmation and the location fixes.
- Rebuild the Docker images so no change lives only inside a running container.
- Add the PostgreSQL CI job and the secret scan.
- Move the rate limiter and SIG token store out of process memory (PostgreSQL first; Redis only if measured).
- Record one real SIG exchange as a fixture and replay it in tests.
- **Done when** `main` deploys cleanly from a built image, CI proves migrations and golden results on PostgreSQL, and no test depends on the network.

### Phase 2 — Real Thailand data (2 to 3 weeks, partly blocked)
*Purpose: replace synthetic inputs with approved ones, without weakening the promises.*
- Boundaries to PostGIS, with a simplified copy for the map; load one pilot province, not all 928 districts.
- Load `ddpm_shelters` as an evacuation-centre version with mapped Thai fields.
- Convert the six flood tiles to COG with overviews; register provenance.
- Settle the no-data rule with the Scientific and Data Authority and write it into a new method version (blocking, DEP-05).
- Draw flood depth per district (Option A).
- **Done when** one real district is assessed end to end, the map shows its flood depth, and every figure carries its source, edition and fingerprint.

### Phase 3 — Complete Increment 1 and 4 (3 to 4 weeks)
*Purpose: a planner can finish a job without a developer.*
- Signed Chiang Yuen golden case (DEP-04) added beside the synthetic one.
- Job trace screen for Admins.
- One-page summary PDF and evacuation map exports as export jobs.
- Lease renewal for long jobs; cancel and retry paths exercised under load.
- **Done when** the golden result matches exactly and the downloads match the locked result.

### Phase 4 — SIG connection, Increment 3 (2 to 3 weeks, needs SIG)
*Purpose: GRP results become traceable public evidence.*
- Admin sharing approval; evidence endpoint with the public field set; SIG machine login; `assessment_ref` in the risk pack; receipt linking with retry.
- Contract tests against recorded SIG responses.
- **Done when** pack numbers equal the golden result, private and uploaded-data assessments return 404, and one receipt is issued by hand.

### Phase 5 — Scale of data and people (3 to 4 weeks)
*Purpose: more scenarios, more areas, more users.*
- Seven JRC return periods; uploads with validation and "current dataset" handling.
- Widen approved districts province by province after review.
- Two workers on 8 CPU; queue and job-duration targets measured.
- Optional: the tile service (Option B) if planners ask to browse nationally.
- **Done when** each scenario has a golden case, replacements never change old results, and service targets are met.

### Phase 6 — Vulnerability and AI explain, Increment 6 (3 weeks, needs DEP-07)
*Purpose: answer the second planner question honestly.*
- Approved vulnerability layer, reprojected, with a stated meaning; method version 2.
- "Which vulnerable people need support?" answered from the stored result only.
- Preparedness investment brief as a traceable document built from results and evidence.
- **Done when** the vulnerability golden case passes and no AI answer invents a number.

### Phase 7 — Pilot hardening, Increment 7 (2 weeks)
- Load test, restore rehearsal, security test, alerts, runbook, production on 8 CPU.
- **Done when** service targets are met, restore completes within eight hours, and security and data sign-off are recorded.

---

## 4. Technical debt register (pay down inside the phases)

| Item | Why it matters | Pay it in |
|---|---|---|
| Rate limits and SIG token in process memory | Blocks a second API copy | Phase 1 |
| SQLite-only CI | Hides PostGIS and `SKIP LOCKED` behaviour | Phase 1 |
| `api/planning.py` and `web/planning.js` are large | Slows every change and review | Phase 2, split by concern |
| Boundaries stored as GeoJSON | Real geometry needs PostGIS indexes | Phase 2 |
| Estimated progress steps in the chat | Times shown are guesses | Phase 3, server-sent events |
| Leaflet and tiles from public CDNs | Unsuitable for a served platform | Phase 5, vendor and contract |
| No lease renewal | A long job could be claimed twice | Phase 3 |
| Interim SIG sign-in (ADR-0002) | Not the agreed login shape | When DEP-01 lands |
| Spec text behind the ADRs | The baseline no longer matches the build | Rolling, per change process |

---

## 5. How to work on this code

- **Start from `handovers.md`.** It names the branch, the state and the next task.
- **Change one thing at a time**, with tests, and keep the commit message explaining *why*.
- **Prefer deleting to adding.** The pending-access list, the mode switch and the place box all left when they stopped earning their place.
- **When a model is involved**, decide in code what may happen; the model only proposes.
- **When unsure about science**, stop and ask the Scientific and Data Authority. Do not encode a guess.
- **Check it in a browser** before saying it works; tests do not see layout, colour or a stuck button.

---

## 6. Review points for the product owner

- End of Phase 1: the platform is provable and deployable.
- End of Phase 2: real data visible, with its provenance.
- End of Phase 3: a planner can complete and download a result unaided.
- End of Phase 4: evidence is shareable and traceable outside GRP.
- Before Phase 6: the meaning of "vulnerable people" is approved in writing.
