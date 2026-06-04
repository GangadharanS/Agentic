"""Thin accessor for the remote GitHub MCP server (Option C).

Reuses ReAct's Streamable HTTP client (``mcp_bridge.MCPClient`` ->
``StreamableMCPClient``). Point ``MCP_SERVER_URL`` at the GitHub-hosted remote
MCP endpoint:

    MCP_SERVER_URL=https://api.githubcopilot.com/mcp/

The client forwards ``GITHUB_TOKEN`` as a Bearer header automatically.
"""
from __future__ import annotations

import os

import _react_path  # noqa: F401  -- side effect: adds ../ReAct to sys.path

from mcp_bridge import MCPClient  # type: ignore


def get_mcp_client():
    """Return an MCP client bound to MCP_SERVER_URL (remote GitHub MCP by default)."""
    return MCPClient(server_url=os.getenv("MCP_SERVER_URL"))


def mcp_server_url() -> str:
    return os.getenv("MCP_SERVER_URL", "https://api.githubcopilot.com/mcp/")
