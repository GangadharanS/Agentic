"""PROrchestrator — custom ADK BaseAgent reproducing the LangGraph routing.

LangGraph used a StateGraph with conditional edges. ADK's deterministic
workflow primitives (SequentialAgent / LoopAgent) cannot express the exact
branching here (reviewer can skip straight to push; tester loops back to fixer
OR re-reviews), so we use a **custom BaseAgent** — the documented ADK pattern
for arbitrary control flow — and drive sub-agents directly.

Equivalent graph:

    init -> reviewer
    reviewer --(fix)--------> fixer -> tester
    reviewer --(push_*)-----> pusher
    tester  --(tests_pass/skip)--> reviewer
    tester  --(tests_fail, iter<max)--> fixer
    tester  --(tests_fail, iter>=max)--> pusher
    pusher  -> END

The fixer->tester cycle (re-run fixer with synthetic <ci> comments until CI
passes or the iteration budget is exhausted) is conceptually an ADK LoopAgent;
we inline it here so the surrounding reviewer loop and early-exit branches stay
explicit and easy to follow.
"""
from __future__ import annotations

from typing import AsyncGenerator

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event

from state import (
    ACTION_FIX,
    ACTION_TESTS_FAIL,
    ACTION_TESTS_PASS,
    ACTION_TESTS_SKIP,
    PUSH_ACTIONS,
)

from .fixer_agent import FixerAgent
from .init_agent import InitAgent
from .pusher_agent import PusherAgent
from .reviewer_agent import ReviewerAgent
from .tester_agent import TesterAgent
from ._mcp_parse import log_event


class PROrchestrator(BaseAgent):
    """Supervisor agent: init -> review -> (fix <-> test) loop -> push."""

    init_agent: InitAgent
    reviewer: ReviewerAgent
    fixer: FixerAgent
    tester: TesterAgent
    pusher: PusherAgent

    model_config = {"arbitrary_types_allowed": True}

    def __init__(
        self,
        *,
        name: str,
        init_agent: InitAgent,
        reviewer: ReviewerAgent,
        fixer: FixerAgent,
        tester: TesterAgent,
        pusher: PusherAgent,
    ):
        super().__init__(
            name=name,
            init_agent=init_agent,
            reviewer=reviewer,
            fixer=fixer,
            tester=tester,
            pusher=pusher,
            sub_agents=[init_agent, reviewer, fixer, tester, pusher],
        )

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        state = ctx.session.state

        # --- init (runs once) ---
        async for event in self.init_agent.run_async(ctx):
            yield event

        # If init hard-failed (e.g. PR not found), skip straight to the pusher
        # so we report the error instead of producing a misleading "clean" pass.
        if state.get("error") and state.get("next_action") in PUSH_ACTIONS:
            async for event in self.pusher.run_async(ctx):
                yield event
            return

        # --- first review ---
        async for event in self.reviewer.run_async(ctx):
            yield event

        # --- supervisor loop ---
        while True:
            action = state.get("next_action")

            if action in PUSH_ACTIONS:
                break

            if action != ACTION_FIX:
                # Unexpected action — fail safe to pusher.
                break

            # fix <-> test inner loop (mirrors fixer -> tester -> {fixer|reviewer})
            go_to_pusher = False
            while True:
                async for event in self.fixer.run_async(ctx):
                    yield event

                # A fixer setup error short-circuits to the pusher.
                if state.get("next_action") in PUSH_ACTIONS:
                    go_to_pusher = True
                    break

                async for event in self.tester.run_async(ctx):
                    yield event

                t = state.get("next_action")
                if t in (ACTION_TESTS_PASS, ACTION_TESTS_SKIP):
                    # CI is healthy — re-review for a fresh opinion.
                    async for event in self.reviewer.run_async(ctx):
                        yield event
                    break  # back to the outer supervisor loop
                if t == ACTION_TESTS_FAIL:
                    if state.get("iteration", 0) >= state.get("max_iterations", 5):
                        # Budget exhausted; keep tests_fail label for the pusher.
                        go_to_pusher = True
                        break
                    # Otherwise loop: fixer runs again with the synthetic <ci> comments.
                    continue
                # Any other tester action — re-review and continue.
                async for event in self.reviewer.run_async(ctx):
                    yield event
                break

            if go_to_pusher:
                break

        ev = log_event(self.name, f"[Orchestrator] routing to pusher (final action={state.get('next_action')})")
        if ev:
            yield ev

        # --- pusher (always) ---
        async for event in self.pusher.run_async(ctx):
            yield event


def build_orchestrator(name: str = "pr_orchestrator_adk") -> PROrchestrator:
    return PROrchestrator(
        name=name,
        init_agent=InitAgent(name="init"),
        reviewer=ReviewerAgent(name="reviewer"),
        fixer=FixerAgent(name="fixer"),
        tester=TesterAgent(name="tester"),
        pusher=PusherAgent(name="pusher"),
    )
