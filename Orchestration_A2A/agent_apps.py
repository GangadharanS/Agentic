"""A2A app factories that expose existing agent skills over JSON-RPC."""
from __future__ import annotations

from typing import Awaitable, Callable

from fastapi import FastAPI

from a2a_server import create_agent_app
from agent_cards import make_card
from state_utils import apply_update

from agents.fixer_agent import fixer_node
from agents.init_agent import init_node
from agents.pusher_agent import pusher_node
from agents.reviewer_agent import reviewer_node
from agents.routing import decide_next_agent
from agents.tester_agent import tester_node


Node = Callable[[dict], Awaitable[dict]]


def _handler(agent_key: str, node: Node):
    async def handle(state: dict) -> dict:
        update = await node(state)
        new_state = apply_update(state, update, agent=agent_key)
        # This agent advertises its own next hop; the supervisor just follows it.
        new_state["next_agent"] = decide_next_agent(agent_key, new_state)
        if new_state.get("a2a_events"):
            new_state["a2a_events"][-1]["next_agent"] = new_state["next_agent"]
        return new_state

    return handle


def build_app(agent_key: str) -> FastAPI:
    nodes: dict[str, Node] = {
        "init": init_node,
        "reviewer": reviewer_node,
        "fixer": fixer_node,
        "tester": tester_node,
        "pusher": pusher_node,
    }
    if agent_key not in nodes:
        raise ValueError(f"Unknown A2A agent '{agent_key}'")
    return create_agent_app(
        card=make_card(agent_key),
        handler=_handler(agent_key, nodes[agent_key]),
        artifact_name=f"{agent_key}-state",
    )
