"""Reviewer node — delegates to the existing ReAct PRReviewAgent."""
from __future__ import annotations

import os
from typing import Any

import _react_path  # noqa: F401 — adds ../ReAct to sys.path

from pr_reviewer import PRReviewAgent  # type: ignore

from state import OrchestrationState


def _decide_next(state: OrchestrationState, comments: list[dict]) -> str:
    """Pure routing logic: looks at the latest review + iteration count."""
    fix_sevs = set(state.get("fix_severities") or ["blocking", "major"])
    fixable = [c for c in comments if (c.get("severity") or "minor") in fix_sevs]

    iteration = state.get("iteration", 0)
    max_iter = state.get("max_iterations", 5)

    if not comments:
        return "push_clean"
    if not fixable:
        # Only minor issues remain — no fixer work, but still notify.
        return "push_no_fixable"
    if iteration >= max_iter:
        return "push_max_iter"
    return "fix"


async def reviewer_node(state: OrchestrationState) -> dict[str, Any]:
    """Run the ReAct PR reviewer once; update state with comments + next_action."""
    repo = f"{state['repo_owner']}/{state['repo_name']}"
    pr_id = state["pr_number"]

    agent = PRReviewAgent(mcp_server_url=os.getenv("MCP_SERVER_URL"))

    print(f"[Reviewer] iteration {state.get('iteration', 0)} — reviewing {repo}#{pr_id}")
    result = await agent.review(repo=repo, pr_id=pr_id, verbose=False, max_rounds=8)

    comments = result.get("comments") or []
    summary = result.get("summary") or {}

    next_action = _decide_next(state, comments)
    print(f"[Reviewer] {len(comments)} comments — next_action={next_action}")

    update: dict[str, Any] = {
        "review_comments": comments,
        "review_history": [comments],
        "react_steps_log": result.get("react_steps", []),
        "next_action": next_action,
    }

    if summary.get("source_branch") and not state.get("head_branch"):
        update["head_branch"] = summary["source_branch"]
    if summary.get("destination_branch") and not state.get("base_branch"):
        update["base_branch"] = summary["destination_branch"]
    if summary.get("pr_title") and not state.get("pr_title"):
        update["pr_title"] = summary["pr_title"]

    if not result.get("success"):
        update["error"] = result.get("error") or "Reviewer returned success=false"

    return update


def route_after_reviewer(state: OrchestrationState) -> str:
    """Conditional-edge function — returns one of: fix, push_clean, push_max_iter, push_no_fixable."""
    return state.get("next_action") or "push_clean"
