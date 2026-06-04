"""ReviewerAgent — runs the ReAct PR review, sets review_comments + next_action.

ADK port of Orchestration/agents/reviewer_agent.py. Reuses ReAct's
``PRReviewAgent`` (its ReAct loop over the remote GitHub MCP tools, driven by a
Gemini model). The routing decision (_decide_next) is identical to LangGraph.

Note on "GCP models": PRReviewAgent uses the Gemini API (Google AI Studio key)
for its ReAct loop. The Fixer / Init / Pusher agents use ``gcp_llm`` which can
target Vertex AI directly. To run the reviewer on Vertex too, you would swap in
a native google-genai ReAct loop; reusing PRReviewAgent keeps the review robust
against the GitHub MCP tool schemas.
"""
from __future__ import annotations

import os
from typing import AsyncGenerator

import _react_path  # noqa: F401

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event

from pr_reviewer import PRReviewAgent  # type: ignore

from state import (
    ACTION_FIX,
    ACTION_PUSH_CLEAN,
    ACTION_PUSH_MAX_ITER,
    ACTION_PUSH_NO_FIXABLE,
)
from state import append as state_append

from ._mcp_parse import log_event


def decide_next(state: dict, comments: list[dict]) -> str:
    """Pure routing logic — identical to the LangGraph reviewer."""
    fix_sevs = set(state.get("fix_severities") or ["blocking", "major"])
    fixable = [c for c in comments if (c.get("severity") or "minor") in fix_sevs]

    iteration = state.get("iteration", 0)
    max_iter = state.get("max_iterations", 5)

    if not comments:
        return ACTION_PUSH_CLEAN
    if not fixable:
        return ACTION_PUSH_NO_FIXABLE
    if iteration >= max_iter:
        return ACTION_PUSH_MAX_ITER
    return ACTION_FIX


class ReviewerAgent(BaseAgent):
    """Run one ReAct review pass; write comments + next_action into state."""

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        repo = f"{state['repo_owner']}/{state['repo_name']}"
        pr_id = state["pr_number"]

        agent = PRReviewAgent(mcp_server_url=os.getenv("MCP_SERVER_URL"))

        ev = log_event(self.name, f"[Reviewer] iteration {state.get('iteration', 0)} — reviewing {repo}#{pr_id}")
        if ev:
            yield ev

        result = await agent.review(repo=repo, pr_id=pr_id, verbose=False, max_rounds=8)

        comments = result.get("comments") or []
        summary = result.get("summary") or {}

        next_action = decide_next(state, comments)

        state["review_comments"] = comments
        state_append(state, "review_history", comments)
        state["next_action"] = next_action

        if summary.get("source_branch") and not state.get("head_branch"):
            state["head_branch"] = summary["source_branch"]
        if summary.get("destination_branch") and not state.get("base_branch"):
            state["base_branch"] = summary["destination_branch"]
        if summary.get("pr_title") and not state.get("pr_title"):
            state["pr_title"] = summary["pr_title"]

        if not result.get("success"):
            state["error"] = result.get("error") or "Reviewer returned success=false"

        ev = log_event(self.name, f"[Reviewer] {len(comments)} comment(s) — next_action={next_action}")
        if ev:
            yield ev
