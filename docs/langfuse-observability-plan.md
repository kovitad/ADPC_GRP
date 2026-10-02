# Langfuse usage monitoring and answer evaluation: current state and plan

**Status:** proposed, revised 1 October 2026 after owner decisions. Decisions are recorded in
[ADR-0035](adr/0035-question-scoped-langfuse-traces-and-golden-evaluation.md).

## 1. Task as agreed

**Objective.** Monitor model usage, estimated cost and response times. Evaluate first-slice
answers against the Thailand Hub's Golden Questions & Answers.

**Initial scope.**

- Instrument the assistant in the **development environment**, following the current development
  review (ADR-0004).
- Cover ADPC-controlled LLM calls, and outbound MCP requests where those calls occur.
- Telemetry improvements in shared code (`api/ai_gateway.py`, `api/langfuse.py`) also improve
  what staging exports for its existing AI calls: result explanation and the admin test call.
- User-visible behaviour and assistant availability remain unchanged in every environment. The
  planning assistant stays dev-only.

### Acceptance criteria

**AC1. Trace questions and failures**

- Each question produces a trace that links its input, LLM calls, tool calls and final answer.
- Errors and timeouts identify the failed step.
- No retries exist today. A timeout appears as one failed tool call. Adding retries is outside
  this task.

**AC2. Capture relevant context**

- Each trace includes the environment, hub, session ID, anonymised user ID, model, and
  application and prompt version.
- Area, hazard scenario, dataset version and receipt ID are recorded when available.
- Trace IDs connect application logs with Langfuse records.

**AC3. Record tokens and estimated model cost** *(unchanged)*

- Capture provider-reported input and output tokens, and available cache usage, for each LLM call.
- Aggregate all recorded calls into the question's estimated model cost without double counting.
- Check recorded token totals against provider responses using test examples.
- Add application metadata identifying complete, partial or unavailable usage. Report missing
  usage separately and never treat it as zero cost.

**AC4. Provide a dashboard and reproducible usage report** *(unchanged)*

- The dashboard shows question counts, failures, recorded tokens, estimated model cost and
  response times. It can be filtered by date, hub, model and environment.
- A supporting report gives:
  - the average model cost per question;
  - the projected model cost per 1,000 comparable questions;
  - the sample size, reporting period, workload and missing-usage coverage;
  - median and 95th-percentile question response times, plus slow tool calls.
- Use native metrics where supported; otherwise calculate them in a documented report script.
- Count questions separately from individual model and tool calls.
- Infrastructure and Langfuse subscription costs are manual, owner-supplied entries in the
  monthly report.
- Evaluation model costs are identified separately from application usage.

**AC5. Prepare the Golden Q&A dataset**

- Create a versioned starter dataset of at least 10 reviewed cases. It covers normal questions,
  missing data and tool failures.
- Each case has:
  - an expected answer or expected behaviour;
  - reference evidence;
  - the relevant area and scenario;
  - the data version.
- Numeric comparisons use documented tolerances agreed with the domain reviewer.
- **Dependency:** the reviewer assignment in section 2 must be confirmed before evaluation
  sign-off.

**AC6. Record evaluation results and human review**

- Record pass, fail or not assessable, each with a reason, for four checks:
  - numerical accuracy;
  - area and scenario consistency;
  - source support;
  - disclosure of limitations.
- Include checks that missing population data is not reported as zero exposure, and that TEST
  shelters are not presented as validated safe shelters.
- Authorised reviewers add scores and comments linked to the evaluated answer.
- Access stays within the free plan's two users: one developer and one reviewer, each with an
  individual account. There is no shared login. A paid upgrade is not required.

**AC7. Compare a baseline and candidate** *(unchanged)*

- Run the same dataset and evaluation rules against a baseline and one candidate model or prompt
  configuration.
- Compare quality, estimated model cost and response time.
- Identify individual regressions, failed evaluations and missing results; none of them count as
  passes.
- Save the model, prompt, application, dataset and evaluator versions with each run.

**AC8. Protect data and handle monitoring failures**

- Mask credentials and sensitive information before export.
- Export question and answer text only under the evaluation exception in section 4.5. All other
  traces are metadata-only.
