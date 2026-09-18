"""Checks on SIG generic Risk pack results before a Planner sees them (ADR-0004).

SIG's live runs showed that some place names silently fall back to a ~12 km box
instead of the admin boundary. GRP stops safely (AD-10) unless the pack states it used
an admin boundary for the place the Planner asked about.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from api.mcp_client import McpToolResult, SigMcpError

AOI_PATTERN = re.compile(r"^aoi\[(?P<name>[^\]]+)\]\s*(?P<detail>.*)$")
HAZARD_MAP_PATH = re.compile(r"^/embed/hazard_map/[^/]+/?$")


@dataclass(frozen=True)
class AreaCheck:
    verified: bool
    requested: str
    sig_place: str | None
    sig_area: str | None
    reason: str


def tool_payload(result: McpToolResult) -> dict[str, Any]:
    if result.structured_content:
        return result.structured_content
    for item in result.content:
        if item.get("type") != "text":
            continue
        try:
            value = json.loads(str(item.get("text", "")))
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        if isinstance(value, dict):
            return value
    raise SigMcpError("SIG MCP returned no structured evidence")


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def check_area(requested_place: str, pack: dict[str, Any]) -> AreaCheck:
    """Accept only an admin-boundary AOI whose name is the first part of the requested place."""

    stats = pack.get("stats") if isinstance(pack.get("stats"), dict) else {}
    sig_place = str(stats.get("place")) if stats.get("place") else None
    aoi_line = next(
        (
            str(line)
            for line in pack.get("trace", [])
            if isinstance(line, str) and line.startswith("aoi[")
        ),
        None,
    )
    requested_head = _normalize(requested_place.split(",")[0])
    if aoi_line is None:
        return AreaCheck(
            False, requested_place, sig_place, None, "SIG did not report the area used"
        )
    match = AOI_PATTERN.match(aoi_line)
    aoi_name = match.group("name") if match else ""
    if "via admin boundary" not in aoi_line:
        return AreaCheck(
            False,
            requested_place,
            sig_place,
            aoi_line,
            "SIG did not find an admin boundary for this place and used an approximate area",
        )
    names = {_normalize(aoi_name), _normalize(sig_place or "")} - {""}
    if not requested_head or requested_head not in names:
        return AreaCheck(
            False,
            requested_place,
            sig_place,
            aoi_line,
            "SIG analysed a different place from the one requested",
        )
    return AreaCheck(True, requested_place, sig_place, aoi_line, "Admin boundary matched")


def embed_url(result: McpToolResult, allowed_host: str | None) -> str | None:
    """Return the receipt-bound hazard-map URL from a SIG ``ui_embed`` result.

    The MCP result can contain prose and arbitrary links.  Treat it as untrusted and
    accept only the documented HTTPS component path on the configured SIG host.
    """

    candidates: list[str] = []

    def visit(value: object) -> None:
        if isinstance(value, dict):
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
        elif isinstance(value, str):
            candidates.extend(re.findall(r"https://[^\s\"'<>]+", value))

    visit(result.structured_content)
    visit(result.content)
    for candidate in candidates:
        parsed = urlparse(candidate.replace("&amp;", "&"))
        if (
            parsed.scheme == "https"
            and parsed.hostname == allowed_host
            and parsed.username is None
            and parsed.password is None
            and HAZARD_MAP_PATH.fullmatch(parsed.path)
        ):
            return parsed.geturl()
    return None
