from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

MCP_PROTOCOL_VERSION = "2025-06-18"


class SigMcpError(RuntimeError):
    """A safe, detail-free SIG MCP failure."""


@dataclass(frozen=True)
class McpToolResult:
    content: list[dict[str, Any]]
    structured_content: dict[str, Any]
    is_error: bool


def _decode_response(response: httpx.Response) -> dict[str, Any]:
    content_type = response.headers.get("content-type", "").lower()
    try:
        if "text/event-stream" in content_type:
            documents = []
            for line in response.text.splitlines():
                if line.startswith("data:"):
                    documents.append(json.loads(line.removeprefix("data:").strip()))
            if not documents:
                raise ValueError("empty event stream")
            payload = documents[-1]
        else:
            payload = response.json()
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise SigMcpError("SIG MCP returned an unreadable response") from error
    if not isinstance(payload, dict):
        raise SigMcpError("SIG MCP returned an invalid response")
    if payload.get("error"):
        raise SigMcpError("SIG MCP declined the request")
    return payload


class SigMcpClient:
    def __init__(
        self,
        base_url: str,
        access_token: str,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.access_token = access_token
        self.client = client or httpx.AsyncClient(timeout=45.0, follow_redirects=False)
        self._owns_client = client is None
        self.session_id: str | None = None
        self._next_id = 1

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        return headers

    async def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        try:
            response = await self.client.post(
                self.base_url,
                headers=self._headers(),
                json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            if error.response.status_code in {401, 403}:
                raise SigMcpError("SERVIR sign-in must be renewed") from error
            raise SigMcpError("SIG MCP is unavailable") from error
        except httpx.HTTPError as error:
            raise SigMcpError("SIG MCP is unavailable") from error
        self.session_id = response.headers.get("mcp-session-id") or self.session_id
        payload = _decode_response(response)
        if payload.get("id") not in {request_id, str(request_id)}:
            raise SigMcpError("SIG MCP response did not match the request")
        result = payload.get("result")
        if not isinstance(result, dict):
            raise SigMcpError("SIG MCP returned no result")
        return result

    async def initialize(self) -> None:
        await self._request(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "adpc-grp", "version": "0.1.0"},
            },
        )
        try:
            response = await self.client.post(
                self.base_url,
                headers=self._headers(),
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise SigMcpError("SIG MCP session could not be initialized") from error

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> McpToolResult:
        result = await self._request("tools/call", {"name": name, "arguments": arguments})
        content = result.get("content", [])
        structured = result.get("structuredContent", {})
        if not isinstance(content, list) or not isinstance(structured, dict):
            raise SigMcpError("SIG MCP tool returned an invalid result")
        return McpToolResult(
            content=[item for item in content if isinstance(item, dict)],
            structured_content=structured,
            is_error=bool(result.get("isError", False)),
        )

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def __aenter__(self) -> SigMcpClient:
        await self.initialize()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()