- A simulated Langfuse outage, or a rejected telemetry request, does not stop the assistant from
  responding.
- Record detectable export failures and dropped telemetry. Document how to investigate incomplete
  reporting.
- Document the selected plan's ingestion, retention and user limits. For behaviour when a limit
  is reached, document findings from Langfuse support or a controlled test; otherwise mark it
  **unconfirmed**. An unconfirmed result does not block completion.
- Record the ingestion API and payload format used. Record an SDK version only if an SDK is
  introduced.

**Completion evidence**

- sample trace links;
- dashboard access;
- the usage report;
- the evaluation dataset;
- the baseline and candidate comparison;
- a short setup guide.

Demonstrate four cases: a successful question, a missing-data answer, a tool timeout and a
telemetry failure.

Hosted data expires after 30 days on the free plan. So that evidence stays usable after that,
save sanitised JSON exports or screenshots in the repository beside the completion report, with
credentials and sensitive content removed (section 4.8).

**Integration boundary** *(unchanged)*

This task measures activity visible to the ADPC application. Measuring Claude Desktop's internal
model usage and SIG-managed internal processing needs separate access or instrumentation. Those
gaps are documented, and partial measurements are never presented as total cost.

**Follow-up scope** *(unchanged)*

- deploying the assistant to staging or production;
- new retry behaviour;
- paid-plan upgrades;
- automated LLM judging;
- release gates.

## 2. Decisions and dependencies

| # | Topic | Decision | Status |
|---|---|---|---|
| D1 | Environment | Development only for the assistant. Shared-code telemetry improvements also apply to staging's existing AI calls (option a). No user-visible or availability change. | Decided |
| D2 | Question and answer text | Masked text only for **explicitly approved evaluation cases** run through **named test accounts**. Both conditions are required: a test account alone never enables text export. Everything else is metadata-only. The privacy documentation must be updated first (section 4.5). | Decided |
| D3 | Retries | None today, and none added. A timeout is one failed tool call. | Decided |
| D4 | Reviewer | **Proposed:** Ole as initial acceptance reviewer, with Daniel supporting domain-reference questions. | **Dependency: not yet confirmed.** Needed before tolerances are agreed and before evaluation sign-off |
| D5 | Langfuse plan and access | Langfuse Cloud Hobby (free). Its two seats go to one developer and one reviewer, each with an individual account; there is no shared login. One project per environment. | Decided. Which developer gets the seat is still to be named; the reviewer seat follows D4 |
| D6 | Quota behaviour | Ask Langfuse support, or run a controlled test, to find out what happens when the 50,000-unit monthly limit is reached. Otherwise mark it unconfirmed. | Open; does not block completion |

**Free-plan limits** (Langfuse pricing and API-limits pages, checked 1 October 2026):

- 50,000 units a month, where a unit is one trace, observation or score. One question is about
  10-12 units.
- 30 days of data access.
- 2 users.
- 1 annotation queue.
- Rate limits, per organisation and shared across projects:
  - ingestion: 1,000 requests a minute;
  - Metrics API: 100 requests a day;
  - general API: 30 requests a minute;
  - datasets: 100 requests a minute.
- Data regions: US, EU or Japan.
- Masking happens client-side, in GRP. Server-side masking is not available on Cloud.

## 3. What exists today

