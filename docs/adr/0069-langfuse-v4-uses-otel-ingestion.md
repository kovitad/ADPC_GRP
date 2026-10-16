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
- Export each completed AI-call record as one OTel generation under a `grp-ai-call` trace.
- Derive the OTel trace ID deterministically from GRP's request ID.
- Preserve the existing privacy boundary: export only model, prompt-version identifier, token
  counts, timestamps, duration, outcome, channel, Hub code and a pseudonymous person reference.
  Never export prompts, answers, email addresses or credentials.
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
SDK and OpenTelemetry dependencies. Historical rejected calls are not recreated. The current
post-call exporter records the real provider timestamps as metadata; richer nested question,
provider and tool timing remains the separate collector work described by ADR-0035.
