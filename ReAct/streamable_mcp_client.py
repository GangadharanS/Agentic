"""MCP client for GitHub's Streamable HTTP transport (github-mcp-server v1+).

Protocol: POST JSON-RPC to /mcp, session tracked via Mcp-Session-Id header.
Responses may be JSON or SSE-framed (event: message / data: {...}).
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Optional

import aiohttp
from dotenv import load_dotenv

load_dotenv()


def _auth_token() -> str:
    explicit = (os.getenv("MCP_AUTH_TOKEN") or os.getenv("MCP_BEARER_TOKEN") or "").strip()
    if explicit:
        return explicit
    if os.getenv("MCP_AUTH_WITH_GITHUB_TOKEN", "true").lower() in ("1", "true", "yes"):
        return (os.getenv("GITHUB_TOKEN") or "").strip()
    return ""


def mcp_endpoint(server_url: str) -> str:
    """Resolve the Streamable HTTP endpoint from MCP_SERVER_URL."""
    url = (server_url or "").rstrip("/")
    if "githubcopilot.com" in url or url.endswith("/mcp"):
        return url + "/" if not url.endswith("/") else url
    return f"{url}/mcp"


def _parse_sse_body(text: str) -> list[dict]:
    """Extract JSON objects from SSE-framed or plain JSON response bodies."""
    if not text or not text.strip():
        return []
    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            return [json.loads(stripped)]
        except json.JSONDecodeError:
            pass

    payloads: list[dict] = []
    for block in re.split(r"\n\n+", stripped):
        data_line = None
        for line in block.splitlines():
            if line.startswith("data:"):
                data_line = line[5:].strip()
        if data_line:
            try:
                payloads.append(json.loads(data_line))
            except json.JSONDecodeError:
                continue
    return payloads


class StreamableMCPClient:
    """Client for github-mcp-server Streamable HTTP transport."""

    def __init__(self, server_url: str | None = None, auth_token: str | None = None):
        self.server_url = server_url or os.getenv("MCP_SERVER_URL", "http://localhost:8000")
        self.endpoint = mcp_endpoint(self.server_url)
        self.auth_token = auth_token if auth_token is not None else _auth_token()
        self.tools: list = []
        self.request_id = 0
        self._session_id: Optional[str] = None

    def _next_id(self) -> str:
        self.request_id += 1
        return f"req-{self.request_id}"

    def _headers(self, *, json_body: bool = True) -> dict[str, str]:
        headers: dict[str, str] = {
            "Accept": "application/json, text/event-stream",
        }
        if json_body:
            headers["Content-Type"] = "application/json"
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    async def _post(self, body: dict, *, expect_response: bool = True) -> tuple[int, str, dict]:
        timeout = aiohttp.ClientTimeout(total=120)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                self.endpoint,
                json=body,
                headers=self._headers(),
            ) as response:
                text = await response.text()
                hdrs = dict(response.headers)
                if "Mcp-Session-Id" in hdrs:
                    self._session_id = hdrs["Mcp-Session-Id"]
                if not expect_response:
                    return response.status, text, hdrs
                return response.status, text, hdrs

    async def _ensure_session(self) -> None:
        if self._session_id:
            return

        init_id = self._next_id()
        status, text, _ = await self._post(
            {
                "jsonrpc": "2.0",
                "id": init_id,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "clientInfo": {"name": "react-pr-ui", "version": "1.0.0"},
                },
            }
        )
        if status not in (200, 202):
            raise RuntimeError(f"MCP initialize failed ({status}): {text[:300]}")

        payloads = _parse_sse_body(text)
        init_ok = any(p.get("id") == init_id and "result" in p for p in payloads)
        if not init_ok and status == 200 and not self._session_id:
            raise RuntimeError(f"MCP initialize returned no result: {text[:300]}")

        await self._post({"jsonrpc": "2.0", "method": "notifications/initialized"}, expect_response=False)

    async def _call(self, method: str, params: dict) -> dict:
        await self._ensure_session()
        req_id = self._next_id()
        status, text, _ = await self._post(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": method,
                "params": params,
            }
        )
        if status not in (200, 202):
            return {"success": False, "error": f"HTTP {status}: {text[:500]}"}

        for payload in _parse_sse_body(text):
            if payload.get("id") != req_id:
                continue
            if "error" in payload:
                return {"success": False, "error": str(payload["error"])}
            if "result" in payload:
                return {"success": True, "data": payload["result"]}

        return {"success": False, "error": f"No response for {method}: {text[:500]}"}

    async def discover_tools(self) -> list:
        try:
            result = await self._call("tools/list", {})
            if result.get("success") and isinstance(result.get("data"), dict):
                self.tools = result["data"].get("tools", [])
                print(f"[MCP] Discovered {len(self.tools)} tools")
            return self.tools
        except Exception as exc:
            print(f"Error discovering tools: {exc}")
            return self.tools

    async def call_tool(self, tool_name: str, arguments: dict) -> dict:
        return await self._call(
            "tools/call",
            {"name": tool_name, "arguments": arguments},
        )

    async def health_check(self) -> bool:
        try:
            timeout = aiohttp.ClientTimeout(total=5)
            headers = self._headers(json_body=False)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                # Any HTTP response (even 401/405) means the server is reachable.
                async with session.get(self.endpoint, headers=headers) as response:
                    return response.status < 500
        except Exception:
            return False

    def get_tools_for_gemini(self) -> list:
        gemini_tools = []
        for tool in self.tools:
            parameters: dict[str, Any] = {
                "type": "object",
                "properties": {},
                "required": [],
            }
            schema = tool.get("inputSchema") or {}
            if "properties" in schema:
                parameters["properties"] = schema["properties"]
            if "required" in schema:
                parameters["required"] = schema["required"]
            gemini_tools.append(
                {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": parameters,
                }
            )
        return gemini_tools