| Area | Current implementation | Gap against the acceptance criteria |
|---|---|---|
| Exporter | `api/langfuse.py` posts a raw `trace-create` and `generation-create` batch to `/api/public/ingestion` over httpx. There is no SDK. It is best effort and swallows failures. | It is the right shape for AC8 (non-blocking). Everything else in this table is missing. |
| Trace granularity | `run_ai_call` (`api/ai_gateway.py:132`) uses its own `request_id` as the trace ID. | **One trace per LLM call, not per question.** A planning question makes two LLM calls (router `planning-router-v*`, draft `planning-draft-v5`), and they land in two unrelated traces. Fails AC1. |
| MCP calls | `SigMcpClient` (`api/mcp_client.py`) calls `assemble_pack`, `publish_answer`, `ui_embed` and `contribute_*`. It has a 45 s timeout and no retry. | **Not traced at all.** Fails AC1 and AC4 (slow tool calls). |
| Errors | The export is queued with `background.add_task`, and `run_ai_call` then raises on a provider error. The SIG failure path raises `GrpError` after the router export was queued. | FastAPI does not run background tasks when the endpoint raises. In the lookup job (`api/planning.py:1636-1642`), `await tasks()` is skipped when `planning_chat` raises or `wait_for` cancels it. **Failed questions are probably never exported.** Step L0 confirms this with a test first. |
| Usage | Reads `usage.input_tokens` and `usage.output_tokens` from the OpenAI Responses API, with `or 0`. `ProviderError()` defaults to 0. The `llm_usage` columns are `NOT NULL default 0`. | **Missing usage becomes zero** (fails AC3). Cached tokens (`input_tokens_details.cached_tokens`) and reasoning tokens (`output_tokens_details.reasoning_tokens`) are dropped. |
| Cost | None. | No price definitions and no per-question cost. |
| Context | `hub_code`, `channel`, `prompt_version`, `outcome` and a hashed user ID (`person_reference`). | Missing: session ID, app version, area, hazard scenario, `pack_id`, receipt ID, dataset or shelter version, selected layers, and whether the answer was a cache hit or reused evidence. |
| Environment | `LANGFUSE_ENVIRONMENT` falls back to `GRP_ENV`. Compose and the Ubuntu launcher default it to `development`. | **A staging VM would report as `development`.** Fails AC2 and AC8. |
| Privacy statement | The `api/langfuse.py` docstring says prompts and answers are never sent. Spec Section 14.1 is cited. | The evaluation exception (D2) must be documented before it is enabled. |
| Evaluation | `tests/golden` holds GIS numeric goldens. Backlog Epic V (V1-V4) designs a three-lane harness; nothing is built. | No Langfuse dataset, runner, scores or comparison. |

## 4. Design

### 4.1 One trace per question

- `api/telemetry.py` provides a request-scoped `QuestionTrace` collector, held in a
  `contextvars.ContextVar`. It holds a trace ID, the observations and the context fields in
  section 4.4.
- The collector is opened at the entry of `_answer_chat`, `explain_stored_result` and
  `ai_test_call`.
- `run_ai_call` adds a `generation` to the current trace. Its `request_id` stays the generation
  ID and the `llm_usage` key, so GRP's official record joins Langfuse on it.
- `SigMcpClient.call_tool` adds a client-side `span` recording:
  - the tool name;
  - the duration;
  - `isError`;
  - the `pack_id` or receipt ID;
  - the error class (`timeout`, `http_5xx`, `auth`, `invalid_response`).

  It exports no arguments and no results, and never touches the SIG token. A timeout appears as
  one failed span with level `ERROR`. No retry is attempted (D3).
- GRP steps that are already timed become spans: `grp_baseline_evidence`, `area_check` and
  `draft_gate`. `cache_hit` and `evidence_reused` become events.
- **Flush in `finally`.** The trace is exported on success, on `GrpError`, on provider failure
  and on cancellation. The export is a fire-and-forget `asyncio` task with its own short
  timeout. It replaces `export=` and `background.add_task(send_ai_call…)` at all four call sites
  and in the lookup job.
- **What counts as a question.** One trace is created per call to `/planning/chat`,
  `/planning/lookup`, `/assessments/{id}/explain` or `/ai/test-call`.
  - Each trace is tagged `question_kind`: `new`, `area_confirmation`, `resend` or `cache_hit`.
  - Question counts use `new`.
  - A cache hit has zero LLM cost by fact. It is never labelled unavailable.
- The trace ID is written to the `grp.ai` and `grp.langfuse` log lines and returned in a
  `X-GRP-Trace-Id` response header, so logs and Langfuse records connect (AC2).

### 4.2 Usage that is honest about what it does not know

- `call_openai` returns a `Usage` value with `input`, `input_cached`, `output` and
  `output_reasoning`, each `int | None`. It also returns `status`: `complete`, `partial` or
  `unavailable`.
- Langfuse buckets are exported **exclusively**:
  - `input` = `input_tokens − cached_tokens`
  - `input_cached_tokens`
  - `output` = `output_tokens − reasoning_tokens`
  - `output_reasoning_tokens`

  Flat `usageDetails` are stored unchanged, so overlapping buckets would double count. The
  legacy `usage.total` block is dropped.
