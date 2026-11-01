"""Pinned, sanitized live SIG contracts required by the coastal-zoning coordinator."""

import json
from pathlib import Path

FIXTURE = Path("tests/fixtures/sig/coastal_zoning_tool_schemas_20261023.json")


def test_recorded_sig_contract_accepts_polygon_geometry_and_gated_publish() -> None:
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    tools = document["tools"]

    assert set(tools) == {
        "platform_capabilities",
        "resolve_place_time",
        "assemble_pack",
        "publish_answer",
    }
    geometry = tools["assemble_pack"]["properties"]["geometry"]
    assert {choice["type"] for choice in geometry["anyOf"]} == {"object", "array", "null"}
    assert tools["publish_answer"]["required"] == ["pack_id", "draft"]
    assert document["receipt_resolution"]["persist_verdict"] is False
