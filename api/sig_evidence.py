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


@dataclass(frozen=True)
class EmbedCheck:
    url: str | None
    displayed_layer: str | None
    layer_kind: str | None
    verified: bool
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
            False, requested_place, sig_place, None, "Global Risk did not report the area used"
        )
    match = AOI_PATTERN.match(aoi_line)
    aoi_name = match.group("name") if match else ""
    if "via admin boundary" not in aoi_line:
        return AreaCheck(
            False,
            requested_place,
            sig_place,
            aoi_line,
            "Global Risk did not find an admin boundary for this place and used an approximate "
            "area",
        )
    names = {_normalize(aoi_name), _normalize(sig_place or "")} - {""}
    if not requested_head or requested_head not in names:
        return AreaCheck(
            False,
            requested_place,
            sig_place,
            aoi_line,
            "Global Risk analysed a different place from the one requested",
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


DISPLAYED_LAYER_KEYS = frozenset(
    {
        "display_layer",
        "displayed_layer",
        "layer",
        "layer_id",
        "map_layer",
        "render_layer",
        "rendered_layer",
    }
)
FLOOD_HAZARD_LAYER = re.compile(r"^(?:hazard_flood|flood_rp(?:10|20|50|100|200|500))(?:\.tif)?$")
FLOOD_RISK_LAYER = re.compile(
    r"^(?:risk_flood_l2|risk_l2|flood_risk_l2|layer_2_risk)(?:\.tif)?$"
)


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [item for child in value.values() for item in _strings(child)]
    if isinstance(value, list):
        return [item for child in value for item in _strings(child)]
    return []


def _displayed_layers(value: object) -> list[str]:
    layers: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            normalized_key = re.sub(r"[^a-z0-9]+", "_", str(key).casefold()).strip("_")
            if normalized_key in DISPLAYED_LAYER_KEYS:
                layers.extend(item for item in _strings(child) if not item.startswith("http"))
            layers.extend(_displayed_layers(child))
    elif isinstance(value, list):
        for child in value:
            layers.extend(_displayed_layers(child))
    return list(dict.fromkeys(layer.strip() for layer in layers if layer.strip()))


def verified_hazard_embed(
    result: McpToolResult, allowed_host: str | None, *, allow_risk: bool = False
) -> EmbedCheck:
    """Accept an embed only when SIG explicitly identifies the displayed hazard layer.

    SIG changed the meaning of the map's ``severity`` field from water-depth class to
    vulnerability-weighted risk without changing the field name (G-17). A valid URL alone is
    therefore insufficient: MVP 1 fails closed unless the embed response declares one supported
    flood-hazard layer. Risk layers remain hidden until the science owner signs the recipe (G-16).
    """

    url = embed_url(result, allowed_host)
    if url is None:
        return EmbedCheck(
            None, None, None, False, "Global Risk did not return an allowed hazard-map URL."
        )
    layers = _displayed_layers(result.structured_content)
    if not layers:
        return EmbedCheck(
            None,
            None,
            None,
            False,
            "Global Risk did not identify the layer displayed by the embedded map.",
        )
    normalized = [layer.casefold().strip() for layer in layers]
    risk_layers = [layer for layer in normalized if FLOOD_RISK_LAYER.fullmatch(layer)]
    if risk_layers:
        displayed = layers[normalized.index(risk_layers[0])]
        if allow_risk and len(risk_layers) == 1 and len(normalized) == 1:
            return EmbedCheck(
                url,
                displayed,
                "risk",
                True,
                "Displayed Global Risk vulnerability-weighted flood-risk layer verified.",
            )
        return EmbedCheck(
            None,
            displayed,
            "risk",
            False,
            "Global Risk returned a vulnerability-weighted risk map; MVP 1 shows flood hazard "
            "only.",
        )
    hazard_layers = [layer for layer in normalized if FLOOD_HAZARD_LAYER.fullmatch(layer)]
    if len(hazard_layers) != 1 or len(normalized) != 1:
        return EmbedCheck(
            None,
            ", ".join(layers),
            None,
            False,
            "Global Risk did not return one recognized flood-hazard layer for the embedded map.",
        )
    return EmbedCheck(url, layers[0], "hazard", True, "Displayed flood-hazard layer verified.")