- When usage is unavailable, the generation is sent **without** `usageDetails` and with
  `metadata.usage_status="unavailable"`. Langfuse is not allowed to estimate it with a
  tokenizer.
- **Migration** `20261001_0022`:
  - makes the `llm_usage` token columns nullable;
  - adds `usage_status`, `cached_input_tokens` and `reasoning_tokens`.

  The allowance keeps charging the reservation estimate when usage is unavailable, so AI-09 and
  AI-12 still hold.
- `ProviderError` carries `Usage | None` instead of zero defaults.
- **Token test examples (AC3).** Recorded provider response fixtures are kept in
  `tests/fixtures/openai_responses/`. They cover:
  - full usage;
  - cached and reasoning tokens;
  - no usage block;
  - an error with usage.

  Tests assert the bucket arithmetic and that the totals reconcile.

### 4.3 Cost

- `deploy/langfuse/models.json` holds custom model definitions, such as `gpt-5.2`, registered
  through `POST /api/public/models`.
  - Price keys must match the usage bucket names exactly.
  - Prices come from the provider's pricing page on the day of setup and are recorded with that
    date.
- Langfuse infers cost at ingestion. Per-question cost is the sum of the trace's generations.
- `scripts/langfuse_usage_report.py` produces the AC4 report through the Metrics API. It is
  written for the Hobby limit of 100 requests a day: a handful of grouped queries per run. It
  reports:
  - mean cost per `new` question;
  - × 1,000;
  - `n`;
  - the period;
  - the workload mix by mode;
  - missing-usage coverage;
  - p50 and p95 question latency;
  - slow tool spans.

  Manual infrastructure and Langfuse subscription rows are entered by the owner. Evaluation cost
  is reported from the `evaluation` environment.

### 4.4 Context on every trace

| Field | Source | Notes |
|---|---|---|
| `userId` | `person_reference(user_id)` | Already hashed |
| `sessionId` | `sha256(principal.session_id)` | The raw session ID is never sent |
| `environment` | `GRP_ENV` | Startup logs an error and uses `GRP_ENV` when `LANGFUSE_ENVIRONMENT` disagrees |
| `release` / `version` | git SHA baked into the image (`GRP_RELEASE`) | New build argument |
| `metadata.hub_code`, `channel`, `question_kind`, `mode`, `answer_source` | Request and response | |
| `metadata.prompt_versions` | `ROUTER_VERSION`, `DRAFT_VERSION`, `EXPLAIN_VERSION` | |
| `metadata.area` | `area.sig_place`, boundary `admin_code` and level | Admin code, not free text |
| `metadata.hazard`, `return_period` | Pack request; assessment `scenario` | |
| `metadata.pack_id`, `receipt_id`, `evidence_assembled_at`, `evidence_reused` | Pack and receipt | `null` when unavailable |
| `metadata.dataset_versions` | Shelter version, boundary edition, baseline release, `selected_layers` | |
| `tags` | `env:`, `hub:`, `model:`, `kind:` | Dashboard filters |

### 4.5 Privacy: metadata-only by default, with a narrow evaluation exception

- **Default.** Every trace is metadata-only: no question text, answer text, prompt, citation text
  or tool payload. This includes questions typed interactively by test accounts.
- **Exception.** Masked question and answer text is exported only when **both** of these hold:
  1. The question is an **approved evaluation case**. It is run by the evaluation runner from a
     dataset item whose `approved: true` is recorded in the versioned dataset file.
  2. The run uses a **named test account** on the allow-list `LANGFUSE_EVAL_TEXT_ACCOUNTS`.

  The exporter checks both conditions on every trace. A test account alone, or an approved case
  run by any other account, stays metadata-only. A fast test covers each combination.
- **Masking** runs before any export. It removes or redacts:
  - bearer and API keys;
  - JWTs;
  - `publish_token`;
  - email addresses;
  - phone and fax numbers;
  - volunteer `TEL`, `FAX`, `EMAIL` and address fields;
  - raw session and user IDs.

  It is tested against a corpus of realistic but fake secrets.
