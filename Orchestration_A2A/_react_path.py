"""Inject ../ReAct on sys.path so we can reuse its modules (mcp_bridge, pr_reviewer)."""
import sys
from pathlib import Path

_PKG = Path(__file__).resolve().parent
_REACT = _PKG.parent / "ReAct"

# ReAct first so ``from prompts import …`` inside pr_reviewer resolves to ReAct/prompts.py.
_react = str(_REACT)
if _react not in sys.path:
    sys.path.insert(0, _react)

# This package second so ``orch_prompts``, ``state``, etc. stay local.
_pkg = str(_PKG)
if _pkg not in sys.path:
    sys.path.insert(1, _pkg)
