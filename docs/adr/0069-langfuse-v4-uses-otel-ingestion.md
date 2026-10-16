# ADR-0069: Langfuse v4 uses OTel ingestion

- **Status:** Accepted
- **Date:** 15 October 2026

## Context

GRP exported metadata-only AI records by posting legacy `trace-create` and `generation-create`
events to `/api/public/ingestion`. That contract worked with the earlier Langfuse Cloud setup.
The dedicated Langfuse 4.59.0 deployment runs in `events_only` mode. It returns HTTP 207 for the
legacy batch, with every trace and generation rejected as `Event type not accepted`. GRP treated
any 2xx response as success, so the rejection was silent and the Evaluation project remained
empty.

A controlled metadata-only check proved that the Langfuse 4 Python SDK's OTel path writes an
observation to the dedicated deployment and that `/api/public/v2/observations` can read it back.
Changing the server to migration `dual` mode would restore the legacy endpoint temporarily, but
would retain a deprecated integration and add an avoidable server migration dependency.

## Decision

- Use Langfuse Python SDK 4.x as a runtime dependency for AI telemetry.
- Export each completed standalone AI-call record as one OTel generation under a `grp-ai-call`
  trace. For Planning, collect related calls and MCP operations under one
  `grp-planning-question` trace with generation and tool children.
- Derive the OTel trace ID deterministically from GRP's request ID.
- Group calls made during one signed-in GRP login under a one-way hashed Langfuse session
  reference. Never export the real login-session identifier or cookie.
- MCP children export only tool name, timing, safe outcome/error category and allow-listed
  pack/receipt/report identifiers; never arguments, results, tokens, place text or question text.
- Export metadata by default: model, prompt-version identifier, token counts, timestamps,
  duration, outcome, channel, Hub code and a pseudonymous person reference. ADR-0035's explicit
  non-production, account-allow-listed stakeholder mode may additionally export Planning and AI
  input/output content. Never export email addresses, credentials, real session identifiers or raw
  MCP arguments/results.
- Run SDK creation, flush and shutdown in a worker thread because telemetry is best-effort and
  must not block the request event loop.
- Keep telemetry failure independent of the GRP response and official `llm_usage` record.
- Keep production export disabled until the operational gates in ADR-0068 are complete.
- Treat the host, public key and secret key as one project-bound configuration set. Deployments
  with a blank or partial set do not export, so application and database migrations do not require
  Langfuse credentials or copy a developer's local key.

## Consequences

The dedicated Langfuse v4 server no longer needs `dual` write mode. New GRP AI calls appear in
the project selected by its API key. The runtime image is larger because it includes the Langfuse
SDK and OpenTelemetry dependencies. Historical rejected calls are not recreated. The question-scoped collector approved by the
16 October 2026 amendment to ADR-0035 groups Planning generations and tools and records their real
operation durations in metadata. Native Langfuse latency remains near zero because completed
records are exported after each operation; opening live OTel spans at operation start remains
follow-up work.
