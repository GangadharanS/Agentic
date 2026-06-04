"""FixerAgent — applies AI-generated fixes file-by-file via remote MCP.

ADK port of Orchestration/agents/fixer_agent.py. The LLM rewrite uses
``gcp_llm`` (Vertex AI or AI Studio Gemini) instead of google.generativeai.

Same-repo PRs:  read from + write to the PR's HEAD branch.
Fork PRs:       read from the FORK at head_sha; write to ai-fixes/pr-<N> in base.
"""
from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from typing import AsyncGenerator

import _react_path  # noqa: F401

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event

from gcp_llm import DEFAULT_MODEL, generate_text, llm_available
from mcp_client import get_mcp_client
from prompts import FIXER_SYSTEM_PROMPT, FIXER_USER_TEMPLATE
from state import ACTION_PUSH_MAX_ITER
from state import append as state_append

from ._mcp_parse import extract_text, log_event, parse_get_file_contents


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z0-9_+\-]*\n?", "", stripped)
        if stripped.endswith("```"):
            stripped = stripped[:-3].rstrip()
    return stripped


async def _fix_one_file(*, model_name: str, file_path: str, file_content: str, comments: list[dict]) -> str | None:
    comments_block = "\n".join(
        f"  - line {c.get('line', '?')} [{(c.get('severity') or 'major').upper()}] "
        f"{c.get('category') or 'logic'}: {c.get('text', '')}"
        for c in comments
    )
    user_prompt = FIXER_USER_TEMPLATE.format(
        file_path=file_path,
        file_content=file_content,
        comments_block=comments_block,
    )
    text = await generate_text(
        model_name=model_name,
        system_instruction=FIXER_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        max_output_tokens=8192,
        temperature=0.1,
    )
    if not text:
        return None
    return _strip_code_fences(text)


class FixerAgent(BaseAgent):
    """Apply fixes for fixable comments; fork-aware read/write targets."""

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        state = ctx.session.state

        base_owner = state["repo_owner"]
        base_repo = state["repo_name"]
        is_fork = state.get("is_fork", False)
        ai_branch = state.get("ai_fix_branch") or ""
        head_branch = state.get("head_branch") or ""
        head_sha = state.get("head_sha") or ""
        head_repo_owner = state.get("head_repo_owner") or base_owner
        head_repo_name = state.get("head_repo_name") or base_repo

        iteration = state.get("iteration", 0) + 1
        state["iteration"] = iteration

        fix_sevs = set(state.get("fix_severities") or ["blocking", "major"])
        fixable = [
            c for c in (state.get("review_comments") or [])
            if (c.get("severity") or "minor") in fix_sevs
            and c.get("file") and c.get("file") != "<ci>"
        ]

        ev = log_event(
            self.name,
            f"[Fixer] iteration {iteration} — {len(fixable)} fixable comment(s) across "
            f"{len({c.get('file') for c in fixable})} file(s)" + (" (fork-mode)" if is_fork else ""),
        )
        if ev:
            yield ev

        # Resolve read/write targets
        if is_fork:
            if not ai_branch:
                state_append(state, "fixes_history", [{"file": "<setup>", "success": False, "error": "fork mode but ai_fix_branch missing"}])
                state["error"] = "Fork mode but ai_fix_branch was not prepared by init."
                state["next_action"] = ACTION_PUSH_MAX_ITER
                state["review_comments"] = []
                return
            read_owner, read_repo = head_repo_owner, head_repo_name
            read_ref = head_sha or head_branch
            write_owner, write_repo, write_branch = base_owner, base_repo, ai_branch
        else:
            if not head_branch:
                state_append(state, "fixes_history", [{"file": "<setup>", "success": False, "error": "head_branch unknown"}])
                state["error"] = "Same-repo mode but head_branch was not resolved."
                state["next_action"] = ACTION_PUSH_MAX_ITER
                state["review_comments"] = []
                return
            read_owner, read_repo = base_owner, base_repo
            read_ref = head_branch
            write_owner, write_repo, write_branch = base_owner, base_repo, head_branch

        if not fixable:
            state_append(state, "fixes_history", [])
            state["review_comments"] = []
            return

        if not llm_available():
            state_append(
                state,
                "fixes_history",
                [{"file": c["file"], "success": False, "error": "No GCP/Gemini credentials"} for c in fixable],
            )
            state["error"] = "No GCP/Gemini credentials (set GOOGLE_API_KEY/GEMINI_API_KEY or Vertex env)."
            state["next_action"] = ACTION_PUSH_MAX_ITER
            state["review_comments"] = []
            return

        model_name = os.getenv("GEMINI_MODEL", DEFAULT_MODEL)

        by_file: dict[str, list[dict]] = defaultdict(list)
        for c in fixable:
            by_file[c["file"]].append(c)

        mcp = get_mcp_client()
        attempts: list[dict] = []

        for file_path, comments in by_file.items():
            ev = log_event(self.name, f"[Fixer]   -> {file_path} ({len(comments)} comments)")
            if ev:
                yield ev

            get_res = await mcp.call_tool(
                "get_file_contents",
                {"owner": read_owner, "repo": read_repo, "path": file_path, "ref": read_ref},
            )
            if not get_res.get("success"):
                attempts.append({"file": file_path, "success": False, "error": f"get_file_contents failed: {get_res.get('error')}"})
                continue

            parsed = parse_get_file_contents(get_res.get("data"))
            if not parsed:
                attempts.append({"file": file_path, "success": False, "error": "Could not parse get_file_contents response"})
                continue
            current_content, _read_sha = parsed
            if not current_content:
                attempts.append({"file": file_path, "success": False, "error": "Empty file content from MCP"})
                continue

            new_content = await _fix_one_file(
                model_name=model_name, file_path=file_path,
                file_content=current_content, comments=comments,
            )
            if not new_content or new_content == current_content:
                attempts.append({"file": file_path, "success": False, "error": "LLM produced no change"})
                continue

            write_sha = ""
            write_get = await mcp.call_tool(
                "get_file_contents",
                {"owner": write_owner, "repo": write_repo, "path": file_path, "ref": write_branch},
            )
            if write_get.get("success"):
                wparsed = parse_get_file_contents(write_get.get("data"))
                if wparsed:
                    write_sha = wparsed[1]

            commit_msg = f"[ai-fix] iter {iteration}: address {len(comments)} review comment(s) in {file_path}"
            put_args = {
                "owner": write_owner,
                "repo": write_repo,
                "path": file_path,
                "content": new_content,
                "message": commit_msg,
                "branch": write_branch,
            }
            if write_sha:
                put_args["sha"] = write_sha

            put_res = await mcp.call_tool("create_or_update_file", put_args)
            if not put_res.get("success"):
                attempts.append({"file": file_path, "success": False, "error": f"create_or_update_file failed: {put_res.get('error')}"})
                continue

            commit_sha = ""
            try:
                data_obj = json.loads(extract_text(put_res.get("data")))
                if isinstance(data_obj, dict):
                    commit_sha = (data_obj.get("commit") or {}).get("sha", "") or data_obj.get("sha", "")
            except Exception:
                pass

            attempts.append({"file": file_path, "success": True, "commit_sha": commit_sha, "message": commit_msg})
            ev = log_event(
                self.name,
                f"[Fixer]   committed {file_path} -> {write_owner}/{write_repo}@{write_branch}"
                + (f" ({commit_sha[:7]})" if commit_sha else ""),
            )
            if ev:
                yield ev

        state_append(state, "fixes_history", attempts)
        state["review_comments"] = []  # clear so tester/reviewer regenerate fresh
