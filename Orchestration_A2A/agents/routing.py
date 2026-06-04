"""Per-agent next-hop routing for the A2A mesh.

In a strict A2A pattern the supervisor does not own the workflow graph. Each
agent, after producing its result, decides which agent (if any) should run
next based on its own local outcome, and advertises that as ``next_agent`` in
the task it returns. The supervisor simply follows ``next_agent`` until an
agent returns ``END`` (``None``).

Each function below encodes only the knowledge a single agent has about what
should happen immediately after it runs:

    init      -> reviewer            (or pusher if init failed fatally)
    reviewer  --(fix)-------> fixer
    reviewer  --(push_*)----> pusher
    fixer     --(ok)--------> tester (or pusher if the fix step failed/maxed out)
    tester    --(pass/skip)-> reviewer
    tester    --(fail, iter<max)--> fixer
    tester    --(fail, iter>=max)-> pusher
    pusher    -> END
"""
from __future__ import annotations

from typing import Any, Callable

from state import END, PUSH_ACTIONS


def _after_init(state: dict[str, Any]) -> str | None:
    if state.get("error") and state.get("next_action") in PUSH_ACTIONS:
        return "pusher"
    return "reviewer"


def _after_reviewer(state: dict[str, Any]) -> str | None:
    if state.get("next_action") == "fix":
        return "fixer"
    # push_clean / push_no_fixable / push_max_iter
    return "pusher"


def _after_fixer(state: dict[str, Any]) -> str | None:
    if state.get("next_action") in PUSH_ACTIONS:
        return "pusher"
    return "tester"


def _after_tester(state: dict[str, Any]) -> str | None:
    action = state.get("next_action")
    if action in {"tests_pass", "tests_skip"}:
        return "reviewer"
    if action == "tests_fail":
        if state.get("iteration", 0) >= state.get("max_iterations", 5):
            return "pusher"
        return "fixer"
    # Defensive default: re-review on any unexpected tester outcome.
    return "reviewer"


def _after_pusher(_state: dict[str, Any]) -> str | None:
    return END


ROUTES: dict[str, Callable[[dict[str, Any]], "str | None"]] = {
    "init": _after_init,
    "reviewer": _after_reviewer,
    "fixer": _after_fixer,
    "tester": _after_tester,
    "pusher": _after_pusher,
}


def decide_next_agent(agent_key: str, state: dict[str, Any]) -> str | None:
    """Return the next agent key this agent advertises, or END (None)."""
    route = ROUTES.get(agent_key)
    if route is None:
        return END
    return route(state)
