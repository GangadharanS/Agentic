"""Shared session-state schema for the ADK PR orchestrator.

Unlike LangGraph (which uses a typed `OrchestrationState` with reducers), ADK
agents communicate through a plain ``ctx.session.state`` dict. We keep the SAME
keys as the LangGraph version so the two implementations stay comparable, and
provide small helpers for the parts LangGraph handled automatically (list
appends that LangGraph did via ``Annotated[list, add]`` reducers).
"""
from __future__ import annotations

from typing import Any

# ---- Routing actions (identical to the LangGraph graph) ----
ACTION_FIX = "fix"
ACTION_PUSH_CLEAN = "push_clean"
ACTION_PUSH_NO_FIXABLE = "push_no_fixable"
ACTION_PUSH_MAX_ITER = "push_max_iter"
ACTION_TESTS_PASS = "tests_pass"
ACTION_TESTS_FAIL = "tests_fail"
ACTION_TESTS_SKIP = "tests_skip"

PUSH_ACTIONS = {ACTION_PUSH_CLEAN, ACTION_PUSH_NO_FIXABLE, ACTION_PUSH_MAX_ITER}


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
    """Build the seed session state (mirrors PROrchestrationAgent._initial_state)."""
    return {
        # Inputs
        "repo_owner": owner,
        "repo_name": name,
        "pr_number": pr_number,
        # Configuration
        "max_iterations": max_iter,
        "fix_severities": severities,
        "enable_tester": enable_tester,
        "tester_timeout_s": tester_timeout_s,
        # Loop state
        "iteration": 0,
        "init_done": False,
        "review_comments": [],
        "review_history": [],
        "fixes_history": [],
        "test_history": [],
        # Outputs
        "next_action": None,
        "summary_review_url": None,
        "stacked_pr_url": None,
        "error": None,
    }


def append(state: dict[str, Any], key: str, value: Any) -> None:
    """Reducer helper: append `value` to a list stored at state[key] (creates it)."""
    bucket = state.get(key)
    if not isinstance(bucket, list):
        bucket = []
    bucket.append(value)
    state[key] = bucket
