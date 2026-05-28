"""High-level GitHub PR orchestration via LangGraph multi-agent workflow.

Parallel to ReAct/PRReviewAgent — that class runs a single ReAct review;
PROrchestrationAgent runs the full init → review → fix → test → push loop.
"""
from __future__ import annotations

import contextlib
import os
import sys
from typing import Any, AsyncIterator

from graph import build_graph
from state import OrchestrationState


class PROrchestrationAgent:
    """LangGraph orchestrator: review, auto-fix, CI test, re-review, and push summary."""

    def __init__(
        self,
        *,
        checkpoint_db: str | None = None,
        use_checkpoint: bool = True,
        recursion_limit: int = 80,
    ):
        self.checkpoint_db = checkpoint_db or os.getenv(
            "ORCH_CHECKPOINT_DB", ".orchestration_state.db"
        )
        self.use_checkpoint = use_checkpoint
        self.recursion_limit = recursion_limit

    @staticmethod
    def default_thread_id(pr_number: int | str) -> str:
        return f"pr-{pr_number}"

    @staticmethod
    def _parse_repo(repo: str) -> tuple[str, str]:
        owner, _, name = repo.strip().partition("/")
        if not owner or not name:
            raise ValueError(f"Invalid repo '{repo}'. Use owner/repo-name.")
        return owner, name

    @contextlib.asynccontextmanager
    async def _checkpointer(self) -> AsyncIterator[Any]:
        if not self.use_checkpoint:
            from langgraph.checkpoint.memory import MemorySaver
            yield MemorySaver()
            return
        try:
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        except ImportError:
            print(
                "[warn] langgraph-checkpoint-sqlite not installed — falling back to MemorySaver",
                file=sys.stderr,
            )
            from langgraph.checkpoint.memory import MemorySaver
            yield MemorySaver()
            return

        async with AsyncSqliteSaver.from_conn_string(self.checkpoint_db) as saver:
            print(f"[checkpoint] using SQLite at {self.checkpoint_db}")
            yield saver

    def _run_config(self, thread_id: str) -> dict:
        return {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": self.recursion_limit,
        }

    def _initial_state(
        self,
        *,
        owner: str,
        name: str,
        pr_number: int,
        max_iter: int,
        severities: list[str],
        enable_tester: bool,
        tester_timeout_s: int,
    ) -> OrchestrationState:
        return {
            "repo_owner": owner,
            "repo_name": name,
            "pr_number": pr_number,
            "iteration": 0,
            "max_iterations": max_iter,
            "fix_severities": severities,
            "enable_tester": enable_tester,
            "tester_timeout_s": tester_timeout_s,
            "init_done": False,
        }

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
    ) -> dict:
        """Start a fresh orchestration run for a PR."""
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

        initial = self._initial_state(
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
                f"[PROrchestrationAgent] starting {repo}#{pr_num} thread={tid} "
                f"max_iter={max_iterations} tester={'on' if enable_tester else 'off'} "
                f"severities={fix_severities}\n"
            )

        async with self._checkpointer() as checkpointer:
            graph = build_graph(checkpointer=checkpointer)
            final = await graph.ainvoke(initial, config=self._run_config(tid))

        return self._result(repo=repo, pr_id=str(pr_num), thread_id=tid, final=final)

    async def resume(
        self,
        repo: str,
        pr_id: int | str,
        *,
        thread_id: str | None = None,
        verbose: bool = True,
    ) -> dict:
        """Resume from the latest SQLite checkpoint for thread_id (default pr-<num>)."""
        self._parse_repo(repo)  # validate format; state comes from checkpoint
        pr_num = int(pr_id)
        tid = thread_id or self.default_thread_id(pr_num)

        if verbose:
            print(f"[PROrchestrationAgent] resuming thread '{tid}'…")

        async with self._checkpointer() as checkpointer:
            graph = build_graph(checkpointer=checkpointer)
            final = await graph.ainvoke(None, config=self._run_config(tid))

        return self._result(repo=repo, pr_id=str(pr_num), thread_id=tid, final=final)

    @staticmethod
    def _result(*, repo: str, pr_id: str, thread_id: str, final: dict) -> dict:
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
