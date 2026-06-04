"""Async A2A JSON-RPC client used by the supervisor orchestrator.

Implements the strict A2A request/poll loop:

1. ``message/send`` submits the PR state and returns a (usually non-terminal)
   task.
2. ``tasks/get`` is polled until the task reaches ``completed`` or ``failed``.
"""
from __future__ import annotations

import asyncio
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from a2a_types import (
    extract_state_from_task,
    is_terminal,
    state_part,
    task_error_text,
    text_part,
)


@dataclass
class RemoteAgent:
    key: str
    base_url: str
    card: dict[str, Any]

    @property
    def endpoint(self) -> str:
        return f"{self.base_url.rstrip('/')}/a2a"


class A2AClient:
    def __init__(
        self,
        *,
        request_timeout_s: float = 30.0,
        task_timeout_s: float = 900.0,
        poll_interval_s: float | None = None,
    ):
        # Per-HTTP-request timeout (short: each call is send-or-poll).
        self.request_timeout_s = request_timeout_s
        # Total time to wait for a single task to reach a terminal state.
        self.task_timeout_s = task_timeout_s
        self.poll_interval_s = (
            poll_interval_s
            if poll_interval_s is not None
            else float(os.getenv("A2A_POLL_INTERVAL_S", "2.0"))
        )

    async def discover(self, key: str, base_url: str) -> RemoteAgent:
        url = f"{base_url.rstrip('/')}/.well-known/agent-card.json"
        async with httpx.AsyncClient(timeout=self.request_timeout_s) as client:
            response = await client.get(url)
            response.raise_for_status()
            card = response.json()
        return RemoteAgent(key=key, base_url=base_url, card=card)

    async def _rpc(self, agent: RemoteAgent, method: str, params: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": method,
            "params": params,
        }
        async with httpx.AsyncClient(timeout=self.request_timeout_s) as client:
            response = await client.post(agent.endpoint, json=payload)
            response.raise_for_status()
            body = response.json()
        if "error" in body:
            raise RuntimeError(f"A2A RPC error from {agent.key} ({method}): {body['error']}")
        return body.get("result") or {}

    async def send_state(
        self,
        agent: RemoteAgent,
        state: dict[str, Any],
        *,
        task_id: str | None = None,
        message: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        tid = task_id or str(uuid.uuid4())
        task = await self._rpc(
            agent,
            "message/send",
            {
                "id": tid,
                "message": {
                    "role": "user",
                    "parts": [
                        text_part(message or f"Run {agent.key} on the attached PR state."),
                        state_part(state),
                    ],
                },
            },
        )

        task = await self._poll(agent, task)

        if (task.get("status") or {}).get("state") == "failed":
            raise RuntimeError(f"A2A task failed from {agent.key}: {task_error_text(task)}")

        return extract_state_from_task(task), task

    async def _poll(self, agent: RemoteAgent, task: dict[str, Any]) -> dict[str, Any]:
        task_id = task.get("id")
        deadline = time.monotonic() + self.task_timeout_s
        while not is_terminal(task):
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"A2A task {task_id} on {agent.key} did not finish within "
                    f"{self.task_timeout_s}s"
                )
            await asyncio.sleep(self.poll_interval_s)
            task = await self._rpc(agent, "tasks/get", {"id": task_id})
        return task
