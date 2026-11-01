"""Delegated MCP capability discovery for coastal zoning (ADR-0070)."""

import asyncio
import json

import httpx
import pytest

from api.mcp_client import SigMcpClient, SigMcpError


def test_tool_discovery_follows_bounded_cursor_pages() -> None:
    methods: list[tuple[str, dict]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        document = json.loads(request.content)
        method = document["method"]
        params = document.get("params", {})
        methods.append((method, params))
        if method == "notifications/initialized":
            return httpx.Response(202)
        if method == "initialize":
            result = {"protocolVersion": "2025-06-18", "capabilities": {}}
        elif not params:
            result = {
                "tools": [
                    {
                        "name": "assemble_pack",
                        "description": "Assemble evidence.",
                        "inputSchema": {"type": "object", "properties": {"geometry": {}}},
                    }
                ],
                "nextCursor": "page-2",
            }
        else:
            assert params == {"cursor": "page-2"}
            result = {
                "tools": [
                    {
                        "name": "publish_answer",
                        "inputSchema": {"type": "object", "required": ["pack_id"]},
                    }
                ]
            }
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": document["id"], "result": result})

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            async with SigMcpClient(
                "https://sig.example/mcp", "delegated-token", client=client
            ) as mcp:
                return await mcp.list_tools()

    tools = asyncio.run(exercise())

    assert [tool.name for tool in tools] == ["assemble_pack", "publish_answer"]
    assert tools[0].input_schema["properties"] == {"geometry": {}}
    assert methods == [
        (
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "adpc-grp", "version": "0.1.0"},
            },
        ),
        ("notifications/initialized", {}),
        ("tools/list", {}),
        ("tools/list", {"cursor": "page-2"}),
    ]


def test_tool_discovery_rejects_repeated_cursor() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        document = json.loads(request.content)
        if document["method"] == "notifications/initialized":
            return httpx.Response(202)
        result = (
            {"protocolVersion": "2025-06-18", "capabilities": {}}
            if document["method"] == "initialize"
            else {"tools": [], "nextCursor": "same"}
        )
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": document["id"], "result": result})

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            async with SigMcpClient("https://sig.example/mcp", "token", client=client) as mcp:
                await mcp.list_tools()

    with pytest.raises(SigMcpError, match="invalid tool cursor"):
        asyncio.run(exercise())
