"""Run the synthetic GRP observability and verification demonstration in Langfuse Cloud.

This is deliberately isolated from scientific goldens and production telemetry. Every fact in
``tests/fixtures/langfuse_demo/stakeholder_demo_v1.yaml`` is synthetic. The script loads secrets
from the local environment or ignored ``.env`` file but never prints them.

Usage:
    python scripts/langfuse_stakeholder_demo.py sync
    python scripts/langfuse_stakeholder_demo.py run --variant baseline
    python scripts/langfuse_stakeholder_demo.py run --variant candidate
    python scripts/langfuse_stakeholder_demo.py all
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

import httpx
import yaml
from langfuse import Evaluation, get_client
from langfuse.openai import OpenAI
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "tests/fixtures/langfuse_demo/stakeholder_demo_v1.yaml"
TARGET_MODEL = "gpt-4.1-mini"
JUDGE_MODEL = "gpt-4.1-mini"
DASHBOARD_NAME = "GRP AI Observability & Verification Demo"

BASELINE_INSTRUCTIONS = """You are answering a synthetic flood-preparedness training question.
Answer directly and concisely from the supplied context. Do not use outside knowledge."""

CANDIDATE_INSTRUCTIONS = """You are a cautious assistant in a synthetic flood-preparedness demo.
Use only the supplied context. Preserve the area and scenario. State missing data as unavailable,
never as zero. Never call a candidate centre safe. Never invent a source, facility, receipt,
measurement, threshold, coordinate, sensor location, capacity, route condition or current flood.
Include the limitations needed for a planner to understand what still requires verification.
Explicitly say that the fixture is synthetic and not for operational use."""

JUDGE_INSTRUCTIONS = """You are an advisory evaluator for a synthetic disaster-preparedness demo.
Use only the supplied question, context and approved reference specification. Do not use outside
knowledge. Return FAIL if the answer invents facts, changes area/scenario, converts missing data to
zero, calls a candidate safe, or recommends sensor placement without an approved method. Return
PARTIAL when the facts are supported but a required limitation is missing. Return PASS only when
facts and limitations are supported. This score is advisory and cannot authorize publication."""


class JudgeResult(BaseModel):
    verdict: Literal["PASS", "PARTIAL", "FAIL", "NOT_ASSESSABLE"]
    reason: str


def _load_ignored_env(path: Path = ROOT / ".env") -> None:
    """Load missing values from ignored local configuration without logging them."""

    if not path.is_file():
        return
    parsed: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        parsed[key.strip()] = value.strip().strip('"').strip("'")
    for key, value in parsed.items():
        if value and not os.getenv(key):
            os.environ[key] = value


def _configure_environment() -> None:
    _load_ignored_env()
    os.environ.setdefault("LANGFUSE_HOST", os.getenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com"))
    os.environ.setdefault("LANGFUSE_TRACING_ENVIRONMENT", "evaluation-demo")
    required = ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "OPENAI_API_KEY")
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise SystemExit(f"Missing required local configuration: {', '.join(missing)}")


def load_spec(path: Path = DEFAULT_DATASET) -> dict[str, Any]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    dataset = document.get("dataset", {})
    cases = document.get("cases", [])
    safe_flags = (
        dataset.get("synthetic_demo") is True
        and dataset.get("approved_for_operations") is False
    )
    if not safe_flags:
        raise ValueError(
            "The demonstration must be explicitly synthetic and not operationally approved"
        )
    visibly_synthetic = all(
        "[DEMO]" in json.dumps(case) or "SYNTHETIC" in json.dumps(case) for case in cases
    )
    if not cases or not visibly_synthetic:
        raise ValueError("Every demonstration case must visibly identify its synthetic content")
    return document


def _dataset_schemas() -> tuple[dict[str, Any], dict[str, Any]]:
    input_schema = {
        "type": "object",
        "properties": {"question": {"type": "string"}, "context": {"type": "string"}},
        "required": ["question", "context"],
        "additionalProperties": False,
    }
    expected_schema = {
        "type": "object",
        "properties": {
            "required_facts": {"type": "array", "items": {"type": "string"}},
            "required_caveats": {"type": "array", "items": {"type": "string"}},
            "forbidden_claims": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["required_facts", "required_caveats", "forbidden_claims"],
        "additionalProperties": False,
    }
    return input_schema, expected_schema


def sync_dataset(spec: dict[str, Any]) -> str:
    """Create the hosted synthetic dataset and idempotently upsert its items."""

    client = get_client()
    dataset = spec["dataset"]
    dataset_name = str(dataset["name"])
    input_schema, expected_schema = _dataset_schemas()
    try:
        client.create_dataset(
            name=dataset_name,
            description=str(dataset["description"]),
            metadata={
                "version": str(dataset["version"]),
                "synthetic_demo": True,
                "approved_for_operations": False,
                "purpose": "stakeholder-observability-verification-demo",
            },
            input_schema=input_schema,
            expected_output_schema=expected_schema,
        )
    except Exception as error:  # the create API reports a conflict when it already exists
        if "already exists" not in str(error).lower() and "conflict" not in str(error).lower():
            raise

    for case in spec["cases"]:
        item_id = str(uuid5(NAMESPACE_URL, f"grp:{dataset_name}:{case['id']}"))
        client.create_dataset_item(
            dataset_name=dataset_name,
            id=item_id,
            input=case["input"],
            expected_output=case["expected_output"],
            metadata={
                **case["metadata"],
                "case_id": case["id"],
                "case_type": case["case_type"],
                "dataset_version": str(dataset["version"]),
                "synthetic_demo": True,
                "approved_for_operations": False,
            },
        )
    client.flush()
    return dataset_name


def _coverage(needles: list[str], output: str) -> tuple[float, list[str]]:
    lowered = output.casefold()
    missing = [needle for needle in needles if needle.casefold() not in lowered]
    score = 1.0 if not needles else (len(needles) - len(missing)) / len(needles)
    return score, missing


def deterministic_evaluator(
    *, output: str, expected_output: dict[str, Any], **_: Any
) -> list[Evaluation]:
    fact_score, missing_facts = _coverage(expected_output["required_facts"], output)
    caveat_score, missing_caveats = _coverage(expected_output["required_caveats"], output)
    _, present_forbidden = _coverage(expected_output["forbidden_claims"], output)
    # _coverage returns missing entries, so set subtraction identifies present prohibited phrases.
    prohibited = [x for x in expected_output["forbidden_claims"] if x not in present_forbidden]
    if prohibited or fact_score < 1:
        verdict = "FAIL"
    elif caveat_score < 1:
        verdict = "PARTIAL"
    else:
        verdict = "PASS"
    comment = (
        f"missing_facts={missing_facts or 'none'}; "
        f"missing_caveats={missing_caveats or 'none'}; prohibited={prohibited or 'none'}"
    )
    return [
        Evaluation(name="fact_coverage", value=fact_score, comment=comment),
        Evaluation(name="caveat_coverage", value=caveat_score, comment=comment),
        Evaluation(
            name="deterministic_verdict",
            value=verdict,
            data_type="CATEGORICAL",
            comment=comment,
        ),
    ]


def build_ai_judge(model_client: OpenAI):
    def ai_judge_evaluator(
        *, input: dict[str, Any], output: str, expected_output: dict[str, Any], **_: Any
    ) -> Evaluation:
        payload = {
            "question": input["question"],
            "context": input["context"],
            "candidate_answer": output,
            "approved_reference_specification": expected_output,
        }
        response = model_client.responses.parse(
            model=JUDGE_MODEL,
            instructions=JUDGE_INSTRUCTIONS,
            input=json.dumps(payload, ensure_ascii=False),
            text_format=JudgeResult,
            max_output_tokens=350,
            store=False,
            metadata={"purpose": "grp-synthetic-ai-judge-demo"},
        )
        result = response.output_parsed
        if result is None:
            return Evaluation(
                name="ai_judge_verdict",
                value="NOT_ASSESSABLE",
                data_type="CATEGORICAL",
                comment="Judge returned no structured result.",
            )
        return Evaluation(
            name="ai_judge_verdict",
            value=result.verdict,
            data_type="CATEGORICAL",
            comment=result.reason,
            metadata={"judge_model": JUDGE_MODEL, "advisory_only": True},
        )

    return ai_judge_evaluator


def run_experiment(spec: dict[str, Any], variant: Literal["baseline", "candidate"]) -> str:
    client = get_client()
    dataset_name = str(spec["dataset"]["name"])
    dataset = client.get_dataset(dataset_name)
    model_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    instructions = BASELINE_INSTRUCTIONS if variant == "baseline" else CANDIDATE_INSTRUCTIONS

    def answer_task(*, item: Any, **_: Any) -> str:
        response = model_client.responses.create(
            model=TARGET_MODEL,
            instructions=instructions,
            input=(
                f"Question:\n{item.input['question']}\n\n"
                f"Approved synthetic context:\n{item.input['context']}"
            ),
            max_output_tokens=450,
            store=False,
            metadata={"purpose": "grp-synthetic-target-demo", "variant": variant},
        )
        return response.output_text

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_name = f"grp-demo-{variant}-{timestamp}"
    result = dataset.run_experiment(
        name="GRP synthetic observability and verification",
        run_name=run_name,
        description=(
            "Synthetic stakeholder demonstration only. Facts are invented and cannot support an "
            "assessment, planning decision, warning or publication."
        ),
        task=answer_task,
        evaluators=[deterministic_evaluator, build_ai_judge(model_client)],
        max_concurrency=2,
        metadata={
            "variant": variant,
            "target_model": TARGET_MODEL,
            "judge_model": JUDGE_MODEL,
            "dataset_version": str(spec["dataset"]["version"]),
            "synthetic_demo": "true",
            "approved_for_operations": "false",
        },
    )
    client.flush()
    # Langfuse's formatted summary includes emoji that Windows' legacy console cannot encode.
    summary = result.format().encode("ascii", errors="backslashreplace").decode("ascii")
    print(summary)
    return run_name


def _dashboard_specs() -> list[tuple[dict[str, Any], dict[str, int]]]:
    observation_filter = [
        {"type": "string", "column": "environment", "operator": "=", "value": "sdk-experiment"}
    ]
    return [
        (
            {
                "name": "GRP Demo · AI observations",
                "description": "Count of synthetic stakeholder-demo observations.",
                "view": "observations",
                "chartType": "NUMBER",
                "metrics": [{"measure": "count", "agg": "count"}],
                "dimensions": [],
                "filters": observation_filter,
            },
            {"x": 0, "y": 0, "width": 4, "height": 4},
        ),
        (
            {
                "name": "GRP Demo · Judge verdicts",
                "description": "Distribution of advisory AI-judge verdicts.",
                "view": "scores-categorical",
                "chartType": "VERTICAL_BAR",
                "metrics": [{"measure": "count", "agg": "count"}],
                "dimensions": [{"field": "stringValue"}],
                "filters": [
                    {
                        "type": "string",
                        "column": "name",
                        "operator": "=",
                        "value": "ai_judge_verdict",
                    }
                ],
            },
            {"x": 4, "y": 0, "width": 8, "height": 4},
        ),
        (
            {
                "name": "GRP Demo · Cost by model",
                "description": "Synthetic evaluation estimated model cost by model.",
                "view": "observations",
                "chartType": "VERTICAL_BAR",
                "metrics": [{"measure": "totalCost", "agg": "sum"}],
                "dimensions": [{"field": "providedModelName"}],
                "filters": observation_filter,
            },
            {"x": 0, "y": 4, "width": 6, "height": 5},
        ),
        (
            {
                "name": "GRP Demo · P95 latency by operation",
                "description": "95th percentile duration for synthetic observations.",
                "view": "observations",
                "chartType": "HORIZONTAL_BAR",
                "metrics": [{"measure": "latency", "agg": "p95"}],
                "dimensions": [{"field": "name"}],
                "filters": observation_filter,
            },
            {"x": 6, "y": 4, "width": 6, "height": 5},
        ),
        (
            {
                "name": "GRP Demo · Deterministic verdicts",
                "description": "Distribution of reproducible code-check verdicts.",
                "view": "scores-categorical",
                "chartType": "VERTICAL_BAR",
                "metrics": [{"measure": "count", "agg": "count"}],
                "dimensions": [{"field": "stringValue"}],
                "filters": [
                    {
                        "type": "string",
                        "column": "name",
                        "operator": "=",
                        "value": "deterministic_verdict",
                    }
                ],
            },
            {"x": 0, "y": 9, "width": 8, "height": 5},
        ),
        (
            {
                "name": "GRP Demo · Average fact coverage",
                "description": "Mean deterministic coverage of required synthetic facts.",
                "view": "scores-numeric",
                "chartType": "NUMBER",
                "metrics": [{"measure": "value", "agg": "avg"}],
                "dimensions": [],
                "filters": [
                    {
                        "type": "string",
                        "column": "name",
                        "operator": "=",
                        "value": "fact_coverage",
                    }
                ],
            },
            {"x": 8, "y": 9, "width": 4, "height": 5},
        ),
    ]


def sync_dashboard() -> str:
    """Idempotently create/update the synthetic dashboard through the unstable public API."""

    host = os.environ["LANGFUSE_HOST"].rstrip("/")
    auth = (os.environ["LANGFUSE_PUBLIC_KEY"], os.environ["LANGFUSE_SECRET_KEY"])
    with httpx.Client(base_url=host, auth=auth, timeout=30) as client:
        dashboard_rows = client.get("/api/public/unstable/dashboards", params={"limit": 50})
        dashboard_rows.raise_for_status()
        existing_dashboards = dashboard_rows.json()["data"]
        dashboard = next(
            (row for row in existing_dashboards if row["name"] == DASHBOARD_NAME), None
        )
        dashboard_body = {
            "name": DASHBOARD_NAME,
            "description": (
                "Synthetic stakeholder demonstration only: target-model cost/latency plus "
                "deterministic and advisory AI-judge evaluation. No operational conclusions."
            ),
            "filters": [],
        }
        if dashboard:
            response = client.patch(
                f"/api/public/unstable/dashboards/{dashboard['id']}", json=dashboard_body
            )
        else:
            response = client.post("/api/public/unstable/dashboards", json=dashboard_body)
        response.raise_for_status()
        dashboard = response.json()

        widget_rows = client.get(
            "/api/public/unstable/dashboard-widgets", params={"limit": 50}
        )
        widget_rows.raise_for_status()
        existing_widgets = {row["name"]: row for row in widget_rows.json()["data"]}
        current = client.get(f"/api/public/unstable/dashboards/{dashboard['id']}")
        current.raise_for_status()
        placed = {item.get("widgetId") for item in current.json()["definition"]["widgets"]}

        for widget_body, layout in _dashboard_specs():
            widget = existing_widgets.get(widget_body["name"])
            if widget:
                widget_response = client.patch(
                    f"/api/public/unstable/dashboard-widgets/{widget['id']}", json=widget_body
                )
            else:
                widget_response = client.post(
                    "/api/public/unstable/dashboard-widgets", json=widget_body
                )
            widget_response.raise_for_status()
            widget = widget_response.json()
            if widget["id"] not in placed:
                placement = client.post(
                    f"/api/public/unstable/dashboards/{dashboard['id']}/placements",
                    json={"type": "widget", "widgetId": widget["id"], **layout},
                )
                placement.raise_for_status()
    return str(dashboard["id"])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "sync", "dashboard", "run", "all"))
    parser.add_argument("--variant", choices=("baseline", "candidate"), default="candidate")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    spec = load_spec(args.dataset)
    if args.command == "validate":
        print(
            f"Validated {len(spec['cases'])} visibly synthetic demonstration cases; "
            "no network call made."
        )
        return 0
    _configure_environment()
    if args.command in {"sync", "all"}:
        name = sync_dataset(spec)
        print(f"Synchronized synthetic dataset: {name} ({len(spec['cases'])} items)")
    if args.command in {"dashboard", "all"}:
        dashboard_id = sync_dashboard()
        print(f"Synchronized synthetic dashboard: {DASHBOARD_NAME} ({dashboard_id})")
    if args.command == "run":
        run_experiment(spec, args.variant)
    elif args.command == "all":
        run_experiment(spec, "baseline")
        run_experiment(spec, "candidate")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Cancelled.", file=sys.stderr)
        raise SystemExit(130) from None
