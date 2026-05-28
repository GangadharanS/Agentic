"""
FastAPI backend for the ReAct PR Review UI.

Endpoints:
  GET    /api/health                          - service + MCP + Gemini status
  GET    /api/repos                           - list GitHub repos for the user
  GET    /api/repos/{owner}/{repo}/prs        - list PRs for a repo
  GET    /api/repos/{owner}/{repo}/prs/{pr}   - PR summary
  POST   /api/review                          - run ReAct PR review (SSE stream)
  GET    /api/mcp/tools                       - list discovered MCP tools
  GET    /api/mcp/config                      - get MCP/agent config
  POST   /api/mcp/config                      - update MCP/agent config (in-memory)
  POST   /api/mcp/tools/{name}/test           - call an MCP tool directly
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# Ensure ReAct/ is on path so `import` works regardless of how uvicorn is invoked
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

load_dotenv(_HERE / ".env")

from github_api import (  # noqa: E402
    get_pr_summary,
    github_health,
    list_repo_prs,
    list_user_repos,
)
from mcp_bridge import MCPClient  # noqa: E402
from pr_reviewer import PRReviewAgent  # noqa: E402
from prompts import PR_REVIEW_SYSTEM_PROMPT, PR_REVIEW_TOOLS, PR_REVIEW_USER_TEMPLATE  # noqa: E402
from react_agent import ReActAgent, parse_json_from_text  # noqa: E402

# ---------------------------------------------------------------------------
# In-memory runtime config (lives only for the lifetime of the process).
# Persisted config is on the .env file. The UI can override these at runtime.
# ---------------------------------------------------------------------------

class RuntimeConfig:
    def __init__(self):
        self.mcp_server_url: str = os.getenv("MCP_SERVER_URL", "http://localhost:8000")
        self.gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        self.max_rounds: int = int(os.getenv("REACT_MAX_ROUNDS", "8"))
        # Tools the LLM is allowed to call. None means "use defaults from prompts.py".
        self.tool_allowlist: List[str] = list(PR_REVIEW_TOOLS)

    def to_dict(self) -> dict:
        return {
            "mcp_server_url": self.mcp_server_url,
            "gemini_model": self.gemini_model,
            "max_rounds": self.max_rounds,
            "tool_allowlist": self.tool_allowlist,
        }


CONFIG = RuntimeConfig()


def get_mcp_client() -> MCPClient:
    return MCPClient(server_url=CONFIG.mcp_server_url)


def get_review_agent() -> PRReviewAgent:
    agent = PRReviewAgent(mcp_server_url=CONFIG.mcp_server_url)
    agent.agent.model_name = CONFIG.gemini_model
    return agent


# ---------------------------------------------------------------------------
# Lifespan: warm up MCP tool discovery once
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        client = get_mcp_client()
        await client.discover_tools()
        print(f"[ReAct UI] MCP discovered {len(client.tools)} tools")
    except Exception as exc:
        print(f"[ReAct UI] MCP discovery failed at startup: {exc}")
    yield


app = FastAPI(
    title="ReAct PR Review API",
    version="1.0.0",
    description="Backend for the ReAct PR Review UI.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health():
    mcp_client = get_mcp_client()
    mcp_ok = await mcp_client.health_check()
    if mcp_ok and not mcp_client.tools:
        try:
            await mcp_client.discover_tools()
        except Exception:
            pass

    gh = await github_health()
    gemini_configured = bool(os.getenv("GEMINI_API_KEY", "").strip())

    return {
        "status": "ok" if (mcp_ok and gemini_configured and gh.get("ok")) else "degraded",
        "mcp_server": {"url": CONFIG.mcp_server_url, "connected": mcp_ok, "tools": len(mcp_client.tools)},
        "gemini": {"configured": gemini_configured, "model": CONFIG.gemini_model},
        "github": gh,
    }


# ---------------------------------------------------------------------------
# GitHub repos & PRs (direct API, not via MCP)
# ---------------------------------------------------------------------------

@app.get("/api/repos")
async def repos(per_page: int = 50, visibility: str = "all"):
    try:
        items = await list_user_repos(per_page=per_page, visibility=visibility)
        return {"repos": items, "count": len(items)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/repos/{owner}/{repo}/prs")
async def repo_prs(owner: str, repo: str, state: str = "open"):
    try:
        items = await list_repo_prs(owner, repo, state=state)
        return {"prs": items, "count": len(items), "state": state}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/repos/{owner}/{repo}/prs/{pr_id}")
async def pr_summary(owner: str, repo: str, pr_id: int):
    try:
        return await get_pr_summary(owner, repo, pr_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# ReAct PR review — streaming Thought / Action / Observation events
# ---------------------------------------------------------------------------

class ReviewRequest(BaseModel):
    owner: str
    repo: str
    pr_id: int
    post: bool = False
    max_rounds: Optional[int] = None


@app.post("/api/review/stream")
async def review_stream(req: ReviewRequest):
    """SSE stream of ReAct steps. Each event is a JSON object with `type` field."""

    async def event_gen():
        max_rounds = req.max_rounds or CONFIG.max_rounds
        repo_full = f"{req.owner}/{req.repo}"

        yield _sse("status", {"message": f"Starting ReAct review for {repo_full} PR #{req.pr_id}"})

        mcp_client = get_mcp_client()
        await mcp_client.discover_tools()
        yield _sse("status", {"message": f"MCP discovered {len(mcp_client.tools)} tools"})

        try:
            agent = ReActAgent(mcp_client, model=CONFIG.gemini_model)
        except ValueError as exc:
            yield _sse("error", {"message": str(exc)})
            return

        user_message = PR_REVIEW_USER_TEMPLATE.format(
            pr_id=req.pr_id, repo_owner=req.owner, repo_name=req.repo
        )

        # Run agent in a worker task so we can emit progress (this implementation
        # emits a final 'steps' event; the agent itself prints to stdout in real time).
        try:
            result = await agent.run(
                system_prompt=PR_REVIEW_SYSTEM_PROMPT,
                user_message=user_message,
                tool_filter=CONFIG.tool_allowlist,
                max_rounds=max_rounds,
                verbose=True,
            )
        except Exception as exc:
            yield _sse("error", {"message": f"Agent failed: {exc}"})
            return

        for step in result.get("steps", []):
            yield _sse(
                "step",
                {
                    "round": step.round_num,
                    "thought": step.thought,
                    "action": step.action,
                    "action_input": step.action_input,
                    "observation": step.observation,
                },
            )
            await asyncio.sleep(0)

        parsed = parse_json_from_text(result.get("text", ""))
        review = {
            "success": result.get("success", False),
            "repo": repo_full,
            "pr_id": req.pr_id,
            "comments": (parsed or {}).get("comments", []),
            "summary": (parsed or {}).get("summary", {}),
            "tool_calls_made": result.get("tool_calls_made", []),
            "raw_response": result.get("text", ""),
            "error": result.get("error"),
        }
        yield _sse("review", review)

        if req.post:
            yield _sse("status", {"message": "Posting review to GitHub..."})
            try:
                pr_agent = get_review_agent()
                post_result = await pr_agent.post_review(
                    repo=repo_full,
                    pr_id=req.pr_id,
                    review={"comments": review["comments"]},
                    verbose=True,
                )
                yield _sse("posted", post_result)
            except Exception as exc:
                yield _sse("error", {"message": f"Post failed: {exc}"})

        yield _sse("done", {"ok": True})

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@app.post("/api/review")
async def review_sync(req: ReviewRequest):
    """Non-streaming review — returns the full result once complete."""
    try:
        agent = get_review_agent()
        result = await agent.review(
            repo=f"{req.owner}/{req.repo}",
            pr_id=req.pr_id,
            verbose=False,
            max_rounds=req.max_rounds or CONFIG.max_rounds,
        )
        if req.post and result.get("comments") is not None:
            post = await agent.post_review(
                repo=f"{req.owner}/{req.repo}",
                pr_id=req.pr_id,
                review=result.get("review") or {"comments": result["comments"]},
                verbose=False,
            )
            result["posted"] = post
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# MCP tools / config
# ---------------------------------------------------------------------------

@app.get("/api/mcp/tools")
async def list_mcp_tools():
    client = get_mcp_client()
    if not client.tools:
        await client.discover_tools()
    return {
        "count": len(client.tools),
        "allowlist": CONFIG.tool_allowlist,
        "tools": [
            {
                "name": t["name"],
                "description": t.get("description", ""),
                "input_schema": t.get("inputSchema", {}),
                "enabled": t["name"] in CONFIG.tool_allowlist,
            }
            for t in client.tools
        ],
    }


class ConfigUpdate(BaseModel):
    mcp_server_url: Optional[str] = None
    gemini_model: Optional[str] = None
    max_rounds: Optional[int] = None
    tool_allowlist: Optional[List[str]] = None


@app.get("/api/mcp/config")
async def get_config():
    return CONFIG.to_dict()


@app.post("/api/mcp/config")
async def update_config(update: ConfigUpdate):
    if update.mcp_server_url is not None:
        CONFIG.mcp_server_url = update.mcp_server_url.strip()
    if update.gemini_model is not None:
        CONFIG.gemini_model = update.gemini_model.strip()
    if update.max_rounds is not None and update.max_rounds > 0:
        CONFIG.max_rounds = update.max_rounds
    if update.tool_allowlist is not None:
        CONFIG.tool_allowlist = list(update.tool_allowlist)
    return CONFIG.to_dict()


class ToolTestRequest(BaseModel):
    arguments: dict = {}


@app.post("/api/mcp/tools/{tool_name}/test")
async def test_tool(tool_name: str, req: ToolTestRequest):
    client = get_mcp_client()
    result = await client.call_tool(tool_name, req.arguments)
    return result


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------

def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("REACT_BACKEND_PORT", "8090"))
    uvicorn.run("backend:app", host="0.0.0.0", port=port, reload=False)
