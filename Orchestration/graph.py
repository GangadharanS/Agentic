"""LangGraph wiring for the Supervisor / Orchestrator pattern.

       ┌─────────┐
       │  START  │
       └────┬────┘
            ▼
       ┌────────┐   (runs once: resolves head/base/fork, prepares ai-fixes/ branch)
       │  init  │
       └────┬───┘
            ▼
       ┌──────────┐
       │ Reviewer │◄──────────────────────────────────┐
       └────┬─────┘                                   │
            │ route_after_reviewer                    │
            │                                         │
        fix │   push_clean/push_no_fixable/push_max   │
            ▼                                         │
       ┌──────────┐                                   │
       │  Fixer   │                                   │
       └────┬─────┘                                   │
            ▼                                         │
       ┌──────────┐                                   │
       │  Tester  │ ──tests_pass / tests_skip─────────┘
       └────┬─────┘
            │ tests_fail (iter < max) ──► Fixer (loop with CI-derived comments)
            │ tests_fail_max_iter     ──► Pusher
            ▼
       ┌──────────┐
       │  Pusher  │ → summary review + (fork-mode) stacked PR
       └────┬─────┘
            ▼
           END
"""
from __future__ import annotations

from typing import Optional

from langgraph.graph import END, START, StateGraph

from agents.fixer_agent import fixer_node
from agents.init_agent import init_node
from agents.pusher_agent import pusher_node
from agents.reviewer_agent import reviewer_node, route_after_reviewer
from agents.tester_agent import tester_node
from state import OrchestrationState


def route_after_tester(state: OrchestrationState) -> str:
    """tests_pass/tests_skip → reviewer; tests_fail → fixer (or pusher if maxed)."""
    action = state.get("next_action") or "tests_skip"
    if action == "tests_fail":
        if state.get("iteration", 0) >= state.get("max_iterations", 5):
            return "tests_fail_max_iter"
        return "tests_fail"
    return action


def build_graph(checkpointer: Optional[object] = None):
    workflow = StateGraph(OrchestrationState)

    workflow.add_node("init", init_node)
    workflow.add_node("reviewer", reviewer_node)
    workflow.add_node("fixer", fixer_node)
    workflow.add_node("tester", tester_node)
    workflow.add_node("pusher", pusher_node)

    workflow.add_edge(START, "init")
    workflow.add_edge("init", "reviewer")

    workflow.add_conditional_edges(
        "reviewer",
        route_after_reviewer,
        {
            "fix": "fixer",
            "push_clean": "pusher",
            "push_no_fixable": "pusher",
            "push_max_iter": "pusher",
        },
    )

    workflow.add_edge("fixer", "tester")

    workflow.add_conditional_edges(
        "tester",
        route_after_tester,
        {
            "tests_pass": "reviewer",
            "tests_skip": "reviewer",
            "tests_fail": "fixer",
            "tests_fail_max_iter": "pusher",
        },
    )

    workflow.add_edge("pusher", END)

    return workflow.compile(checkpointer=checkpointer)