- **Before enabling (step L4a):**
  - rewrite the `api/langfuse.py` docstring;
  - record the exception in ADR-0035 and in the setup guide;
  - tell the owner which line in spec Section 14.1 needs the matching amendment. The spec
    `.docx` is outside Git.

  The allow-list ships empty, and text export stays off until this step is merged.

### 4.6 Monitoring failures

- Langfuse calls use a 3 s connect and 5 s total timeout, off the request path.
- A rejected request (4xx, including 429 or a quota response) or an unreachable host logs one
  `grp.langfuse` warning with the trace ID, HTTP status and error class. It also increments a
  dropped-telemetry counter, shown on `/platform.html` next to `langfuse_configured`.
- The guide explains how to investigate incomplete reporting: compare `llm_usage` rows with
  Langfuse generations for the same period, joined on `request_id`, and read the warning log.
- **Outage test:** a fast test with a fake transport that hangs, returns 503 or returns 429. The
  answer is returned on time, and the warning and counter are recorded. The same is
  demonstrated live with `LANGFUSE_HOST` pointed at a dead endpoint.
- **Quota behaviour (D6):** ask Langfuse support. If there is no answer, run a controlled test
  in a throwaway project, if one can be exhausted safely. Otherwise record the behaviour as
  **unconfirmed**. GRP's behaviour is the same either way: the answer is returned and the
  telemetry loss is counted.

### 4.7 Golden Q&A evaluation

This builds on backlog Epic V lanes V1-V3, which code checks. V4, the LLM judge, is follow-up
scope.

- **Dataset.** `tests/golden/qa/thailand_hub_v1.yaml` is the source of truth and is versioned. It
  is mirrored to the Langfuse dataset `thailand-hub-golden-v1`. Each case records:
  - the question;
  - the area (admin code) and scenario;
  - the frozen evidence fixture;
  - the expected answer or behaviour;
  - reference sources;
  - data versions;
  - tolerances;
  - `case_type`;
  - `approved`, `reviewed_by` and `reviewed_on`.

  Until D4 is confirmed, every case stays `approved: false`, and the run reports it as draft.
- **Frozen evidence.** Each case pins a stored pack, injected through the `stored_pack` path or a
  fake `SigMcpClient`. A comparison therefore varies only the model or prompt. Tool-failure
  cases inject a timeout or `isError` from the fake.
- **Draft seed cases (12):**
  1. Chiang Yuen RP100 result explanation (`01a0d226…`): counts and depths.
  2. Kanthararom district evidence: 34 centres, 18 volunteer centres, 175 villages.
  3. Kanthararom early-warning resources: 0 records must read as "no records", not "none exist"
     *(missing data)*.
  4. A sub-district question answered as district-wide SIG context, with the disclosure.
  5. A district with no centre records (`NO_CENTRES_REPLY`).
  6. A population question with population missing: it must not say "0 people exposed"
     *(missing data)*.
  7. A contributed `*_test` layer: it must not be called a validated safe shelter.
  8. Bang Bua Thong area resolution, and rejection of the wrong province.
  9. An ambiguous place: `needs_area_confirmation`, with no SIG call.
  10. A brief that cites GRP figures: the receipt is withheld (ADR-0028).
  11. An `assemble_pack` timeout: one failed tool span, `SIG_UNAVAILABLE`, no invented answer
      *(tool failure)*.
  12. An `assemble_pack` result with `isError`: the same outcome *(tool failure)*.
- **Runner.** `scripts/run_golden_eval.py --config baseline|candidate` runs under a named test
  account into `environment=evaluation`. Run metadata records:
  - the git SHA;
  - the model;
  - the prompt versions;
  - the dataset version;
  - the evaluator version (`grp-eval-v1`).
- **Scores.** Each check is a categorical score with the values `pass`, `fail` and
  `not_assessable`, and a reason in `comment`:
  - `numeric_accuracy`;
  - `area_scenario_version`;
  - `attribution`;
  - `limitations_disclosed`.

  `limitations_disclosed` includes the zero-exposure and TEST-shelter rules. The reviewer adds
  `human_review` scores and comments on the same trace.
- **Comparison.** Use the Langfuse Compare view, plus `scripts/compare_eval_runs.py`, which
  writes to `docs/evaluations/` a report with:
  - quality per check;
  - cost per case;
  - p50 and p95 latency;
  - **regressions**;
  - **failed evaluations**;
  - **missing results**.

  Missing results are never counted as passes.

