"""MCP client bridge for ReAct.

Default: Streamable HTTP (github-mcp-server v1+, api.githubcopilot.com).
Fallback: legacy SSE transport (custom mcp_client_app) when MCP_TRANSPORT=sse.
"""
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

# Legacy SSE client (custom_mcp_tools / mcp_client_app)
if str(_ROOT / "mcp_client_app") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mcp_client_app"))

from streamable_mcp_client import StreamableMCPClient  # noqa: E402

_LEGACY = None
if os.getenv("MCP_TRANSPORT", "streamable").lower() == "sse":
    from mcp_client import MCPClient as _LegacyMCPClient  # noqa: E402

    _LEGACY = _LegacyMCPClient


def MCPClient(server_url: str | None = None, auth_token: str | None = None):
    """Factory — returns the appropriate MCP client for the configured transport."""
    if _LEGACY is not None:
        return _LEGACY(server_url=server_url)
    return StreamableMCPClient(server_url=server_url, auth_token=auth_token)


# Singleton for modules that import mcp_client directly.
mcp_client = MCPClient()
