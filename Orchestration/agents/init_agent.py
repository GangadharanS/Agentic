"""Init node — runs once, resolves head/base/fork info and prepares AI branch."""
from __future__ import annotations

import json
import os
from typing import Any

import _react_path  # noqa: F401

from mcp_bridge import MCPClient  # type: ignore

from llm_client import generate_text, slm_enabled, slm_model
from prompts import INIT_SLM_SYSTEM, INIT_SLM_USER_TEMPLATE
from state import OrchestrationState


def _extract_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if "content" in value and isinstance(value["content"], list):
            parts = []
            for item in value["content"]:
                if isinstance(item, dict) and "text" in item:
                    parts.append(item["text"])
            return "\n".join(parts) if parts else json.dumps(value)
        return json.dumps(value)
    return str(value)


def _parse_json(raw: Any) -> dict | None:
    text = _extract_text(raw)
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(obj, list) and obj:
        obj = obj[0]
    return obj if isinstance(obj, dict) else None


async def init_node(state: OrchestrationState) -> dict[str, Any]:
    """Resolve PR metadata, detect fork, create AI branch if needed."""
    if state.get("init_done"):
        return {}

    owner = state["repo_owner"]
    repo = state["repo_name"]
    pr_num = int(state["pr_number"])

    mcp = MCPClient(server_url=os.getenv("MCP_SERVER_URL"))

    print(f"[Init] resolving PR metadata for {owner}/{repo}#{pr_num}")
    pr_res = await mcp.call_tool(
        "get_pull_request",
        {"owner": owner, "repo": repo, "pullNumber": pr_num},
    )
    if not pr_res.get("success"):
        return {
            "init_done": True,
            "error": f"init: get_pull_request failed: {pr_res.get('error')}",
            "next_action": "push_max_iter",
        }

    pr = _parse_json(pr_res.get("data")) or {}
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

    update: dict[str, Any] = {
        "init_done": True,
        "head_branch": head.get("ref") or state.get("head_branch") or "",
        "head_sha": head.get("sha") or "",
        "base_branch": base.get("ref") or state.get("base_branch") or "main",
        "head_repo_owner": head_owner,
        "head_repo_name": head_name,
        "is_fork": is_fork,
        "pr_title": pr.get("title") or state.get("pr_title") or "",
    }

    if is_fork:
        ai_branch = f"ai-fixes/pr-{pr_num}"
        update["ai_fix_branch"] = ai_branch
        print(f"[Init] fork PR detected ({head_repo_full}); preparing branch '{ai_branch}' in {owner}/{repo}")

        # Best-effort: idempotently create the AI branch from the base branch in our repo.
        # github-mcp-server `create_branch` typically: {owner, repo, branch, from_branch}
        cb = await mcp.call_tool(
            "create_branch",
            {
                "owner": owner,
                "repo": repo,
                "branch": ai_branch,
                "from_branch": update["base_branch"],
            },
        )
        if cb.get("success"):
            print(f"[Init] created branch {ai_branch} from {update['base_branch']}")
        else:
            err = (cb.get("error") or "").lower()
            if "already exists" in err or "reference already exists" in err or "422" in err:
                print(f"[Init] branch {ai_branch} already exists — reusing")
            else:
                print(f"[Init] warning: create_branch failed ({cb.get('error')}); fork-mode fixes will be skipped")
                update["ai_fix_branch"] = ""  # disable fork-mode fixes
    else:
        print(f"[Init] same-repo PR; will commit fixes directly to '{update['head_branch']}'")

    if slm_enabled():
        model = slm_model("GEMINI_MODEL_INIT")
        head_repo_full = f"{head_owner}/{head_name}"
        body_excerpt = (pr.get("body") or "")[:400].replace("\n", " ")
        brief = await generate_text(
            model_name=model,
            system_instruction=INIT_SLM_SYSTEM,
            user_prompt=INIT_SLM_USER_TEMPLATE.format(
                pr_number=pr_num,
                pr_title=update.get("pr_title") or "",
                repo_owner=owner,
                repo_name=repo,
                head_repo=head_repo_full,
                head_branch=update.get("head_branch") or "",
                head_sha_short=(update.get("head_sha") or "")[:8],
                base_branch=update.get("base_branch") or "main",
                is_fork=is_fork,
                ai_fix_branch=update.get("ai_fix_branch") or "(n/a — same-repo)",
                body_excerpt=body_excerpt or "(no description)",
            ),
            max_output_tokens=512,
        )
        if brief:
            update["init_brief"] = brief
            print(f"[Init] SLM brief ({model}):\n{brief}")

    return update
