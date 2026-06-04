"""FastAPI server adapter for one A2A agent.

This implements a strict A2A task lifecycle:

    submitted -> working -> completed | failed

``message/send`` accepts the PR state, registers a task, kicks off the agent
skill in the background and returns immediately with a non-terminal task
(``submitted``/``working``). The supervisor then polls ``tasks/get`` until the
task reaches ``completed`` or ``failed``. This keeps long-running steps (e.g.
the tester polling CI) within the protocol instead of holding one HTTP request
open for minutes.
"""
from __future__ import annotations

import asyncio
import traceback
import uuid
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from a2a_types import (
    AgentCard,
    build_task,
    extract_state_from_message,
)


StateHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def _rpc_error(rpc_id: Any, code: int, message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}},
        status_code=status_code,
    )


def create_agent_app(
    *,
    card: AgentCard,
    handler: StateHandler,
    artifact_name: str,
) -> FastAPI:
    app = FastAPI(title=card.name, version=card.version)

    # In-memory task store for this agent process: task_id -> task object.
    tasks: dict[str, dict[str, Any]] = {}

    @app.get("/.well-known/agent-card.json")
    async def agent_card() -> dict[str, Any]:
        return card.to_dict()

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "agent": card.name}

    async def _run_task(task_id: str, state: dict[str, Any]) -> None:
        tasks[task_id] = build_task(task_id=task_id, status="working")
        try:
            updated = await handler(state)
            tasks[task_id] = build_task(
                task_id=task_id,
                status="completed",
                artifact_name=artifact_name,
                state=updated,
                message=f"{card.name} completed",
            )
        except Exception as exc:
            error_text = f"{type(exc).__name__}: {exc}"
            print(f"[{card.name}] A2A task {task_id} failed:\n{traceback.format_exc()}")
            tasks[task_id] = build_task(
                task_id=task_id,
                status="failed",
                artifact_name=artifact_name,
                error=error_text,
            )

    @app.post("/a2a")
    async def rpc(request: Request):
        body = await request.json()
        rpc_id = body.get("id")
        method = body.get("method")
        params = body.get("params") or {}

        if method == "message/send":
            task_id = params.get("id") or str(uuid.uuid4())
            try:
                state = extract_state_from_message(params.get("message") or {})
            except ValueError as exc:
                return _rpc_error(rpc_id, -32602, str(exc), status_code=400)

            # Register as submitted, then run the skill in the background. The
            # client receives this non-terminal task and polls tasks/get.
            tasks[task_id] = build_task(task_id=task_id, status="submitted")
            asyncio.create_task(_run_task(task_id, state))
            return {"jsonrpc": "2.0", "id": rpc_id, "result": tasks[task_id]}

        if method == "tasks/get":
            task_id = params.get("id")
            task = tasks.get(task_id)
            if task is None:
                return _rpc_error(rpc_id, -32001, f"Task not found: {task_id}", status_code=404)
            return {"jsonrpc": "2.0", "id": rpc_id, "result": task}

        return _rpc_error(rpc_id, -32601, f"Unsupported method: {method}", status_code=404)

    return app
