"""Utilities for applying agent partial updates to the shared A2A state."""
from __future__ import annotations

from copy import deepcopy
from typing import Any


APPEND_FIELDS = {
    "review_history",
    "fixes_history",
    "react_steps_log",
    "test_history",
    "a2a_events",
}


def initial_state(
    *,
    owner: str,
    name: str,
    pr_number: int,
    max_iter: int,
    severities: list[str],
    enable_tester: bool,
    tester_timeout_s: int,
) -> dict[str, Any]:
    return {
        "repo_owner": owner,
        "repo_name": name,
        "pr_number": pr_number,
        "iteration": 0,
        "max_iterations": max_iter,
        "fix_severities": severities,
        "enable_tester": enable_tester,
        "tester_timeout_s": tester_timeout_s,
        "init_done": False,
        "review_history": [],
        "fixes_history": [],
        "react_steps_log": [],
        "test_history": [],
        "a2a_events": [],
    }


def apply_update(state: dict[str, Any], update: dict[str, Any], *, agent: str) -> dict[str, Any]:
    """Apply a node-style partial update and return a new JSON-serializable state."""
    merged = deepcopy(state)
    for key, value in (update or {}).items():
        if key in APPEND_FIELDS:
            current = merged.get(key) or []
            if isinstance(value, list):
                merged[key] = [*current, *value]
            else:
                merged[key] = [*current, value]
        else:
            merged[key] = value

    merged.setdefault("a2a_events", [])
    merged["a2a_events"].append(
        {
            "agent": agent,
            "updated_keys": sorted((update or {}).keys()),
            "next_action": merged.get("next_action"),
            "iteration": merged.get("iteration", 0),
        }
    )
    return merged
