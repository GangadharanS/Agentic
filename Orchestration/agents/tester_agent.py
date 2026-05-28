"""Tester node — polls GitHub Actions check runs on the latest commit.

Strategy:
  - Determine target SHA: PR head_sha for same-repo, latest commit on ai_fix_branch for forks.
  - Poll `list_check_runs_for_ref` (or `list_workflow_runs`) until all runs are completed
    or timeout elapses.
  - On failure: convert failed checks into synthetic `blocking` review comments and route
    back to the Fixer. On success/no-CI: continue to the Reviewer for the next pass.
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import _react_path  # noqa: F401

from mcp_bridge import MCPClient  # type: ignore

from state import OrchestrationState, ReviewComment, TestRun


POLL_INTERVAL_S = 15
NO_CI_CONCLUSIONS = {"no_ci", "skipped"}


def _extract_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if "content" in value and isinstance(value["content"], list):
            parts = [it.get("text", "") for it in value["content"] if isinstance(it, dict)]
            return "\n".join(p for p in parts if p) or json.dumps(value)
        return json.dumps(value)
    return str(value)


def _parse_json(raw: Any) -> Any:
    text = _extract_text(raw)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _normalize_check_runs(obj: Any) -> list[dict]:
    """github-mcp-server list_check_runs returns {total_count, check_runs:[...]} or a list."""
    if isinstance(obj, dict):
        if "check_runs" in obj:
            return obj["check_runs"] or []
        if "workflow_runs" in obj:
            return obj["workflow_runs"] or []
        # Single check run
        if "status" in obj and "conclusion" in obj:
            return [obj]
    if isinstance(obj, list):
        return obj
    return []


async def _fetch_check_runs(mcp, *, owner: str, repo: str, ref: str) -> list[dict] | None:
    """Try the GitHub MCP tools that surface CI state. Return None on hard failure."""
    for tool, args in (
        ("list_check_runs_for_ref", {"owner": owner, "repo": repo, "ref": ref}),
        ("get_pull_request_status", None),  # fallback; PR-specific, no args here
    ):
        if args is None:
            continue
        res = await mcp.call_tool(tool, args)
        if res.get("success"):
            parsed = _parse_json(res.get("data"))
            return _normalize_check_runs(parsed)
    return None


def _comments_from_failed_checks(failed: list[dict]) -> list[ReviewComment]:
    comments: list[ReviewComment] = []
    for ck in failed:
        name = ck.get("name") or ck.get("display_title") or "unknown_check"
        summary = (ck.get("output") or {}).get("summary") or ck.get("conclusion") or ""
        text = f"CI check **{name}** failed: {summary or 'see GitHub Actions logs for details'}"
        comments.append({
            "file": "<ci>",
            "line": 0,
            "text": text,
            "severity": "blocking",
            "category": "test_failure",
            "type": "ci",
            "source": "tester",
        })
    return comments


async def tester_node(state: OrchestrationState) -> dict[str, Any]:
    if not state.get("enable_tester", True):
        return {"next_action": "tests_skip", "test_history": [{"success": True, "conclusion": "skipped", "head_sha": "", "summary": "tester disabled"}]}

    owner = state["repo_owner"]
    repo = state["repo_name"]
    is_fork = state.get("is_fork", False)
    ai_branch = state.get("ai_fix_branch") or ""
    head_branch = state.get("head_branch") or ""
    ref = ai_branch if (is_fork and ai_branch) else head_branch

    if not ref:
        print("[Tester] no ref available — skipping")
        return {
            "next_action": "tests_skip",
            "test_history": [{"success": True, "conclusion": "skipped", "head_sha": "", "summary": "no ref"}],
        }

    timeout = int(state.get("tester_timeout_s", 600))
    deadline = asyncio.get_event_loop().time() + timeout
    mcp = MCPClient(server_url=os.getenv("MCP_SERVER_URL"))

    print(f"[Tester] watching CI on {owner}/{repo}@{ref} (timeout {timeout}s)")
    last_seen_total = 0

    while True:
        runs = await _fetch_check_runs(mcp, owner=owner, repo=repo, ref=ref)
        if runs is None:
            print("[Tester] no CI tool available on this MCP server — skipping")
            return {
                "next_action": "tests_skip",
                "test_history": [{"success": True, "conclusion": "no_ci", "head_sha": ref, "summary": "MCP server exposes no check-run tool"}],
            }

        if not runs:
            if asyncio.get_event_loop().time() > deadline:
                print("[Tester] no CI runs detected before timeout — treating as no_ci")
                return {
                    "next_action": "tests_skip",
                    "test_history": [{"success": True, "conclusion": "no_ci", "head_sha": ref, "summary": "no workflow runs found"}],
                }
            print("[Tester] no runs yet — waiting…")
            await asyncio.sleep(POLL_INTERVAL_S)
            continue

        if len(runs) != last_seen_total:
            last_seen_total = len(runs)
            print(f"[Tester] tracking {len(runs)} check run(s)")

        in_progress = [r for r in runs if (r.get("status") or "").lower() != "completed"]
        if in_progress:
            if asyncio.get_event_loop().time() > deadline:
                print(f"[Tester] {len(in_progress)} check(s) still running at timeout — treating as failure")
                # Treat timeout as failure but with no actionable fixes
                return {
                    "next_action": "tests_fail",
                    "test_history": [{
                        "success": False, "conclusion": "timed_out", "head_sha": ref,
                        "summary": f"{len(in_progress)} check(s) still running after {timeout}s",
                        "timed_out": True,
                    }],
                    "review_comments": [],  # nothing fixable
                }
            await asyncio.sleep(POLL_INTERVAL_S)
            continue

        # All completed
        failed = [r for r in runs if (r.get("conclusion") or "").lower() in {"failure", "timed_out", "cancelled", "action_required"}]
        if failed:
            comments = _comments_from_failed_checks(failed)
            print(f"[Tester] ✗ {len(failed)} check(s) failed — feeding back to fixer")
            return {
                "next_action": "tests_fail",
                "test_history": [{
                    "success": False, "conclusion": "failure", "head_sha": ref,
                    "summary": f"{len(failed)}/{len(runs)} check(s) failed",
                    "failed_checks": [{"name": f.get("name"), "conclusion": f.get("conclusion")} for f in failed],
                }],
                "review_comments": comments,
                "review_history": [comments],
            }

        print(f"[Tester] ✓ all {len(runs)} check(s) passed")
        return {
            "next_action": "tests_pass",
            "test_history": [{"success": True, "conclusion": "success", "head_sha": ref, "summary": f"{len(runs)}/{len(runs)} checks passed"}],
        }


def route_after_tester(state: OrchestrationState) -> str:
    return state.get("next_action") or "tests_skip"
