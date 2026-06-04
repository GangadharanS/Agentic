"""HTTP entry for Azure Container Apps — wraps PROrchestrationAgent (LangGraph CLI).

The container runs this FastAPI app (long-lived). Trigger a run via POST /api/orchestrate.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

load_dotenv()

from pr_orchestrator import PROrchestrationAgent  # noqa: E402


def _agent() -> PROrchestrationAgent:
    return PROrchestrationAgent(
        checkpoint_db=os.getenv("ORCH_CHECKPOINT_DB", "/data/.orchestration_state.db"),
        use_checkpoint=os.getenv("ORCH_USE_CHECKPOINT", "true").lower() in ("1", "true", "yes"),
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    print("[Orchestration] HTTP server ready")
    yield


app = FastAPI(
    title="PR Orchestration API",
    version="1.0.0",
    description="LangGraph multi-agent PR orchestrator (init → review → fix → test → push).",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class OrchestrateRequest(BaseModel):
    repo: str = Field(..., description="Base repo as owner/name")
    pr: int = Field(..., description="Pull request number")
    max_iter: Optional[int] = None
    severities: Optional[List[str]] = None
    enable_tester: bool = True
    tester_timeout_s: Optional[int] = None
    thread_id: Optional[str] = None
    resume: bool = False


@app.get("/api/health")
async def health():
    gemini_ok = bool(os.getenv("GEMINI_API_KEY", "").strip())
    mcp_url = os.getenv("MCP_SERVER_URL", "http://localhost:8000")
    gh_ok = bool(os.getenv("GITHUB_TOKEN", "").strip())
    return {
        "status": "ok" if (gemini_ok and gh_ok) else "degraded",
        "gemini": {"configured": gemini_ok},
        "github": {"configured": gh_ok},
        "mcp_server_url": mcp_url,
        "checkpoint_db": os.getenv("ORCH_CHECKPOINT_DB", "/data/.orchestration_state.db"),
    }


@app.post("/api/orchestrate")
async def orchestrate(req: OrchestrateRequest):
    """Run (or resume) the full LangGraph orchestration for one PR."""
    agent = _agent()
    severities = req.severities
    if severities is None:
        severities = [
            s.strip()
            for s in os.getenv("ORCH_FIX_SEVERITIES", "blocking,major").split(",")
            if s.strip()
        ]

    try:
        if req.resume:
            result = await agent.resume(
                req.repo,
                req.pr,
                thread_id=req.thread_id,
                verbose=True,
            )
        else:
            result = await agent.run(
                req.repo,
                req.pr,
                max_iter=req.max_iter,
                severities=severities,
                enable_tester=req.enable_tester,
                tester_timeout_s=req.tester_timeout_s,
                thread_id=req.thread_id,
                verbose=True,
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if not result.get("success"):
        raise HTTPException(status_code=422, detail=result)
    return result
