# Langfuse stakeholder demonstration

## Purpose

This demonstration shows developers and stakeholders how GRP can combine:

- model-call traces, token usage, estimated cost and latency;
- a versioned evaluation dataset;
- reproducible code checks;
- an advisory AI judge;
- baseline-versus-candidate experiments; and
- explicit human approval before operational use.

It is **not** a scientific evaluation. Every place, facility, count and condition is invented.
The dataset is visibly marked `synthetic_demo=true` and `approved_for_operations=false`. Nothing
in it may support an assessment, planning decision, warning or publication.

## Implemented Cloud assets

The current ignored local credentials authenticate to one Langfuse Cloud project. On 12 October
2026, the following assets were created and verified without printing either API key:

- Dataset: `demo/grp-observability-verification-v1`, six synthetic cases.
- Dashboard: **GRP AI Observability & Verification Demo**.
- Baseline experiment: `grp-demo-baseline-20261012T091245Z`.
- Candidate experiment: `grp-demo-candidate-20261012T091318Z`.
- Target model: `gpt-4.1-mini`.
- Advisory judge model: `gpt-4.1-mini`.

Links for authorized project users:

- [Dashboard](https://cloud.langfuse.com/project/cmtcbwi5a03ziad0cumtq90v5/dashboards/cmv516s0u05aoad0e6zlrbccb)
- [Baseline run](https://cloud.langfuse.com/project/cmtcbwi5a03ziad0cumtq90v5/datasets/cmv51act1052cad0kgb8rfpi0/runs/fe17056e-e9f1-4473-8a1c-1da1c9f1f34d)
- [Candidate run](https://cloud.langfuse.com/project/cmtcbwi5a03ziad0cumtq90v5/datasets/cmv51act1052cad0kgb8rfpi0/runs/8c93826e-4677-44dd-8f08-c22c206afe7b)

The dashboard uses Langfuse's unstable dashboard/widget API, so its contract may change.
`scripts/langfuse_stakeholder_demo.py dashboard` idempotently reapplies the current definition.

## Demonstration cases

The source file is
[`tests/fixtures/langfuse_demo/stakeholder_demo_v1.yaml`](../../tests/fixtures/langfuse_demo/stakeholder_demo_v1.yaml).
It deliberately lives outside `tests/golden`: invented demonstration values are not scientific
goldens.

The six cases cover:

1. candidate evacuation centres and unsafe wording;
2. RP100 exposed-population numbers and scope;
3. school, temple and stadium classifications;
4. missing population evidence that must not become zero;
5. unsupported sensor-placement recommendations; and
6. an external-tool timeout that must not produce invented evidence.

The YAML keeps `input`, `expected_output` and `metadata` separate. The target model receives the
question and synthetic context but not the expected specification. Evaluators receive the
candidate output and expected specification after generation.

## Evaluation methods

### Deterministic checks

The local evaluator writes these Langfuse scores:

- `fact_coverage`, numeric from 0 to 1;
- `caveat_coverage`, numeric from 0 to 1; and
- `deterministic_verdict`, categorical `PASS`, `PARTIAL` or `FAIL`.

The string checks are intentionally simple for teaching purposes. Production validators need
reviewed normalization, typed facts, exact entity sets and approved tolerances.

### Advisory AI judge

The runner calls a separate structured-output model evaluation and writes
`ai_judge_verdict`: `PASS`, `PARTIAL`, `FAIL` or `NOT_ASSESSABLE`, with a reason. The judge is told
to use only supplied evidence and never authorize publication. It is an SDK evaluator executed by
the demonstration process; it does not require a Langfuse project LLM connection.

A later built-in Langfuse evaluator would require an approved project LLM connection. Keep its
rule inactive until it has been calibrated against named human labels.

### Human review

No score in this demonstration is labelled as human review. A real pilot must have reviewers label
candidate answers independently, preferably before seeing the judge result. Compare human and
judge labels using agreement, a confusion matrix, Cohen's kappa, false passes and false fails.
A safety-critical false pass blocks use of the judge as a gate.

## Initial findings

The first run is intentionally informative rather than a success claim:

| Result | Baseline | Candidate |
| --- | ---: | ---: |
| AI judge | 5 pass, 1 partial | 5 pass, 1 fail |
| Deterministic verdict | 4 partial, 2 fail | 1 pass, 2 partial, 3 fail |
| Mean fact coverage | 0.667 | 0.750 |
| Mean caveat coverage | 0.000 | 0.472 |

The candidate improved mean fact and caveat coverage, but neither evaluator supports promotion.
The code check and judge disagree substantially, and the candidate still produced failures. This
is the intended stakeholder lesson: an AI judge is useful for nuanced review but cannot replace
clear specifications, deterministic checks or human calibration. Exact phrase matching also
creates false failures and must be replaced by typed production checks.

These runs used the same model family for target and judge. A later pilot should add a cross-family
judge to investigate correlated bias, but it must not assume cross-family means correct.

## Dashboard contents

The dashboard contains six widgets:

1. AI observation count;
2. advisory judge verdict distribution;
3. estimated cost by model;
4. p95 latency by operation;
5. deterministic verdict distribution; and
6. average fact coverage.

The observation widgets filter to Langfuse SDK experiment traffic. Score widgets filter by the
specific demonstration score name. The project currently contains only this synthetic dataset;
future projects should isolate development, evaluation, staging and production with separate API
keys.

## Run it again

Install the optional dependencies:

```bash
python -m pip install -e ".[evaluation]"
```

Keep the keys in ignored local configuration. Never put them in Git or command-line arguments.
The script accepts `LANGFUSE_HOST`; if it is absent, it uses `https://cloud.langfuse.com`.

Validate locally without network or model calls:

```bash
python scripts/langfuse_stakeholder_demo.py validate
```

Synchronize the dataset and dashboard:

```bash
python scripts/langfuse_stakeholder_demo.py sync
python scripts/langfuse_stakeholder_demo.py dashboard
```

Run one variant:

```bash
python scripts/langfuse_stakeholder_demo.py run --variant baseline
python scripts/langfuse_stakeholder_demo.py run --variant candidate
```

Run the complete flow:

```bash
python scripts/langfuse_stakeholder_demo.py all
```

Each run makes paid model calls. It is bounded to six cases, two concurrent tasks, one target call
and one judge call per case. Langfuse telemetry failure does not alter the scientific GRP records;
this script must remain separate from production assessment execution.

## Next review before a real pilot

1. Confirm named business and domain reviewers.
2. Replace invented cases with reviewed questions while leaving them unapproved.
3. Pin immutable GRP evidence and source versions.
4. Replace phrase matching with typed facts and entity-set validators.
5. Collect blinded human labels across every outcome category.
6. Calibrate the judge; inspect every mismatch and false pass.
7. Obtain privacy approval before exporting any non-synthetic question or answer.
8. Decide whether to retain the SDK judge or configure a built-in Langfuse evaluator.
9. Keep any production evaluator rule inactive until explicit approval.
10. Record a release decision; never silently modify a golden expected value to pass.
