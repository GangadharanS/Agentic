"""A2A supervisor client for the PR review/fix/test/push workflow.

Strict A2A pattern: the supervisor owns **no** workflow graph. It is a generic
task driver. Each agent, after running, advertises which agent should run next
via ``state["next_agent"]`` (see ``agents/routing.py``). The supervisor simply:

    1. starts the workflow at ``init`` (or the resumed ``next_agent``),
    2. sends the shared state to the current agent and polls its task to
       completion,
    3. follows the ``next_agent`` the agent returned,
    4. stops when an agent returns END (``None``).

The resulting routing (init -> reviewer -> fixer <-> tester loop -> pusher) is
an emergent property of the agents' local decisions, not hardcoded here.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from a2a_client import A2AClient, RemoteAgent
from agent_cards import agent_url
from state import AGENT_KEYS
from state_utils import initial_state


class A2AOrchestrator:
    """Supervisor that communicates with the five PR agents via A2A JSON-RPC."""

    def __init__(
        self,
        *,
        checkpoint_dir: str | None = None,
        use_checkpoint: bool = True,
        timeout_s: float = 900.0,
    ):
        self.checkpoint_dir = Path(
            checkpoint_dir or os.getenv("A2A_CHECKPOINT_DIR", ".a2a_checkpoints")
        )
        self.use_checkpoint = use_checkpoint
        self.client = A2AClient(task_timeout_s=timeout_s)
        self.agents: dict[str, RemoteAgent] = {}

    @staticmethod
    def default_thread_id(pr_number: int | str) -> str:
        return f"pr-{pr_number}"

    @staticmethod
    def _parse_repo(repo: str) -> tuple[str, str]:
        owner, _, name = repo.strip().partition("/")
        if not owner or not name:
            raise ValueError(f"Invalid repo '{repo}'. Use owner/repo-name.")
        return owner, name

    def _checkpoint_path(self, thread_id: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in thread_id)
        return self.checkpoint_dir / f"{safe}.json"

    def _save_checkpoint(self, thread_id: str, state: dict[str, Any]) -> None:
        if not self.use_checkpoint:
            return
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self._checkpoint_path(thread_id).write_text(json.dumps(state, indent=2), encoding="utf-8")

    def _load_checkpoint(self, thread_id: str) -> dict[str, Any]:
        path = self._checkpoint_path(thread_id)
        if not path.exists():
            raise ValueError(f"No A2A checkpoint found for thread '{thread_id}' at {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    async def discover_agents(self, *, verbose: bool = True) -> None:
        for key in AGENT_KEYS:
            remote = await self.client.discover(key, agent_url(key))
            self.agents[key] = remote
            if verbose:
                print(f"[A2A discover] {key:8s} → {remote.card.get('name')} @ {remote.base_url}")

    async def _call(
        self,
        key: str,
        state: dict[str, Any],
        *,
        thread_id: str,
        verbose: bool,
    ) -> dict[str, Any]:
        if key not in self.agents:
            await self.discover_agents(verbose=verbose)
        if verbose:
            print(f"[A2A] → {key} (iter={state.get('iteration', 0)}, action={state.get('next_action')})")
        updated, _task = await self.client.send_state(
            self.agents[key],
            state,
            task_id=f"{thread_id}:{key}:{len(state.get('a2a_events') or [])}",
            message=f"Run {key} step for PR {state.get('repo_owner')}/{state.get('repo_name')}#{state.get('pr_number')}",
        )
        self._save_checkpoint(thread_id, updated)
        if verbose:
            print(
                f"[A2A] ← {key} (iter={updated.get('iteration', 0)}, "
                f"action={updated.get('next_action')}, next={updated.get('next_agent')})"
            )
        return updated

    async def run(
        self,
        repo: str,
        pr_id: int | str,
        *,
        max_iter: int | None = None,
        severities: list[str] | None = None,
        enable_tester: bool = True,
        tester_timeout_s: int | None = None,
        thread_id: str | None = None,
        verbose: bool = True,
    ) -> dict[str, Any]:
        owner, name = self._parse_repo(repo)
        pr_num = int(pr_id)
        tid = thread_id or self.default_thread_id(pr_num)
        max_iterations = max_iter if max_iter is not None else int(
            os.getenv("ORCH_MAX_ITERATIONS", "5")
        )
        fix_severities = severities or [
            s.strip()
            for s in os.getenv("ORCH_FIX_SEVERITIES", "blocking,major").split(",")
            if s.strip()
        ]
        timeout = tester_timeout_s if tester_timeout_s is not None else int(
            os.getenv("ORCH_TESTER_TIMEOUT", "600")
        )

        state = initial_state(
            owner=owner,
            name=name,
            pr_number=pr_num,
            max_iter=max_iterations,
            severities=fix_severities,
            enable_tester=enable_tester,
            tester_timeout_s=timeout,
        )

        if verbose:
            print(
                f"[A2AOrchestrator] starting {repo}#{pr_num} thread={tid} "
                f"max_iter={max_iterations} tester={'on' if enable_tester else 'off'} "
                f"severities={fix_severities}\n"
            )

        await self.discover_agents(verbose=verbose)
        final = await self._run_from_state(state, thread_id=tid, verbose=verbose)
        return self._result(repo=repo, pr_id=str(pr_num), thread_id=tid, final=final)

    async def resume(
        self,
        repo: str,
        pr_id: int | str,
        *,
        thread_id: str | None = None,
        verbose: bool = True,
    ) -> dict[str, Any]:
        self._parse_repo(repo)
        pr_num = int(pr_id)
        tid = thread_id or self.default_thread_id(pr_num)
        state = self._load_checkpoint(tid)
        if verbose:
            print(f"[A2AOrchestrator] resuming thread '{tid}'…")
        await self.discover_agents(verbose=verbose)
        final = await self._run_from_state(state, thread_id=tid, verbose=verbose)
        return self._result(repo=repo, pr_id=str(pr_num), thread_id=tid, final=final)

    @staticmethod
    def _entry_agent(state: dict[str, Any]) -> str:
        """Pick where to (re)start: a resumed next_agent, else init/reviewer."""
        nxt = state.get("next_agent")
        if nxt in AGENT_KEYS:
            return nxt
        if not state.get("init_done"):
            return "init"
        # Resuming a checkpoint that predates routing: re-review.
        return "reviewer"

    def _max_steps(self, state: dict[str, Any]) -> int:
        # Safety bound so a misbehaving routing decision can't loop forever.
        # Each fix iteration costs at most reviewer+fixer+tester (3 hops).
        return state.get("max_iterations", 5) * 3 + len(AGENT_KEYS) + 5

    async def _run_from_state(
        self,
        state: dict[str, Any],
        *,
        thread_id: str,
        verbose: bool,
    ) -> dict[str, Any]:
        """Generic A2A driver: keep calling the agent each agent points to.

        There is no workflow graph here; the next agent is whatever the agent
        that just ran advertised in ``state["next_agent"]``.
        """
        current = self._entry_agent(state)
        budget = self._max_steps(state)

        while current is not None:
            if current not in self.agents:
                state["error"] = f"Routed to unknown agent: {current!r}"
                break

            state = await self._call(current, state, thread_id=thread_id, verbose=verbose)

            budget -= 1
            if budget <= 0:
                state["error"] = "A2A step budget exhausted (possible routing loop)"
                state.setdefault("next_action", "push_max_iter")
                break

            current = state.get("next_agent")

        return state

    @staticmethod
    def _result(*, repo: str, pr_id: str, thread_id: str, final: dict[str, Any]) -> dict[str, Any]:
        error = final.get("error")
        return {
            "success": not bool(error),
            "repo": repo,
            "pr_id": pr_id,
            "thread_id": thread_id,
            "iteration": final.get("iteration", 0),
            "next_action": final.get("next_action"),
            "is_fork": final.get("is_fork"),
            "summary_review_url": final.get("summary_review_url"),
            "stacked_pr_url": final.get("stacked_pr_url"),
            "state": final,
            "error": error,
        }