### 4.8 Durable, sanitised evidence

- `scripts/export_langfuse_evidence.py` fetches the named sample traces, dataset run summaries
  and dashboard figures. It writes them to `docs/evaluations/evidence/<date>/` as JSON.
- Before writing, it reapplies the masking from section 4.5 and drops every field outside an
  allow-list. Screenshots are reviewed by hand before they are committed.
- The completion report links the hosted pages and the saved copies, so the evidence survives
  the free plan's 30-day expiry.

### 4.9 Integration boundary

ADPC can see:

- router, draft and explain LLM calls, with full usage and cost;
- GRP's client-side spans for each SIG MCP call.

ADPC cannot see:

- SIG's internal processing;
- any model SIG runs;
- Claude Desktop → SIG usage.

Langfuse MCP tracing links client and server traces only when both sides propagate W3C trace
context in `_meta`. Neither side is ADPC-instrumented, and MCP tracing does not expose the
client's model tokens. The guide lists what would close these gaps. It never presents GRP's
partial figures as total cost.

## 5. Delivery plan

| Step | Work | Size | Depends on | Done when |
|---|---|---|---|---|
| L0 | Failing tests: provider error and SIG failure each produce an exported trace; missing usage is not 0; environment mismatch | S | — | Tests demonstrate the current gaps |
| L1 | `api/telemetry.py` collector, question trace, flush in `finally`, trace ID in logs and header; replace `export=` at the 4 call sites and in the lookup job | M | L0 | Router, MCP and draft in one trace, also on failure and cancellation |
| L2 | `Usage` type, exclusive buckets, `unavailable`, migration `0022`, response fixtures | M | L0 | AC3 tests pass; `alembic upgrade head` is clean |
| L3 | MCP spans in `SigMcpClient`, with timeout as one failed span | S | L1 | The timeout case shows the failed step |
| L4 | Context fields, `GRP_RELEASE`, environment check, masking, dropped-telemetry counter | M | L1 | A sample trace carries every field; the masking corpus passes |
| L4a | Privacy documentation update, then the two-condition text exception with an empty allow-list | S | L4, D2 | Docs merged; the 4-combination test passes |
| L5 | `models.json` and registration script; per-environment projects and keys; `.env.example` | S | D5 | Cost appears on a development trace |
| L6 | Golden dataset YAML (12 drafts), Langfuse sync, runner, code checks, score configs | L | L1-L4a | One run produces 4 check scores per case |
| L7 | Reviewer confirmation, tolerances, case approval | — | L6, **D4** | ≥10 cases `approved: true` with `reviewed_by` |
| L8 | Baseline and candidate runs, comparison report | S | L7 | `docs/evaluations/<date>-baseline-vs-<candidate>.md` |
| L9 | Dashboard, usage report, evidence export, quota finding (D6), setup and troubleshooting guide, handover | M | L5 | Guide, report and sanitised evidence committed |

## 6. Completion evidence

| Evidence | Produced by |
|---|---|
| Sample traces: a successful question, a missing-data answer, a tool timeout | Kanthararom question, golden case 3 or 6, golden case 11 |
| Telemetry failure | Dead `LANGFUSE_HOST`: answer returned, warning and counter recorded |
| Dashboard and usage report | L9 |
| Evaluation dataset | `tests/golden/qa/thailand_hub_v1.yaml` and the Langfuse dataset |
| Comparison | L8 report |
| Durable copies | `docs/evaluations/evidence/<date>/`, sanitised (section 4.8) |
| Guide, with the ingestion API, payload format and plan limits | `docs/guides/langfuse-setup-and-troubleshooting.md` |

## 7. Risks

- **Reviewer not confirmed (D4).** Implementation can finish, but AC5 cannot be signed off.
- **Price drift.** Cost is calculated at ingestion, so `models.json` carries the price date.
- **Development workload.** The 1,000-question projection describes development traffic, not
  real planners, and the report says so.
- **Free-plan rate limits.** The Metrics API allows 100 requests a day, so the report script
  makes a few grouped queries per run. Ingestion limits are shared across the per-environment
  projects.
