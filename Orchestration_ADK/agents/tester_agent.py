"""TesterAgent — polls GitHub Actions check runs via remote MCP.

ADK port of Orchestration/agents/tester_agent.py.

On failure: converts failed checks into synthetic `blocking` review comments and
sets next_action=tests_fail (orchestrator routes back to the Fixer). On
success / no-CI: sets tests_pass / tests_skip (orchestrator re-reviews).
"""
from __future__ import annotations

import asyncio
from typing import Any, AsyncGenerator

import _react_path  # noqa: F401

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event

from mcp_client import get_mcp_client
from state import ACTION_TESTS_FAIL, ACTION_TESTS_PASS, ACTION_TESTS_SKIP
from state import append as state_append

from ._mcp_parse import log_event, parse_json

POLL_INTERVAL_S = 15


def _normalize_check_runs(obj: Any) -> list[dict]:
    if isinstance(obj, dict):
        if "check_runs" in obj:
            return obj["check_runs"] or []
        if "workflow_runs" in obj:
            return obj["workflow_runs"] or []
        if "status" in obj and "conclusion" in obj:
            return [obj]
    if isinstance(obj, list):
        return obj
    return []


async def _fetch_check_runs(mcp, *, owner: str, repo: str, ref: str) -> list[dict] | None:
    for tool, args in (
        ("list_check_runs_for_ref", {"owner": owner, "repo": repo, "ref": ref}),
        ("get_pull_request_status", None),
    ):
        if args is None:
            continue
        res = await mcp.call_tool(tool, args)
        if res.get("success"):
            return _normalize_check_runs(parse_json(res.get("data")))
    return None


def _comments_from_failed_checks(failed: list[dict]) -> list[dict]:
    comments: list[dict] = []
    for ck in failed:
        name = ck.get("name") or ck.get("display_title") or "unknown_check"
        summary = (ck.get("output") or {}).get("summary") or ck.get("conclusion") or ""
        comments.append({
            "file": "<ci>",
            "line": 0,
            "text": f"CI check **{name}** failed: {summary or 'see GitHub Actions logs for details'}",
            "severity": "blocking",
            "category": "test_failure",
            "type": "ci",
            "source": "tester",
        })
    return comments


class TesterAgent(BaseAgent):
    """Watch CI on the latest commit; route based on the conclusion."""

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        state = ctx.session.state

        if not state.get("enable_tester", True):
            state["next_action"] = ACTION_TESTS_SKIP
            state_append(state, "test_history", {"success": True, "conclusion": "skipped", "head_sha": "", "summary": "tester disabled"})
            return

        owner = state["repo_owner"]
        repo = state["repo_name"]
        is_fork = state.get("is_fork", False)
        ai_branch = state.get("ai_fix_branch") or ""
        head_branch = state.get("head_branch") or ""
        ref = ai_branch if (is_fork and ai_branch) else head_branch

        if not ref:
            state["next_action"] = ACTION_TESTS_SKIP
            state_append(state, "test_history", {"success": True, "conclusion": "skipped", "head_sha": "", "summary": "no ref"})
            return

        timeout = int(state.get("tester_timeout_s", 600))
        deadline = asyncio.get_event_loop().time() + timeout
        mcp = get_mcp_client()

        ev = log_event(self.name, f"[Tester] watching CI on {owner}/{repo}@{ref} (timeout {timeout}s)")
        if ev:
            yield ev

        last_seen_total = 0
        while True:
            runs = await _fetch_check_runs(mcp, owner=owner, repo=repo, ref=ref)
            if runs is None:
                state["next_action"] = ACTION_TESTS_SKIP
                state_append(state, "test_history", {"success": True, "conclusion": "no_ci", "head_sha": ref, "summary": "MCP server exposes no check-run tool"})
                ev = log_event(self.name, "[Tester] no CI tool available on this MCP server — skipping")
                if ev:
                    yield ev
                return

            if not runs:
                if asyncio.get_event_loop().time() > deadline:
                    state["next_action"] = ACTION_TESTS_SKIP
                    state_append(state, "test_history", {"success": True, "conclusion": "no_ci", "head_sha": ref, "summary": "no workflow runs found"})
                    ev = log_event(self.name, "[Tester] no CI runs before timeout — treating as no_ci")
                    if ev:
                        yield ev
                    return
                await asyncio.sleep(POLL_INTERVAL_S)
                continue

            if len(runs) != last_seen_total:
                last_seen_total = len(runs)
                ev = log_event(self.name, f"[Tester] tracking {len(runs)} check run(s)")
                if ev:
                    yield ev

            in_progress = [r for r in runs if (r.get("status") or "").lower() != "completed"]
            if in_progress:
                if asyncio.get_event_loop().time() > deadline:
                    state["next_action"] = ACTION_TESTS_FAIL
                    state["review_comments"] = []
                    state_append(state, "test_history", {
                        "success": False, "conclusion": "timed_out", "head_sha": ref,
                        "summary": f"{len(in_progress)} check(s) still running after {timeout}s",
                        "timed_out": True,
                    })
                    ev = log_event(self.name, f"[Tester] {len(in_progress)} check(s) still running at timeout — treating as failure")
                    if ev:
                        yield ev
                    return
                await asyncio.sleep(POLL_INTERVAL_S)
                continue

            failed = [r for r in runs if (r.get("conclusion") or "").lower() in {"failure", "timed_out", "cancelled", "action_required"}]
            if failed:
                comments = _comments_from_failed_checks(failed)
                state["next_action"] = ACTION_TESTS_FAIL
                state["review_comments"] = comments
                state_append(state, "review_history", comments)
                state_append(state, "test_history", {
                    "success": False, "conclusion": "failure", "head_sha": ref,
                    "summary": f"{len(failed)}/{len(runs)} check(s) failed",
                    "failed_checks": [{"name": f.get("name"), "conclusion": f.get("conclusion")} for f in failed],
                })
                ev = log_event(self.name, f"[Tester] {len(failed)} check(s) failed — feeding back to fixer")
                if ev:
                    yield ev
                return

            state["next_action"] = ACTION_TESTS_PASS
            state_append(state, "test_history", {"success": True, "conclusion": "success", "head_sha": ref, "summary": f"{len(runs)}/{len(runs)} checks passed"})
            ev = log_event(self.name, f"[Tester] all {len(runs)} check(s) passed")
            if ev:
                yield ev
            return
