"""Agent Cards for the five PR-orchestration A2A agents."""
from __future__ import annotations

import os

from a2a_types import AgentCard, AgentSkill


DEFAULT_PORTS = {
    "init": 9101,
    "reviewer": 9102,
    "fixer": 9103,
    "tester": 9104,
    "pusher": 9105,
}


def agent_url(agent_key: str) -> str:
    env_name = f"A2A_{agent_key.upper()}_URL"
    return os.getenv(env_name, f"http://127.0.0.1:{DEFAULT_PORTS[agent_key]}")


def make_card(agent_key: str) -> AgentCard:
    cards = {
        "init": AgentCard(
            name="pr-init-agent",
            description="Resolves PR metadata, fork strategy, and prepares an ai-fixes branch when needed.",
            url=agent_url("init"),
            version="0.1.0",
            skills=[
                AgentSkill(
                    id="resolve-pr-context",
                    name="Resolve PR context",
                    description="Fetch PR metadata through GitHub MCP and update shared orchestration state.",
                )
            ],
        ),
        "reviewer": AgentCard(
            name="pr-reviewer-agent",
            description="Runs the ReAct PR reviewer over GitHub MCP tools and decides whether fixes are needed.",
            url=agent_url("reviewer"),
            version="0.1.0",
            skills=[
                AgentSkill(
                    id="review-pr",
                    name="Review PR",
                    description="Find blocking/major/minor logic issues and choose the next supervisor action.",
                )
            ],
        ),
        "fixer": AgentCard(
            name="pr-fixer-agent",
            description="Applies LLM-generated file fixes through GitHub MCP commits.",
            url=agent_url("fixer"),
            version="0.1.0",
            skills=[
                AgentSkill(
                    id="apply-fixes",
                    name="Apply fixes",
                    description="Read changed files, rewrite fixable files with Gemini, and commit updates.",
                )
            ],
        ),
        "tester": AgentCard(
            name="pr-tester-agent",
            description="Polls GitHub checks through MCP and routes failures back to the fixer.",
            url=agent_url("tester"),
            version="0.1.0",
            skills=[
                AgentSkill(
                    id="watch-ci",
                    name="Watch CI",
                    description="Poll check runs and create synthetic review comments for failing checks.",
                )
            ],
        ),
        "pusher": AgentCard(
            name="pr-pusher-agent",
            description="Posts the final summary review and opens a stacked PR for fork-mode fixes.",
            url=agent_url("pusher"),
            version="0.1.0",
            skills=[
                AgentSkill(
                    id="publish-result",
                    name="Publish result",
                    description="Create a GitHub review comment and optional stacked pull request.",
                )
            ],
        ),
    }
    return cards[agent_key]
