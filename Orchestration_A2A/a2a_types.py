"""Minimal A2A protocol shapes used by this local agent mesh.

The public A2A pattern is:
1. discover an Agent Card,
2. send a task/message to the agent endpoint,
3. receive task status and artifacts.

This module keeps the wire format intentionally small and JSON-serializable so
the orchestrator can pass the same shared PR state between independent agents.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


TaskStatus = Literal["submitted", "working", "completed", "failed"]


@dataclass(frozen=True)
class AgentSkill:
    id: str
    name: str
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
        }


@dataclass(frozen=True)
class AgentCard:
    name: str
    description: str
    url: str
    version: str
    skills: list[AgentSkill]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "url": self.url,
            "version": self.version,
            "protocolVersion": "a2a-jsonrpc-minimal/0.1",
            "capabilities": {
                "streaming": False,
                "stateTransition": True,
            },
            "skills": [skill.to_dict() for skill in self.skills],
        }


def state_part(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "data",
        "mimeType": "application/vnd.agentic.pr-state+json",
        "data": state,
    }


def text_part(text: str) -> dict[str, Any]:
    return {
        "kind": "text",
        "text": text,
    }


def task_artifact(name: str, parts: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "name": name,
        "parts": parts,
    }


def build_task(
    *,
    task_id: str,
    status: TaskStatus,
    artifact_name: str | None = None,
    state: dict[str, Any] | None = None,
    message: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Build an A2A Task object for any lifecycle state.

    ``submitted``/``working`` tasks carry no result artifacts yet; ``completed``
    tasks carry the updated PR state; ``failed`` tasks carry an error message on
    the status. This is the single shape returned by both ``message/send`` and
    ``tasks/get`` so the client can poll a task to completion.
    """
    task: dict[str, Any] = {
        "id": task_id,
        "status": {"state": status},
        "artifacts": [],
    }

    if state is not None:
        parts: list[dict[str, Any]] = []
        if message:
            parts.append(text_part(message))
        parts.append(state_part(state))
        task["artifacts"] = [task_artifact(artifact_name or "result", parts)]

    if error:
        task["status"]["message"] = {"role": "agent", "parts": [text_part(error)]}
    return task


def is_terminal(task: dict[str, Any]) -> bool:
    return (task.get("status") or {}).get("state") in {"completed", "failed"}


def task_error_text(task: dict[str, Any]) -> str:
    status = task.get("status") or {}
    message = status.get("message") or {}
    for part in message.get("parts") or []:
        if part.get("kind") == "text" and part.get("text"):
            return str(part["text"])
    return f"task ended in state '{status.get('state')}'"


def extract_state_from_message(message: dict[str, Any]) -> dict[str, Any]:
    for part in message.get("parts") or []:
        if part.get("kind") == "data" and isinstance(part.get("data"), dict):
            return part["data"]
    raise ValueError("A2A message is missing a PR state data part")


def extract_state_from_task(task: dict[str, Any]) -> dict[str, Any]:
    for artifact in task.get("artifacts") or []:
        for part in artifact.get("parts") or []:
            if part.get("kind") == "data" and isinstance(part.get("data"), dict):
                return part["data"]
    raise ValueError("A2A task response is missing a PR state data part")
