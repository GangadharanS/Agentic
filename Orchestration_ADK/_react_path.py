"""Inject ../ReAct on sys.path so we can reuse its MCP client + PRReviewAgent.

The ADK orchestrator reuses two proven pieces from the ReAct project:
  - streamable_mcp_client / mcp_bridge.MCPClient  (remote GitHub MCP transport)
  - pr_reviewer.PRReviewAgent                     (the ReAct review loop)
"""
import sys
from pathlib import Path

_REACT = Path(__file__).resolve().parent.parent / "ReAct"
if str(_REACT) not in sys.path:
    sys.path.insert(0, str(_REACT))
