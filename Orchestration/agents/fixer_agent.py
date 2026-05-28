"""Fixer node — applies AI-generated fixes file-by-file via MCP.

Same-repo PRs:  read from + write to the PR's HEAD branch.
Fork PRs:       read from the FORK at head_sha; write to `ai-fixes/pr-<N>` in the base repo.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
from collections import defaultdict
from typing import Any

import _react_path  # noqa: F401

import google.generativeai as genai
from mcp_bridge import MCPClient  # type: ignore

from prompts import FIXER_SYSTEM_PROMPT, FIXER_USER_TEMPLATE
from state import OrchestrationState


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z0-9_+\-]*\n?", "", stripped)
        if stripped.endswith("```"):
            stripped = stripped[: -3].rstrip()
    return stripped


def _extract_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if "content" in value and isinstance(value["content"], list):
            parts = []
            for item in value["content"]:
                if isinstance(item, dict):
                    if "text" in item:
                        parts.append(item["text"])
                    elif "value" in item:
                        parts.append(str(item["value"]))
            return "\n".join(parts) if parts else json.dumps(value)
        return json.dumps(value)
    return str(value)


def _parse_get_file_contents(raw: Any) -> tuple[str, str] | None:
    text = _extract_text(raw)
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(obj, list) and obj:
        obj = obj[0]
    if not isinstance(obj, dict):
        return None
    sha = obj.get("sha", "")
    content = obj.get("content", "")
    if obj.get("encoding") == "base64" and content:
        try:
            content = base64.b64decode(content).decode("utf-8", errors="replace")
        except Exception:
            pass
    return (content or "", sha)


async def _fix_one_file(
    *,
    model: genai.GenerativeModel,
    file_path: str,
    file_content: str,
    comments: list[dict],
) -> str | None:
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

    try:
        response = await asyncio.to_thread(model.generate_content, [user_prompt])
    except Exception as exc:
        print(f"[Fixer] LLM error on {file_path}: {exc}")
        return None

    text = response.text if hasattr(response, "text") else ""
    if not text or not text.strip():
        print(f"[Fixer] Empty LLM response for {file_path}")
        return None
    return _strip_code_fences(text)


async def fixer_node(state: OrchestrationState) -> dict[str, Any]:
    """Apply fixes for blocking/major comments. Fork-aware read/write targets."""
    base_owner = state["repo_owner"]
    base_repo = state["repo_name"]
    is_fork = state.get("is_fork", False)
    ai_branch = state.get("ai_fix_branch") or ""
    head_branch = state.get("head_branch") or ""
    head_sha = state.get("head_sha") or ""
    head_repo_owner = state.get("head_repo_owner") or base_owner
    head_repo_name = state.get("head_repo_name") or base_repo

    iteration = state.get("iteration", 0) + 1

    fix_sevs = set(state.get("fix_severities") or ["blocking", "major"])
    # Skip synthetic <ci> entries — they're not file-level fixable.
    fixable: list[dict] = [
        c for c in (state.get("review_comments") or [])
        if (c.get("severity") or "minor") in fix_sevs
        and c.get("file") and c.get("file") != "<ci>"
    ]

    print(f"[Fixer] iteration {iteration} — {len(fixable)} fixable comment(s) "
          f"across {len({c.get('file') for c in fixable})} file(s)"
          + (" (fork-mode)" if is_fork else ""))

    # Resolve read/write targets
    if is_fork:
        if not ai_branch:
            return {
                "iteration": iteration,
                "fixes_history": [[{"file": "<setup>", "success": False, "error": "fork mode but ai_fix_branch missing"}]],
                "error": "Fork mode but ai_fix_branch was not prepared by init.",
                "next_action": "push_max_iter",
                "review_comments": [],
            }
        read_owner, read_repo = head_repo_owner, head_repo_name
        read_ref = head_sha or head_branch
        write_owner, write_repo, write_branch = base_owner, base_repo, ai_branch
    else:
        if not head_branch:
            return {
                "iteration": iteration,
                "fixes_history": [[{"file": "<setup>", "success": False, "error": "head_branch unknown"}]],
                "error": "Same-repo mode but head_branch was not resolved.",
                "next_action": "push_max_iter",
                "review_comments": [],
            }
        read_owner, read_repo = base_owner, base_repo
        read_ref = head_branch
        write_owner, write_repo, write_branch = base_owner, base_repo, head_branch

    if not fixable:
        return {
            "iteration": iteration,
            "fixes_history": [[]],
            "review_comments": [],
        }

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return {
            "iteration": iteration,
            "fixes_history": [[{"file": c["file"], "success": False, "error": "GEMINI_API_KEY not set"} for c in fixable]],
            "error": "GEMINI_API_KEY missing in environment.",
            "next_action": "push_max_iter",
            "review_comments": [],
        }
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
        system_instruction=FIXER_SYSTEM_PROMPT,
    )

    by_file: dict[str, list[dict]] = defaultdict(list)
    for c in fixable:
        by_file[c["file"]].append(c)

    mcp = MCPClient(server_url=os.getenv("MCP_SERVER_URL"))
    attempts: list[dict] = []

    for file_path, comments in by_file.items():
        print(f"[Fixer]   → {file_path} ({len(comments)} comments)")

        # 1. Read current content from the read target
        get_res = await mcp.call_tool(
            "get_file_contents",
            {"owner": read_owner, "repo": read_repo, "path": file_path, "ref": read_ref},
        )
        if not get_res.get("success"):
            attempts.append({"file": file_path, "success": False, "error": f"get_file_contents failed: {get_res.get('error')}"})
            continue

        parsed = _parse_get_file_contents(get_res.get("data"))
        if not parsed:
            attempts.append({"file": file_path, "success": False, "error": "Could not parse get_file_contents response"})
            continue
        current_content, _read_sha = parsed
        if not current_content:
            attempts.append({"file": file_path, "success": False, "error": "Empty file content from MCP"})
            continue

        # 2. LLM rewrite
        new_content = await _fix_one_file(
            model=model, file_path=file_path,
            file_content=current_content, comments=comments,
        )
        if not new_content or new_content == current_content:
            attempts.append({"file": file_path, "success": False, "error": "LLM produced no change"})
            continue

        # 3. Write target: get the existing sha on the WRITE branch (may differ from read sha,
        #    especially in fork mode where the write branch is `ai-fixes/...`).
        write_sha = ""
        write_get = await mcp.call_tool(
            "get_file_contents",
            {"owner": write_owner, "repo": write_repo, "path": file_path, "ref": write_branch},
        )
        if write_get.get("success"):
            wparsed = _parse_get_file_contents(write_get.get("data"))
            if wparsed:
                write_sha = wparsed[1]
        # If write_sha is empty, the file doesn't exist on the write branch yet — create_or_update_file handles both.

        commit_msg = (
            f"[ai-fix] iter {iteration}: address "
            f"{len(comments)} review comment(s) in {file_path}"
        )
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
        data_text = _extract_text(put_res.get("data"))
        try:
            data_obj = json.loads(data_text)
            if isinstance(data_obj, dict):
                commit_sha = (data_obj.get("commit") or {}).get("sha", "") or data_obj.get("sha", "")
        except Exception:
            pass

        attempts.append({"file": file_path, "success": True, "commit_sha": commit_sha, "message": commit_msg})
        print(f"[Fixer]   ✓ committed {file_path} → {write_owner}/{write_repo}@{write_branch}"
              + (f" ({commit_sha[:7]})" if commit_sha else ""))

    return {
        "iteration": iteration,
        "fixes_history": [attempts],
        "review_comments": [],  # clear so tester/reviewer regenerate fresh
    }
