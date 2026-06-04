"""CLI entry: run the ADK PR orchestrator on a GitHub PR.

Examples:
    python main.py --repo owner/repo --pr 42
    python main.py --repo owner/repo --pr 42 --max-iter 3 --severities blocking
    python main.py --repo owner/repo --pr 42 --no-tester

Mirrors Orchestration/main.py but drives a Google ADK Runner instead of a
LangGraph graph. PR target + config are seeded into the ADK session state; the
custom PROrchestrator agent reads/updates that state as it runs.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from agents.orchestrator import build_orchestrator
from state import initial_state

APP_NAME = "orchestration_adk"
USER_ID = "orchestrator"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Multi-agent PR orchestrator (Google ADK)")
    p.add_argument("--repo", required=True, help="owner/repo (the BASE repo where the PR lives)")
    p.add_argument("--pr", required=True, type=int, help="PR number")
    p.add_argument("--max-iter", type=int, default=int(os.getenv("ORCH_MAX_ITERATIONS", "5")),
                   help="Max review-fix iterations (default 5)")
    p.add_argument("--severities", default=os.getenv("ORCH_FIX_SEVERITIES", "blocking,major"),
                   help="Comma-separated severities the Fixer will address")
    p.add_argument("--no-tester", action="store_true", help="Disable the CI Tester node")
    p.add_argument("--tester-timeout", type=int, default=int(os.getenv("ORCH_TESTER_TIMEOUT", "600")),
                   help="Seconds to wait for CI checks (default 600)")
    p.add_argument("--quiet", action="store_true", help="Less console output")
    return p.parse_args()


def _parse_repo(repo: str) -> tuple[str, str]:
    owner, _, name = repo.strip().partition("/")
    if not owner or not name:
        raise ValueError(f"Invalid repo '{repo}'. Use owner/repo-name.")
    return owner, name


def _print_result(repo: str, pr: int, final_state: dict) -> None:
    print("\n========== Orchestration result (ADK) ==========")
    print(f"Repo:          {repo}")
    print(f"PR:            #{pr}")
    print(f"Iterations:    {final_state.get('iteration', 0)}")
    print(f"Final action:  {final_state.get('next_action')}")
    print(f"Fork mode:     {final_state.get('is_fork')}")
    if final_state.get("summary_review_url"):
        print(f"Summary URL:   {final_state['summary_review_url']}")
    if final_state.get("stacked_pr_url"):
        print(f"Stacked PR:    {final_state['stacked_pr_url']}")
    if final_state.get("error"):
        print(f"Error:         {final_state['error']}")


async def _run(args: argparse.Namespace) -> int:
    owner, name = _parse_repo(args.repo)
    pr_num = int(args.pr)
    severities = [s.strip() for s in args.severities.split(",") if s.strip()]
    verbose = not args.quiet

    seed = initial_state(
        owner=owner,
        name=name,
        pr_number=pr_num,
        max_iter=args.max_iter,
        severities=severities,
        enable_tester=not args.no_tester,
        tester_timeout_s=args.tester_timeout,
    )

    if verbose:
        print(
            f"[ADK Orchestrator] starting {args.repo}#{pr_num} "
            f"max_iter={args.max_iter} tester={'on' if not args.no_tester else 'off'} "
            f"severities={severities}"
        )
        print(f"[ADK Orchestrator] MCP={os.getenv('MCP_SERVER_URL', '(unset)')}\n")

    session_service = InMemorySessionService()
    root_agent = build_orchestrator()
    runner = Runner(agent=root_agent, app_name=APP_NAME, session_service=session_service)

    session_id = f"pr-{pr_num}-{uuid.uuid4().hex[:6]}"
    await session_service.create_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        session_id=session_id,
        state=seed,
    )

    kickoff = types.Content(
        role="user",
        parts=[types.Part(text=f"Orchestrate review of {args.repo} PR #{pr_num}.")],
    )

    async for event in runner.run_async(user_id=USER_ID, session_id=session_id, new_message=kickoff):
        if verbose and event.content and event.content.parts:
            for part in event.content.parts:
                if getattr(part, "text", None):
                    print(part.text)

    final_session = await session_service.get_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session_id
    )
    final_state = dict(final_session.state) if final_session else {}

    if verbose:
        _print_result(args.repo, pr_num, final_state)
    return 0 if not final_state.get("error") else 1


def main() -> None:
    try:
        sys.exit(asyncio.run(_run(_parse_args())))
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
