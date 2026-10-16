"""Create or update the plain-language GRP AI overview in Langfuse Evaluation.

The script reads ignored local Langfuse credentials, never prints them, and manages only the
named dashboard and its prefixed widgets.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_NAME = "GRP AI at a glance"
ENVIRONMENT = "development"


def _load_ignored_env(path: Path = ROOT / ".env") -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        if value and not os.getenv(key.strip()):
            os.environ[key.strip()] = value


def _configuration() -> tuple[str, tuple[str, str]]:
    _load_ignored_env()
    host = os.getenv("LANGFUSE_HOST") or os.getenv("LANGFUSE_BASE_URL")
    required = {
        "Langfuse host": host,
        "LANGFUSE_PUBLIC_KEY": os.getenv("LANGFUSE_PUBLIC_KEY"),
        "LANGFUSE_SECRET_KEY": os.getenv("LANGFUSE_SECRET_KEY"),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise SystemExit(f"Missing local configuration: {', '.join(missing)}")
    return str(host).rstrip("/"), (
        str(required["LANGFUSE_PUBLIC_KEY"]),
        str(required["LANGFUSE_SECRET_KEY"]),
    )


def _environment_filter() -> list[dict[str, str]]:
    return [
        {
            "type": "string",
            "column": "environment",
            "operator": "=",
            "value": ENVIRONMENT,
        }
    ]


def _widget_specs() -> list[tuple[dict[str, Any], dict[str, int]]]:
    filters = _environment_filter()
    return [
        (
            {
                "name": "GRP overview · AI requests",
                "description": "How many GRP AI operations were recorded in development.",
                "view": "observations",
                "chartType": "NUMBER",
                "metrics": [{"measure": "count", "agg": "count"}],
                "dimensions": [],
                "filters": filters,
            },
            {"x": 0, "y": 0, "width": 4, "height": 4},
        ),
        (
            {
                "name": "GRP overview · Estimated cost",
                "description": (
                    "Estimated provider cost. A blank value means model pricing is not configured."
                ),
                "view": "observations",
                "chartType": "NUMBER",
                "metrics": [{"measure": "totalCost", "agg": "sum"}],
                "dimensions": [],
                "filters": filters,
            },
            {"x": 4, "y": 0, "width": 4, "height": 4},
        ),
        (
            {
                "name": "GRP overview · Average response time",
                "description": "Average time used by a recorded AI operation.",
                "view": "observations",
                "chartType": "NUMBER",
                "metrics": [{"measure": "latency", "agg": "avg"}],
                "dimensions": [],
                "filters": filters,
            },
            {"x": 8, "y": 0, "width": 4, "height": 4},
        ),
        (
            {
                "name": "GRP overview · Requests by model",
                "description": "Which AI models handled the recorded requests.",
                "view": "observations",
                "chartType": "VERTICAL_BAR",
                "metrics": [{"measure": "count", "agg": "count"}],
                "dimensions": [{"field": "providedModelName"}],
                "filters": filters,
            },
            {"x": 0, "y": 4, "width": 6, "height": 5},
        ),
        (
            {
                "name": "GRP overview · Estimated cost by model",
                "description": (
                    "Estimated cost grouped by model; depends on Langfuse recognizing its pricing."
                ),
                "view": "observations",
                "chartType": "VERTICAL_BAR",
                "metrics": [{"measure": "totalCost", "agg": "sum"}],
                "dimensions": [{"field": "providedModelName"}],
                "filters": filters,
            },
            {"x": 6, "y": 4, "width": 6, "height": 5},
        ),
        (
            {
                "name": "GRP overview · Requests by workflow",
                "description": (
                    "The GRP workflow that made each call, such as the Platform AI test."
                ),
                "view": "observations",
                "chartType": "HORIZONTAL_BAR",
                "metrics": [{"measure": "count", "agg": "count"}],
                "dimensions": [{"field": "name"}],
                "filters": filters,
            },
            {"x": 0, "y": 9, "width": 6, "height": 5},
        ),
        (
            {
                "name": "GRP overview · Slow-call indicator",
                "description": (
                    "95% of recorded operations finish at or below this duration. Lower is better."
                ),
                "view": "observations",
                "chartType": "HORIZONTAL_BAR",
                "metrics": [{"measure": "latency", "agg": "p95"}],
                "dimensions": [{"field": "name"}],
                "filters": filters,
            },
            {"x": 6, "y": 9, "width": 6, "height": 5},
        ),
    ]


def synchronize() -> str:
    host, auth = _configuration()
    with httpx.Client(base_url=host, auth=auth, timeout=30) as client:
        response = client.get("/api/public/unstable/dashboards", params={"limit": 50})
        response.raise_for_status()
        dashboard = next(
            (row for row in response.json()["data"] if row["name"] == DASHBOARD_NAME), None
        )
        dashboard_body = {
            "name": DASHBOARD_NAME,
            "description": (
                "Plain-language development overview: request volume, models, estimated cost and "
                "response time. GRP's database remains the official allowance record. Prompts and "
                "answers are intentionally not exported. Blank cost means pricing is unavailable, "
                "not that usage was free."
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

        response = client.get("/api/public/unstable/dashboard-widgets", params={"limit": 100})
        response.raise_for_status()
        existing_widgets = {row["name"]: row for row in response.json()["data"]}
        response = client.get(f"/api/public/unstable/dashboards/{dashboard['id']}")
        response.raise_for_status()
        placed = {item.get("widgetId") for item in response.json()["definition"]["widgets"]}

        for widget_body, layout in _widget_specs():
            widget = existing_widgets.get(widget_body["name"])
            if widget:
                response = client.patch(
                    f"/api/public/unstable/dashboard-widgets/{widget['id']}", json=widget_body
                )
            else:
                response = client.post(
                    "/api/public/unstable/dashboard-widgets", json=widget_body
                )
            response.raise_for_status()
            widget = response.json()
            if widget["id"] not in placed:
                response = client.post(
                    f"/api/public/unstable/dashboards/{dashboard['id']}/placements",
                    json={"type": "widget", "widgetId": widget["id"], **layout},
                )
                response.raise_for_status()
    return str(dashboard["id"])


if __name__ == "__main__":
    dashboard_id = synchronize()
    print(f"Synchronized {DASHBOARD_NAME} ({dashboard_id})")
