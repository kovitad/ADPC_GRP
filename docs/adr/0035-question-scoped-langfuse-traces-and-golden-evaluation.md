# ADR-0035: Question-scoped Langfuse traces and golden evaluation

**Status:** Proposed (owner decisions recorded 1 October 2026; the reviewer assignment is
unconfirmed)

**Date:** 2026-10-01

**Deciders:** Product Owner, Technical Lead, and the acceptance reviewer once confirmed

## Context

`api/langfuse.py` creates one trace per LLM call. It records no MCP calls, cached tokens or
cost, and it stores missing usage as 0. Failed requests are probably never exported: the export
is a FastAPI background task, which does not run when the endpoint raises.

The task "Integrate Langfuse for GRP usage monitoring and answer evaluation" needs four things:

- one trace per question;
- cost per question;
- failures that are visible;
- a reviewed golden evaluation.

The planning assistant is the only path that makes MCP calls, and it stays dev-only under
ADR-0004. The full task text and design are in
[`docs/langfuse-observability-plan.md`](../langfuse-observability-plan.md).

## Decision

1. **Scope.** The assistant is instrumented in development only. Telemetry improvements in shared
   code also apply to staging's existing AI calls: result explanation and the admin test call.
   User-visible behaviour and assistant availability do not change.
2. **Traces.** Each question gets one Langfuse trace, created by a request-scoped collector:
   - LLM calls become generations.
   - SIG MCP calls become client-side spans.
   - The collector is flushed in `finally`, off the request path.
   - The trace ID appears in application logs.
3. **Retries.** There are no retries today and none are added. A timeout appears as one failed
   tool call.
4. **Usage and cost.** Token usage is exported as exclusive buckets:
   - `input`
   - `input_cached_tokens`
   - `output`
   - `output_reasoning_tokens`

   Usage is recorded as complete, partial or unavailable, and unavailable is never stored as 0.
   Cost comes from checked-in model price definitions that carry their price date.
5. **Environments.** The Langfuse environment equals `GRP_ENV`, with one project per
   environment. Evaluation runs use `environment=evaluation`.
6. **Privacy.**
   - Traces are metadata-only by default.
   - Masked question and answer text is exported only when an **approved evaluation case** is
     run under a **named test account** on `LANGFUSE_EVAL_TEXT_ACCOUNTS`. A test account alone
     never enables it.
   - The privacy documentation, starting with the `api/langfuse.py` statement that prompts and
     answers are never sent, is updated before the allow-list is populated.
7. **Integration.** GRP uses Langfuse's public ingestion API (`POST /api/public/ingestion`) with
   batched `trace-create`, `span-create` and `generation-create` events. An SDK version is
   recorded only if an SDK is introduced.
8. **Failure handling.** Telemetry failures never block an answer. Rejected or unreachable
   exports are logged and counted. Quota behaviour comes from Langfuse support or a controlled
   test, and is otherwise documented as unconfirmed.
9. **Evaluation.**
   - Golden Q&A cases are kept in Git (`tests/golden/qa/`) and mirrored to a Langfuse dataset.
   - Code scores four checks, each pass, fail or not assessable, with a reason.
   - Missing results are never counted as passes.
   - LLM judging is follow-up scope.
10. **Access.** The Langfuse Cloud Hobby plan is used. Its two seats are individual accounts for
    one developer and one reviewer; there is no shared login.
11. **Evidence.** Sanitised JSON exports or screenshots are committed beside the completion
    report, so the evidence survives hosted-data expiry.
12. **Boundary.** GRP never presents its partial figures as total cost. Claude Desktop's model
    usage and SIG-internal processing are documented gaps.

## Options considered

- **Adopt the Langfuse Python SDK (OTel based).** The SDK has a richer API. Rejected for now: it
  adds a dependency and global OTel state to a codebase that exports with plain httpx.
- **Export all content, masked.** Simpler for reviewers. Rejected: it would send planners'
  questions to a hosted service, against the current promise.
- **Enable text export for any test account.** Rejected: interactive test use can contain real
  questions. Text export is tied to approved cases.
- **Count missing usage as 0, or let Langfuse estimate it with a tokenizer.** Rejected: both
  hide gaps in the cost figure.
- **Add read-only retries now.** Deferred to follow-up scope.

## Consequences

- Migration `20261001_0022` makes the `llm_usage` token columns nullable. It adds usage status,
  cached-token and reasoning-token columns.
- Staging traces become question-scoped and honest about usage, with no change to what users
  see.
- The 1,000-question projection describes development traffic until the assistant moves beyond
  development.
- Hosted traces expire after 30 days on the free plan, so durable evidence lives in the
  repository.

## Dependencies

- **Reviewer assignment is not confirmed.** Ole is proposed as the initial acceptance reviewer,
  with Daniel supporting domain-reference questions. This must be confirmed before tolerances
  are agreed and before evaluation sign-off.
- The developer who holds the second Langfuse seat is still to be named.
- Spec Section 14.1 (outside Git) needs a matching amendment for the evaluation text exception.

## Action items

- [ ] Steps L0-L9 in the plan, implemented and tested
- [ ] Privacy documentation updated before the evaluation text exception is enabled
- [ ] Setup and troubleshooting guide, sanitised evidence, and handover update
- [ ] Reviewer assignment confirmed, and at least 10 golden cases approved
