"""Pusher node — final step.

Same-repo PRs: posts a COMMENT review summarizing iterations.
Fork PRs:      opens a stacked PR `ai-fixes/pr-<N>` → base_branch AND posts a summary
               comment on the original PR linking to it.
"""
from __future__ import annotations

import json
import os
from typing import Any

import _react_path  # noqa: F401

from mcp_bridge import MCPClient  # type: ignore

from llm_client import generate_text, slm_enabled, slm_model
from prompts import PUSHER_SLM_SYSTEM, PUSHER_SLM_USER_TEMPLATE, PUSHER_SUMMARY_TEMPLATE
from state import OrchestrationState


STATUS_LABEL = {
    "push_clean": "✅ Clean — all review comments addressed.",
    "push_no_fixable": "ℹ️  Only minor issues remain (not auto-fixable).",
    "push_max_iter": "⚠️  Max iterations reached — some issues may remain.",
    "tests_fail": "🔴 Tests still failing after max iterations.",
}


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
    try:
        return json.loads(_extract_text(raw))
    except json.JSONDecodeError:
        return None


def _build_outcome_block(state: OrchestrationState) -> str:
    history = state.get("review_history") or []
    latest_comments = history[-1] if history else []
    fixes_total = sum(
        sum(1 for f in fixes if f.get("success"))
        for fixes in (state.get("fixes_history") or [])
    )
    test_runs = state.get("test_history") or []
    test_line = ""
    if test_runs:
        last = test_runs[-1]
        test_line = f"\n- Latest CI conclusion: **{last.get('conclusion', 'unknown')}** — {last.get('summary', '')}"

    lines = [f"- Successful file fixes applied: **{fixes_total}**{test_line}"]
    if not latest_comments:
        lines.append("- No outstanding review comments after final pass.")
    else:
        lines.append(f"- {len(latest_comments)} comment(s) remaining:")
        for c in latest_comments:
            lines.append(
                f"  - **[{(c.get('severity') or 'minor').upper()}]** "
                f"`{c.get('file', '?')}`:{c.get('line', '?')} — {c.get('text', '')}"
            )
    return "\n".join(lines)


def _build_iteration_trail(state: OrchestrationState) -> str:
    fixes_history = state.get("fixes_history") or []
    review_history = state.get("review_history") or []
    test_history = state.get("test_history") or []
    rows = []
    for i, rev in enumerate(review_history):
        fix_block = fixes_history[i] if i < len(fixes_history) else []
        successes = sum(1 for f in fix_block if f.get("success"))
        total = len(fix_block)
        test_part = ""
        if i < len(test_history):
            test_part = f", CI: {test_history[i].get('conclusion', '?')}"
        rows.append(
            f"- **Iter {i}:** {len(rev)} comment(s)"
            + (f", {successes}/{total} file(s) auto-fixed" if total else "")
            + test_part
        )
    return "\n".join(rows) if rows else "_(no iterations)_"


def _template_body(state: OrchestrationState, next_action: str, iterations: int) -> str:
    return PUSHER_SUMMARY_TEMPLATE.format(
        iterations=iterations,
        status_label=STATUS_LABEL.get(next_action, next_action),
        outcome_block=_build_outcome_block(state),
        iteration_trail=_build_iteration_trail(state),
    )


async def _build_review_body(state: OrchestrationState, next_action: str, iterations: int) -> str:
    """Prefer SLM-polished markdown; fall back to deterministic template."""
    template = _template_body(state, next_action, iterations)
    if not slm_enabled():
        return template

    model = slm_model("GEMINI_MODEL_PUSHER")
    slm_body = await generate_text(
        model_name=model,
        system_instruction=PUSHER_SLM_SYSTEM,
        user_prompt=PUSHER_SLM_USER_TEMPLATE.format(
            status_label=STATUS_LABEL.get(next_action, next_action),
            iterations=iterations,
            is_fork=state.get("is_fork", False),
            stacked_pr_url=state.get("stacked_pr_url") or "(none yet)",
            outcome_block=_build_outcome_block(state),
            iteration_trail=_build_iteration_trail(state),
        ),
        max_output_tokens=2048,
    )
    if slm_body:
        print(f"[Pusher] using SLM summary ({model})")
        return slm_body

    print(f"[Pusher] SLM unavailable — using template summary")
    return template


async def _open_stacked_pr(mcp, state: OrchestrationState, body: str) -> str | None:
    """Open ai-fixes/pr-<N> → base_branch in the base repo."""
    owner = state["repo_owner"]
    repo = state["repo_name"]
    head = state["ai_fix_branch"]
    base = state.get("base_branch", "main")
    original = state["pr_number"]
    title = f"AI fixes for #{original}: {state.get('pr_title') or 'auto-generated review fixes'}"

    pr_body = (
        f"Automated AI fixes for #{original} (original PR is from a fork).\n\n"
        f"This branch contains LLM-generated fixes for review comments raised on the original PR. "
        f"Merge this PR (or its commits) into the original PR for human verification.\n\n"
        f"---\n\n{body}"
    )

    res = await mcp.call_tool(
        "create_pull_request",
        {"owner": owner, "repo": repo, "title": title, "head": head, "base": base, "body": pr_body},
    )
    if not res.get("success"):
        print(f"[Pusher] stacked PR creation failed: {res.get('error')}")
        return None
    data = _parse_json(res.get("data")) or {}
    url = data.get("html_url") or data.get("url")
    print(f"[Pusher] ✓ stacked PR opened: {url}")
    return url


async def _post_summary_review(mcp, state: OrchestrationState, body: str) -> str | None:
    """Post a COMMENT review on the original PR."""
    res = await mcp.call_tool(
        "create_pull_request_review",
        {
            "owner": state["repo_owner"],
            "repo": state["repo_name"],
            "pullNumber": int(state["pr_number"]),
            "event": "COMMENT",
            "body": body,
        },
    )
    if not res.get("success"):
        print(f"[Pusher] summary review failed: {res.get('error')}")
        return None
    data = _parse_json(res.get("data")) or {}
    url = data.get("html_url") or data.get("url")
    if url:
        print(f"[Pusher] ✓ summary review posted: {url}")
    return url


async def pusher_node(state: OrchestrationState) -> dict[str, Any]:
    next_action = state.get("next_action") or "push_clean"
    iterations = state.get("iteration", 0)

    body = await _build_review_body(state, next_action, iterations)

    print(f"[Pusher] finalizing (status={next_action}, iterations={iterations}, "
          f"{'fork-mode' if state.get('is_fork') else 'same-repo'})")

    mcp = MCPClient(server_url=os.getenv("MCP_SERVER_URL"))
    update: dict[str, Any] = {}

    stacked_url: str | None = None
    if state.get("is_fork") and state.get("ai_fix_branch"):
        any_fix = any(
            any(f.get("success") for f in batch)
            for batch in (state.get("fixes_history") or [])
        )
        if any_fix:
            stacked_url = await _open_stacked_pr(mcp, state, body)
            update["stacked_pr_url"] = stacked_url
        else:
            print("[Pusher] fork-mode: no successful fixes — skipping stacked PR")

    # Always post the summary review on the original PR.
    if stacked_url:
        body += f"\n\n---\n\n**📦 Stacked AI fixes PR:** {stacked_url}"
    review_url = await _post_summary_review(mcp, state, body)
    if review_url:
        update["summary_review_url"] = review_url

    if not review_url and not stacked_url:
        update["error"] = "Pusher could not post review or stacked PR."
    return update
