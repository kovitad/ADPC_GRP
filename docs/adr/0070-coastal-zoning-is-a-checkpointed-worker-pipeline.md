# ADR-0070: Coastal zoning is a checkpointed worker pipeline

**Status:** Accepted; revised to reuse delegated MCP authentication
**Date:** 23 October 2026

## Context

The Coastal Zoning Assessment specification proposes a deterministic Mangrove 360 zoning pipeline, with an LLM used only for receipt-gated zone briefs. The draft refers to another repository layout, a React frontend, and in-process platform tools. This repository instead has FastAPI routes in `api/`, shared domain code in `core/`, a PostgreSQL-leased worker, static web assets, immutable local storage, and a remote SIG MCP integration.

A zoning run can require many tile packs, GIS mosaicking, per-zone evidence packs, model calls,
and packaging. It cannot execute GIS in a web request. The current upstream SIG token is tied to a
human login and held only in API-process memory. The existing Planning feature already uses that
delegated token to call MCP for the signed-in person.

The Claude skill combines MCP evidence calls with deterministic local code. GRP can follow the
same division without loading the skill itself: the API-side coordinator uses the existing user's
MCP authentication for external evidence and receipt operations, while the persistent worker uses
stored artifacts for deterministic GIS. No second SIG identity is needed for the MVP.

## Decision

1. Coastal zoning uses a separate persistent run aggregate: run, P1–P10 checkpoints, zones, artifacts, and review log.
2. The existing database claim/lease worker pattern is reused. No RQ, Arq, Celery, or second queue service is introduced.
3. API requests validate, authorize, enqueue, cancel, retry, review, and read. An API-side
   background coordinator may make bounded MCP/model calls with the existing delegated user token.
   All GIS remains in `worker/`; MCP results cross that boundary only as immutable artifacts and
   identifiers, never as credentials.
4. Completed checkpoints and artifacts are immutable. A failed run retries from its failed checkpoint; worker crashes become reclaimable after lease expiry.
5. Runs are Hub-scoped and owner-scoped. Cross-Hub, unknown, and unauthorized run IDs are indistinguishable (404). Existing Hub roles will be mapped to run/review permissions in a later reviewed route change rather than adding roles now.
6. Receipt IDs may be stored, but receipt verdicts may not. Verdicts are resolved at view time and default to unverified.
7. Artifacts use generated keys beneath `coastal-zoning/{run_id}/` through the existing storage boundary. Filesystem paths are never returned to browsers.
8. The MVP reuses existing per-user MCP authentication. The token remains only in API-process
   memory and is never copied to the database, worker, model, trace, or artifacts. If it expires or
   the API restarts, the external stage fails closed with `SIG_REAUTH_REQUIRED`; after signing in,
   the owner retries from that checkpoint. A service credential is a future scale/reliability
   option, not an MVP requirement.
9. Deterministic zoning rules and scientific goldens will not be invented from the prose specification. They must be imported from the licensed starter kit and verified against approved fixtures.
10. Missing layers remain unknown. A deterministic map may complete without AI, but a zone without a resolving gated receipt remains unranked and labelled as a map-grid estimate.

## Consequences

- The implemented map-grid increment exposes protected routes and lets the worker claim zoning
  jobs only after the API has stored a user/Hub/geometry-bound immutable coverage pack.
- A future migration is not required merely to add pipeline code, but contract changes to stored fields require normal Alembic revisions.
- Polling is the initial progress transport; SSE can be added later without changing the persistent state model.
- The API coordinator needs bounded MCP/model concurrency; the worker needs disk-backed GIS
  scratch but no SIG credential. An API restart may interrupt an external stage, which is an
  accepted MVP limitation because checkpoint retry is explicit.
- Live pilot calls, public sharing, and contribution tools remain out of scope. No `contribute_*` operation is permitted in this pipeline.

## Implementation update

On 23 October 2026 the starter kit was supplied locally. Its zoning function was ported without
semantic changes and pinned to source SHA-256
`a3ec7fbc65190a9b76e4ef1c8a6231f4a9de26108603d6e7ffbdaf770059700d`. South Sumatra and Lamu
meet their supplied agreement thresholds, and fail-closed synthetic edge tests cover unknown
hazards, DEM gaps, missing land cover, and rule priority. NumPy and SciPy are now direct GIS
dependencies. The fixture bytes remain local because the kit has no explicit licence file and its
README says the fixture DEM licence and vintage are unstated.

The same date's map-grid increment now implements the chosen boundary. The API performs bounded
`assemble_pack` calls with the delegated token and persists only a checksum-pinned evidence
result. The worker decodes and aligns those governed display grids, runs the deterministic rules,
and produces a report without any network credential. Live Lamu and South Sumatra runs completed
in Docker. Because zone-level publish calls are not yet wired, P7–P9 are skipped, receipt IDs are
absent, and all candidate components remain unranked and visibly labelled map-grid estimates.

## Required follow-up gates

- Confirm the starter-kit licence and whether its restricted golden fixture bytes may be committed.
  Retain their recorded source hashes and atlas contract.
- Freeze sanitized contracts for arbitrary-polygon `assemble_pack`, `publish_answer`, trace fields,
  and receipt resolution.
- Approve delegated-auth retry behavior, evidence cache/derivative licences, legal-table ownership,
  AOI/tile quotas, retention, model, and role mappings.
- Add API and worker wiring only after the relevant gates have tests and fail-closed configuration.
