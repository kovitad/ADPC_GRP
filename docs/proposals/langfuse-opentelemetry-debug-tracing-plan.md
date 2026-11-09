# Langfuse OpenTelemetry debug tracing plan

**Status:** Proposed  
**Date:** 9 November 2026  
**Scope:** Local development and explicitly approved evaluation deployments only

## Purpose

Give developers one useful trace for each AI-assisted GRP question, including the question,
answer, model calls, governed SIG MCP calls, outbound HTTP timing, retries, timeouts and safe error
details. Preserve GRP's secret, Hub and personal-data boundaries even when debug content capture is
enabled.

This plan does not authorize production content capture. Implementation requires an ADR amendment
before deployment outside local development or GRP Evaluation.

## Documentation reviewed

1. [Langfuse OpenTelemetry integration](https://langfuse.com/integrations/native/opentelemetry)
2. [OpenTelemetry HTTP spans](https://opentelemetry.io/docs/specs/semconv/http/http-spans/)
3. [OpenTelemetry context propagation](https://opentelemetry.io/docs/concepts/context-propagation/)
4. [OpenTelemetry recording errors](https://opentelemetry.io/docs/specs/semconv/general/recording-errors/)
5. [OpenTelemetry Python instrumentation](https://opentelemetry.io/docs/languages/python/instrumentation/)
6. [OpenTelemetry HTTPX instrumentation](https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation/httpx/httpx.html)
7. [OpenTelemetry FastAPI instrumentation](https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation/fastapi/fastapi.html)
8. [Langfuse with an existing OpenTelemetry setup](https://langfuse.com/faq/all/existing-otel-setup)

The key findings are:

- Langfuse v4 accepts OTLP over HTTP at `/api/public/otel`; the Python Langfuse SDK is preferred for
  Python and already handles Langfuse attribute mapping and export.
- Langfuse filtering and aggregation require trace attributes such as user, session, trace name and
  metadata on every relevant span. `propagate_attributes()` is preferred when using its SDK.
- Generic HTTP spans are not exported by Langfuse's default LLM-focused filter. GRP must explicitly
  include its approved HTTP/tool scopes without enabling every infrastructure span.
- HTTP client spans should represent each wire attempt where possible and use stable semantic
  convention fields. Request and response bodies and headers are opt-in and sensitive.
- Failed operations should set span status `ERROR`, a low-cardinality `error.type`, and one exception
  event where appropriate. Successfully handled or retried errors must not make the final logical
  operation fail.
- W3C trace context can cross service boundaries, but incoming context from untrusted callers and
  outgoing baggage to third parties must be treated as a security boundary.

## Current GRP gaps

The repaired `main` branch exports one completed AI generation after the call. It does not yet:

- create one root trace for a complete user question;
- retain the question and answer in approved debug mode;
- show live parent-child timing for router, draft, MCP and HTTP operations;
- distinguish connect, read, write and pool timeouts;
- represent HTTP status, retries and redirects with OpenTelemetry semantic fields;
- propagate context into detached tasks or durable worker jobs;
- export generic HTTP spans through Langfuse's default filter.

The pilot branch contains a useful question collector, session hashing and account-allow-listed
content capture. It should be ported as a starting point, but its completed-after-the-fact child
records should be replaced incrementally with live spans.

## Proposed trace model

One user action produces one trace:

```text
grp.question (root chain)
├── grp.route                         span
├── ai.planning-router-v3             generation
│   └── HTTP POST api.openai.com      client span
├── mcp.initialize                    tool
│   └── HTTP POST servirplatform...   client span
├── mcp.assemble_pack                 tool
│   └── HTTP POST servirplatform...   client span
├── ai.planning-draft-v5              generation
│   └── HTTP POST api.openai.com      client span
├── grp.validate-answer               guardrail
└── grp.prepare-response              span
```

Use a separate root name for other channels, such as `grp.assessment-explanation`,
`grp.flood-answer` and `grp.platform-ai-test`. A deterministic operation name and prompt version
must be used instead of question text in span names.

### Trace-level fields

| Field | Value |
|---|---|
| `langfuse.trace.name` | Stable workflow name, such as `grp-planning-question` |
| `langfuse.user.id` | Existing one-way `grp-…` person reference |
| `langfuse.session.id` | One-way `grp-session-…` login-session reference |
| `langfuse.environment` | `development` or approved `evaluation` |
| `langfuse.trace.metadata.hub_code` | Non-secret Hub code |
| `langfuse.trace.metadata.route` | Low-cardinality route template, not the raw URL |
| `langfuse.trace.metadata.release` | Git SHA or immutable image tag |
| `langfuse.trace.metadata.capture_mode` | `metadata` or `allowlisted-content` |

Apply these fields to every exported span through `propagate_attributes()`. Do not put email,
question text, access tokens, cookies or raw session IDs into attributes or baggage.

### HTTP client fields

Use the stable OpenTelemetry names:

- `http.request.method`
- `server.address` and `server.port`
- `url.full`, with user info removed and all query values removed or redacted
- `http.response.status_code`, only when a response was received
- `http.request.resend_count`, for each retry or redirect after the first attempt
- `network.protocol.version`, when HTTPX exposes it reliably
- `error.type`, only on failed attempts

GRP-specific filterable metadata may additionally include:

- `langfuse.observation.metadata.service`: `openai`, `sig-mcp`, or another approved service
- `langfuse.observation.metadata.operation`: stable API/MCP operation
- `langfuse.observation.metadata.timeout_phase`: `connect`, `read`, `write`, or `pool`
- `langfuse.observation.metadata.retryable`: boolean
- `langfuse.observation.metadata.response_bytes`: bounded integer

Do not capture `Authorization`, `Cookie`, `Set-Cookie`, MCP session headers, API keys or complete
query strings. Do not enable wildcard header capture. Request/response body capture remains off for
generic HTTP spans.

### Error handling

Map errors consistently:

| Condition | `error.type` | Status |
|---|---|---|
| `httpx.ConnectTimeout` | `timeout.connect` | `ERROR` |
| `httpx.ReadTimeout` | `timeout.read` | `ERROR` |
| `httpx.WriteTimeout` | `timeout.write` | `ERROR` |
| `httpx.PoolTimeout` | `timeout.pool` | `ERROR` |
| DNS/connect failure | stable exception class or `network.connect` | `ERROR` |
| HTTP error response | status code as a string, for example `503` | `ERROR` |
| MCP protocol rejection | `mcp.protocol_error` | `ERROR` |
| Invalid upstream document | `upstream.invalid_response` | `ERROR` |
| User cancellation | `cancelled` | `ERROR` on cancelled attempt |

Record an exception once at the lowest span that owns the failure. Sanitize its message; never
export response bodies, token fragments, file paths or headers as exception text. A retry attempt
may fail while the enclosing logical operation succeeds; in that case only the attempt is marked
failed.

## Development content capture

Content capture must fail closed behind all of these controls:

1. `GRP_ENV` is exactly `dev` or `evaluation`.
2. `LANGFUSE_CAPTURE_CONTENT=true`.
3. The authenticated email is in `LANGFUSE_EVAL_TEXT_ACCOUNTS`.
4. The destination key is verified as the GRP Evaluation project.
5. The trace records `capture_mode=allowlisted-content`.

For an allow-listed tester, Langfuse may receive:

- the user's question as root input;
- the final GRP answer as root output;
- model instructions and model input on each generation;
- model output on each generation;
- a redacted, size-bounded summary of MCP tool arguments and results.

Apply recursive redaction before export. Block keys matching at least `authorization`, `token`,
`secret`, `password`, `cookie`, `api_key`, `email`, `tel`, `fax`, `address` and MCP session IDs.
Limit each text value and serialized document, record truncation metadata, and refuse binary data.
Raw uploads, raw GIS layers and source responses are never trace content.

Production must ignore or reject content-capture settings. Metadata-only production export remains
a separate operational approval.

## Context propagation

### Inside one API process

- Start the root span only after authentication and content-capture eligibility are known.
- Keep it current while routing, model and MCP child spans execute.
- Python `contextvars` normally flow through awaited coroutines and `asyncio.create_task()` at task
  creation. Add explicit tests for FastAPI `BackgroundTasks`, detached SIG jobs and
  `asyncio.to_thread()`.
- Pass context explicitly when lifecycle or task boundaries make implicit inheritance ambiguous.

### Browser to API

Do not trust caller-supplied `traceparent`, `tracestate` or `baggage` for authenticated product
traces. Start a new server-side trace and return only an opaque GRP request ID where needed. This
prevents forged parents and trace injection from public clients.

### API to external providers

Create local child spans around OpenAI and SIG MCP calls, but do not propagate GRP `baggage` to
third-party hosts. Initially do not inject W3C `traceparent` either; provider correlation should use
an approved provider request ID stored as a redacted attribute. Revisit propagation only if the
provider documents and approves it.

### API to GRP-owned services and worker

For a future GRP-owned HTTP service, inject/extract W3C `traceparent` and `tracestate`; baggage may
contain only low-risk flags such as `grp.trace.kind=debug`.

The current worker boundary is a database queue, not HTTP. Add nullable `traceparent` and
`tracestate` columns to the specific job tables only when worker correlation is needed. Validate
length and W3C syntax on write, extract in the worker, create a linked worker span, and never store
baggage, content, identity or credentials in queue rows. A job may outlive trace retention, so the
job ID remains the operational source of truth.

## Implementation phases

### Phase 1 — Gated question traces

- Port the reviewed question collector, session hashing and account allow-list from the pilot
  branch.
- Add settings and Docker wiring for content capture, defaulting to false/empty.
- Group Planning router, draft, explanation and platform test generations under one root.
- Capture question/answer content only for the allow-listed development account.
- Keep metadata-only behavior for every other user.

**Acceptance:** one Planning question appears as one trace with ordered generations; another user's
question has no content fields.

### Phase 2 — Live AI and MCP spans

- Replace completed-after-the-fact synthetic durations with live Langfuse observations.
- Add tool spans around MCP initialize and each tool call.
- Capture safe tool summaries, status and bounded identifiers; never delegated tokens or raw MCP
  headers.
- Preserve telemetry failure isolation from the user response.

**Acceptance:** Langfuse duration matches measured operation time and an MCP timeout appears on the
correct child span.

### Phase 3 — HTTP semantic spans

- Add the pinned HTTPX instrumentation dependency.
- Prefer instrumentation of approved client instances over global HTTPX instrumentation.
- Add hooks or wrappers for URL sanitization, service naming and timeout classification.
- Configure a Langfuse export filter that includes the GRP root, generation, tool and approved HTTP
  scopes only. Do not export health checks, OIDC discovery, arbitrary feeds or Langfuse's own
  export request.
- Ensure the OTLP exporter cannot recursively trace itself.

**Acceptance:** OpenAI and MCP attempts show method, sanitized host/path, status, duration, retries
and timeout phase; no authorization/cookie/MCP-session data appears.

### Phase 4 — Cross-service correlation

- Add explicit context handoff tests for detached API tasks.
- Add W3C propagation only between GRP-owned HTTP services.
- Add migration-backed queue context only for selected worker jobs with a demonstrated debugging
  need.
- Treat malformed/external context as untrusted and start a new trace.

**Acceptance:** an API request and selected worker execution share a trace or validated span link,
while third-party requests receive no GRP baggage.

### Phase 5 — Operations and removal controls

- Add a protected readiness view showing configured project name, environment, capture mode and
  allow-list count, never key values or account names.
- Add trace-volume and export-failure metrics and an upper bound per question.
- Define Evaluation retention and a deletion procedure for accidental content capture.
- Add a one-command kill switch and prove metadata-only fallback.
- Review whether debug content capture should be removed after the test period.

## Tests

At minimum, add tests for:

- all content-capture gates and production fail-closed behavior;
- recursive secret/contact-field redaction and truncation;
- one root with correct child hierarchy and hashed user/session values;
- HTTP success, 4xx, 5xx, connect/read/write/pool timeout and retry attributes;
- no secret headers, query values, raw MCP arguments or binary content;
- exception recorded once with stable `error.type`;
- context across await, detached task and thread boundaries;
- rejection of forged/malformed incoming context;
- no propagation of baggage to OpenAI, SIG or other external hosts;
- worker queue context validation if Phase 4 is implemented;
- Langfuse outage never changes the GRP response or official usage record;
- a Docker read-back proof through `/api/public/v2/observations`.

## Rollout and rollback

1. Implement on `main` with capture off by default.
2. Run offline unit/contract tests and secret-canary tests.
3. Enable for one approved account in local `dev` and generate synthetic questions first.
4. Inspect every exported field in GRP Evaluation before using a real question.
5. Exercise success, timeout, provider error, MCP error and cancellation cases.
6. Disable capture and prove new traces revert to metadata-only.
7. Do not enable on Staging or Production without a new approval and retention decision.

Rollback is configuration-first: set `LANGFUSE_CAPTURE_CONTENT=false`, clear the account allow-list,
and restart the API. If span export itself is unsafe, clear the Langfuse host/key configuration;
GRP must continue operating without telemetry.

## Decisions required before implementation

1. Confirm the single initial allow-listed tester account.
2. Approve maximum question, answer and tool-summary sizes.
3. Approve Evaluation retention and who may view/delete captured content.
4. Decide whether SIG MCP argument/result summaries may include place names and public dataset IDs.
5. Decide which worker job types genuinely need cross-process tracing.
6. Confirm that external providers must receive no `traceparent`, or document an approved exception.
