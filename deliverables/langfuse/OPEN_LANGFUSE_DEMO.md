# How to open the GRP Langfuse demonstration

This is a synthetic training demonstration. Its invented values must not be used for real planning, assessments or warnings.

## Step 1 — Sign in

1. Open a normal web browser.
2. Go to:

   <https://cloud.langfuse.com>

3. Sign in with the Langfuse account connected to the GRP project.

## Step 2 — Open the dashboard

Copy and paste this complete address into the browser address bar:

<https://cloud.langfuse.com/project/cmtcbwi5a03ziad0cumtq90v5/dashboards/cmv516s0u05aoad0e6zlrbccb>

Dashboard name:

**GRP AI Observability & Verification Demo**

It contains six widgets:

- AI observation count
- AI-judge verdicts
- Deterministic verdicts
- Average fact coverage
- Estimated cost by model
- P95 latency by operation

If a widget is empty, change the dashboard date range so it includes **12 October 2026**.

## Step 3 — Open the candidate experiment

Copy and paste:

<https://cloud.langfuse.com/project/cmtcbwi5a03ziad0cumtq90v5/datasets/cmv51act1052cad0kgb8rfpi0/runs/8c93826e-4677-44dd-8f08-c22c206afe7b>

Run name:

`grp-demo-candidate-20261012T091318Z`

You should see six rows. Select a row to inspect:

- the synthetic question and context;
- the generated answer;
- the expected specification;
- `fact_coverage`;
- `caveat_coverage`;
- `deterministic_verdict`; and
- `ai_judge_verdict`.

## Step 4 — Open the baseline experiment

Copy and paste:

<https://cloud.langfuse.com/project/cmtcbwi5a03ziad0cumtq90v5/datasets/cmv51act1052cad0kgb8rfpi0/runs/fe17056e-e9f1-4473-8a1c-1da1c9f1f34d>

Run name:

`grp-demo-baseline-20261012T091245Z`

Use this run to compare the original short prompt with the more cautious candidate prompt.

## Step 5 — Open the dataset

Copy and paste:

<https://cloud.langfuse.com/project/cmtcbwi5a03ziad0cumtq90v5/datasets/cmv51act1052cad0kgb8rfpi0>

Dataset name:

`demo/grp-observability-verification-v1`

The six cases cover candidate evacuation centres, RP100 population, facility classifications, missing data, sensor placement and a tool timeout.

## Initial demonstration results

| Result | Baseline | Candidate |
| --- | ---: | ---: |
| AI judge | 5 pass, 1 partial | 5 pass, 1 fail |
| Deterministic check | 4 partial, 2 fail | 1 pass, 2 partial, 3 fail |
| Mean fact coverage | 0.667 | 0.750 |
| Mean caveat coverage | 0.000 | 0.472 |

These results are not an approval. They demonstrate that deterministic checks and the AI judge can disagree and therefore require human calibration.

## If you see “404” or “no access”

1. Confirm that you are signed in to Langfuse Cloud.
2. Confirm that you selected the correct Langfuse organization/project.
3. Try opening the project first:

   <https://cloud.langfuse.com/project/cmtcbwi5a03ziad0cumtq90v5>

4. If the project is still unavailable, the signed-in account may not be a member of the project associated with the configured API keys.

Do not send API keys or passwords through email, chat or screenshots.
