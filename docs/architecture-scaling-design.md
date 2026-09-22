# Scaling design: modular monolith now, services on measured triggers

**Status:** Proposed for the Technical Lead and architecture owner to confirm.
**Date:** 18 September 2026.
**Applies to:** GRP MVP 1 and the first pilot. It follows `GRP-ARC-001` v2.2 AD-05 (every assessment is a background job) and AD-11 (simple, replaceable infrastructure).

## 1. What we run today

| Part | Technology | Job |
|---|---|---|
| `grp-api` | Python 3.12, FastAPI, SQLAlchemy | Sign-in and sessions, permissions, input validation, job creation, reading results, the AI gateway, the SIG evidence endpoint. **Never runs GIS.** |
| `grp-worker` | Same image, worker entry point, rasterio and shapely | Claims jobs, runs the approved method, checks the result rules, writes one locked result |
| `grp-db` | PostgreSQL 16 with PostGIS | The official record: people, membership, datasets and versions, jobs, results, security log, AI usage |
| Caddy | Front door | HTTPS, security headers, serves the web pages, forwards `/api` |
| Web | Plain HTML, CSS and JavaScript with Leaflet | No build step and no framework, so a page is what you see in the file |

This is **one codebase with clear internal boundaries, deployed as a few processes**. It is not a microservice system, and it should not become one until something measurable demands it.

## 2. Why work runs as background jobs

- **The work is genuinely slow.** SIG's own live runs took 52 to 152 seconds for one area. District GIS takes seconds to minutes.
- **The service targets require it.** Submitting must answer in under a second with a job number; 95% of assessments must finish within five minutes on one worker.
- **It survives failure.** A job holds a lease, so a crashed worker's job is picked up again. A cancel is respected. A result is written once and never edited.
- **It is honest to the planner.** The states are visible: queued, running, succeeded, failed, cancelled, each with a support reference and a trace.

The queue is PostgreSQL `SELECT … FOR UPDATE SKIP LOCKED`: no extra broker to run, and it sits behind an interface so it can move to a broker later without changing callers.

## 3. Why not microservices now

- **Team size.** A small team would spend its time on deployment, versioning and tracing instead of the product.
- **One database is the point.** Access rules, job state, results and the audit log must stay consistent. Splitting them turns ordinary transactions into distributed ones.
- **The boundary that matters already exists.** ADPC owns users, data and calculation; SIG owns evidence, gates and receipts. Two systems, one read-only endpoint between them.
- **Cost.** Each service adds its own deployment, secrets, monitoring, alerting and on-call.
- **Scale.** The pilot is 50 named people, 20 at once, 5 queued jobs.

## 4. What keeps the monolith split-ready

A module can become a service only if these hold. They are also good design on their own.

| Rule | Why it matters at a split | State today |
|---|---|---|
| One-way dependencies | Two modules that call each other cannot be separated | **Good:** `api` → `core` → database; the worker never imports the API, the API never imports GIS |
| Replaceable parts behind interfaces | Swap local for remote without touching callers | **Good:** storage, job queue, AI provider and login provider are interfaces |
| State lives in the database | Anything in process memory breaks with a second copy | **Weak:** rate limits (`api/rate_limits.py`) and the SIG token (`api/token_store.py`) are in memory. Fix before running two API copies |
| Idempotent, replayable work | Network retries must be safe | **Good:** `Idempotency-Key` on submit, job leases, results written once |
| Typed contracts at the edges | The seam becomes an API without redesign | **Good:** Appendix D errors, `x-grp-access` on every route, a fixed public field set for SIG |
| Pinned inputs and fingerprints | A remote worker must prove it used the same data | **Good:** every job pins versions and SHA-256s and rechecks them before writing |
| Each service owns its tables | Two services writing one table is the classic failure | **Watch:** everything shares one database today, which is correct now; on a split, the extracted part takes its tables with it |
| Traceable requests | Debugging across services needs one thread to follow | **Partial:** support reference and trace IDs exist; distributed tracing arrives at Beta |

## 5. When a split is worth it

Only for a reason you can measure:

1. **Different scaling shapes.** GIS wants CPU and memory; the API wants concurrency. Adding worker copies is cheaper. Split only if workers need different hardware.
2. **Different runtime needs.** Map tiles want a caching image server; PDF export wants a headless browser. Neither belongs in the API image.
3. **Team ownership.** Separate teams releasing on separate schedules.
4. **Fault isolation.** Keeping a heavy or third-party-dependent part from affecting the platform. The queue and the AI gateway already provide most of this.
5. **Other consumers.** Another Hub or product calling the AI gateway or the evidence endpoint directly.
6. **Boundaries you do not control.** ADPC and SIG, which is already a boundary.

"Because microservices are modern" is not on the list.

## 6. Steps to take before any split

1. Add worker copies (same image, more processes) once the server has 8 CPU.
2. Split by **process type**, not service: API, GIS worker, export worker, scheduler.
3. Separate queues per job type inside the same database.
4. Move shared state (rate limits, SIG token) to PostgreSQL or Redis. Needed anyway.
5. Only then extract a service, starting with one that owns little data.

## 7. Extraction candidates, in order

| Candidate | Trigger | Technology |
|---|---|---|
| Map tile service | Country-wide flood tiles (Option B in the data plan) | TiTiler or rio-tiler over the COGs, with a tile cache |
| Export service | Increment 4 rendering makes PDFs heavy | Same worker image first, then its own service |
| More GIS workers | Queue regularly older than target after adding copies | Same image, more copies, bigger machine |
| AI gateway | Another Hub or product needs the same allowance rules | Lift `api/ai_gateway.py` as-is; already isolated |

## 8. Triggers worth watching

- Oldest queued job older than 30 minutes after adding workers.
- Tile or export work consuming most of the API server's CPU.
- A second team owning a part with its own release schedule.
- An external consumer calling the AI gateway or evidence endpoint.
- Availability or recovery targets that one server cannot meet.

## 9. What stays either way

Python and FastAPI, PostgreSQL with PostGIS, the database job queue, Docker Compose per environment, plain JavaScript on the front end, and the rules in Section 4. Those rules are what make the future cheap; the deployment shape is a detail that follows the numbers.
