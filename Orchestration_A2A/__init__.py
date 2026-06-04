"""Orchestration_A2A — multi-agent PR review/fix/push using the A2A protocol.

Same five agents as Orchestration/ (init, reviewer, fixer, tester, pusher) but
each runs as an independent **A2A server** (its own Agent Card + JSON-RPC
endpoint). A supervisor `A2AOrchestrator` acts as the **A2A client**, discovering
each agent's card and exchanging the shared PR state via `message/send`.
"""

from orchestrator import A2AOrchestrator

__all__ = ["A2AOrchestrator"]
