"""InitAgent — runs once: resolve head/base/fork info, prepare AI branch.

ADK port of Orchestration/agents/init_agent.py (LangGraph init_node).
"""
from __future__ import annotations

from typing import AsyncGenerator

import _react_path  # noqa: F401

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event

from gcp_llm import generate_text, slm_enabled, slm_model
from mcp_client import get_mcp_client
from prompts import INIT_SLM_SYSTEM, INIT_SLM_USER_TEMPLATE
from state import ACTION_PUSH_MAX_ITER

from ._mcp_parse import log_event, parse_json_obj


class InitAgent(BaseAgent):
    """Resolve PR metadata, detect fork, create the ai-fixes branch when needed."""

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        state = ctx.session.state

        if state.get("init_done"):
            return

        owner = state["repo_owner"]
        repo = state["repo_name"]
        pr_num = int(state["pr_number"])

        mcp = get_mcp_client()

        ev = log_event(self.name, f"[Init] resolving PR metadata for {owner}/{repo}#{pr_num}")
        if ev:
            yield ev

        pr_res = await mcp.call_tool(
            "get_pull_request",
            {"owner": owner, "repo": repo, "pullNumber": pr_num},
        )
        if not pr_res.get("success"):
            state["init_done"] = True
            state["error"] = f"init: get_pull_request failed: {pr_res.get('error')}"
            state["next_action"] = ACTION_PUSH_MAX_ITER
            ev = log_event(self.name, f"[Init] get_pull_request failed: {pr_res.get('error')}")
            if ev:
                yield ev
            return

        pr = parse_json_obj(pr_res.get("data")) or {}
        head = pr.get("head") or {}
        base = pr.get("base") or {}
        head_repo = head.get("repo") or {}
        base_repo = base.get("repo") or {}

        head_repo_full = head_repo.get("full_name") or f"{owner}/{repo}"
        base_repo_full = base_repo.get("full_name") or f"{owner}/{repo}"
        is_fork = head_repo_full != base_repo_full

        head_owner, _, head_name = head_repo_full.partition("/")
        if not head_name:
            head_owner, head_name = owner, repo

        state["init_done"] = True
        state["head_branch"] = head.get("ref") or state.get("head_branch") or ""
        state["head_sha"] = head.get("sha") or ""
        state["base_branch"] = base.get("ref") or state.get("base_branch") or "main"
        state["head_repo_owner"] = head_owner
        state["head_repo_name"] = head_name
        state["is_fork"] = is_fork
        state["pr_title"] = pr.get("title") or state.get("pr_title") or ""

        if is_fork:
            ai_branch = f"ai-fixes/pr-{pr_num}"
            state["ai_fix_branch"] = ai_branch
            ev = log_event(
                self.name,
                f"[Init] fork PR detected ({head_repo_full}); preparing '{ai_branch}' in {owner}/{repo}",
            )
            if ev:
                yield ev

            cb = await mcp.call_tool(
                "create_branch",
                {
                    "owner": owner,
                    "repo": repo,
                    "branch": ai_branch,
                    "from_branch": state["base_branch"],
                },
            )
            if cb.get("success"):
                msg = f"[Init] created branch {ai_branch} from {state['base_branch']}"
            else:
                err = (cb.get("error") or "").lower()
                if "already exists" in err or "reference already exists" in err or "422" in err:
                    msg = f"[Init] branch {ai_branch} already exists — reusing"
                else:
                    msg = f"[Init] warning: create_branch failed ({cb.get('error')}); fork-mode fixes skipped"
                    state["ai_fix_branch"] = ""
            ev = log_event(self.name, msg)
            if ev:
                yield ev
        else:
            ev = log_event(
                self.name,
                f"[Init] same-repo PR; fixes commit directly to '{state['head_branch']}'",
            )
            if ev:
                yield ev

        if slm_enabled():
            model = slm_model("GEMINI_MODEL_INIT")
            body_excerpt = (pr.get("body") or "")[:400].replace("\n", " ")
            brief = await generate_text(
                model_name=model,
                system_instruction=INIT_SLM_SYSTEM,
                user_prompt=INIT_SLM_USER_TEMPLATE.format(
                    pr_number=pr_num,
                    pr_title=state.get("pr_title") or "",
                    repo_owner=owner,
                    repo_name=repo,
                    head_repo=f"{head_owner}/{head_name}",
                    head_branch=state.get("head_branch") or "",
                    head_sha_short=(state.get("head_sha") or "")[:8],
                    base_branch=state.get("base_branch") or "main",
                    is_fork=is_fork,
                    ai_fix_branch=state.get("ai_fix_branch") or "(n/a — same-repo)",
                    body_excerpt=body_excerpt or "(no description)",
                ),
                max_output_tokens=512,
            )
            if brief:
                state["init_brief"] = brief
                ev = log_event(self.name, f"[Init] SLM brief ({model}):\n{brief}")
                if ev:
                    yield ev
