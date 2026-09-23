# ADR-0021: A SIG evidence lookup runs as a background task, not inside the request

**Status:** Accepted for the Developer environment (Docker Desktop) on 23 September 2026. Extends ADR-0004.

**Date:** 2026-09-23

**Deciders:** Product owner (Kovitad); Technical Lead (Kwan) to review

## Context

`assemble_pack` on the shared SERVIR service was called four times on 23 September for Thai districts — Mueang Nan twice, once per hazard, and Bang Sue, the district in SERVIR's own published runbook. Every call exceeded 60 seconds without returning. `api/mcp_client.py` gives the client 45 seconds, so a real Thai district lookup cannot complete inside a GRP web request at all.

Holding a request open for two minutes is not the answer either: a proxy or a browser may cut it, the planner watches a frozen page, and nothing survives a reload.

GRP already has the shape for this. Assessments run in the worker, and `GRP.jobs` in `web/grp-common.js` shows a pill in the top bar, polls every five seconds and notifies when a job ends. The obstacle is that the worker cannot do this work: the SIG token that authorizes the call lives only in the API process's memory (ADR-0002, ADR-0017), and putting it in the job row would persist an upstream credential, which that decision forbids.

## Decision

Run the lookup as an asyncio task **in the API process**, and let the browser watch it with the job tracker it already uses.

- **`POST /api/v1/planning/lookups`** takes the same body as the chat route, checks Hub membership in the request so a refusal is immediate, starts the task and returns a job id.
- **`GET /api/v1/planning/lookups/{job_id}`** returns the state and, once it succeeds, the same answer payload the chat route would have returned. A lookup another session started is **not found**, not refused: it is not theirs to know exists.
- **AD-03 is not weakened.** The worker owns GIS; this is a network call to SIG. No raster is read and no geometry is computed here.
- **The task uses the app's own database provider** (`app_session` in `api/sig_jobs.py`), resolved through the app so it picks up whatever the app is configured with, a test's override included. One code path, not one for the app and another for tests.
- **Bounded and owned.** At most 200 lookups; a finished one is readable for 30 minutes so a planner can come back to the tab; an unfinished one is given up after 10 minutes. Signing out drops a session's lookups with its token.
- **`POST /api/v1/planning/chat` stays.** It is the same function the task calls, it is what the tests exercise, and it remains usable for a fast turn.

## Options considered

| Option | Benefit | Main risk |
|---|---|---|
| Raise the client timeout to three minutes | One line | The planner watches a frozen page; a proxy or reload still loses it |
| Move the gather to the worker | Matches assessments exactly | The worker cannot see the SIG token, and persisting it breaks ADR-0002 |
| Background task in the API process (chosen) | Survives a slow gather, reuses the job tracker, keeps the token where it is | In-process: a restart loses running lookups, and a second instance cannot see them |
| Wait for SERVIR to make `assemble_pack` faster | No GRP change | Not ours to schedule, and the feature is unusable until then |

## Consequences

- A planner can ask a question that takes two minutes, switch to another page, and be told when the answer lands.
- This is the third thing held in process memory, after the token store and the answer cache. All three move together when GRP runs more than one API instance; none of them is safe to shard before then.
- The latency itself is not fixed, only survived. It stays on the list of questions for SERVIR.

## Action items

- [x] Lookup store, endpoints, browser polling, tests (`tests/fast/test_planning_chat.py`)
- [ ] Demonstrate a real Thai district lookup end to end in Docker Desktop
- [ ] Ask SERVIR whether 60 seconds is expected for a Thai district
- [ ] Technical Lead review
