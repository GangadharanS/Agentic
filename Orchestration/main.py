"""CLI entry: run PROrchestrationAgent on a GitHub PR.

Examples:
    python main.py --repo owner/repo --pr 42
    python main.py --repo owner/repo --pr 42 --max-iter 3 --severities blocking
    python main.py --repo owner/repo --pr 42 --no-tester
    python main.py --repo owner/repo --pr 42 --resume
    python main.py --repo owner/repo --pr 42 --no-checkpoint
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from pr_orchestrator import PROrchestrationAgent


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Multi-agent PR orchestrator (PROrchestrationAgent)")
    p.add_argument("--repo", required=True, help="owner/repo (the BASE repo where the PR lives)")
    p.add_argument("--pr", required=True, type=int, help="PR number")
    p.add_argument("--max-iter", type=int,
                   default=int(os.getenv("ORCH_MAX_ITERATIONS", "5")),
                   help="Max review-fix iterations (default 5)")
    p.add_argument("--severities", default=os.getenv("ORCH_FIX_SEVERITIES", "blocking,major"),
                   help="Comma-separated severities the Fixer will address")
    p.add_argument("--no-tester", action="store_true",
                   help="Disable the CI Tester node")
    p.add_argument("--tester-timeout", type=int,
                   default=int(os.getenv("ORCH_TESTER_TIMEOUT", "600")),
                   help="Seconds to wait for CI checks (default 600)")
    p.add_argument("--thread-id", default=None,
                   help="Checkpoint thread id (default: pr-<num>)")
    p.add_argument("--resume", action="store_true",
                   help="Resume from checkpoint for --thread-id (or pr-<num>)")
    p.add_argument("--no-checkpoint", action="store_true",
                   help="In-memory checkpointer only")
    p.add_argument("--checkpoint-db", default=os.getenv("ORCH_CHECKPOINT_DB", ".orchestration_state.db"),
                   help="SQLite checkpoint path")
    p.add_argument("--quiet", action="store_true", help="Less console output")
    return p.parse_args()


def _print_result(result: dict) -> None:
    print("\n========== Orchestration result ==========")
    print(f"Thread:        {result['thread_id']}")
    print(f"Iterations:    {result.get('iteration', 0)}")
    print(f"Final action:  {result.get('next_action')}")
    print(f"Fork mode:     {result.get('is_fork')}")
    if result.get("summary_review_url"):
        print(f"Summary URL:   {result['summary_review_url']}")
    if result.get("stacked_pr_url"):
        print(f"Stacked PR:    {result['stacked_pr_url']}")
    if result.get("error"):
        print(f"Error:         {result['error']}")


async def _run(args: argparse.Namespace) -> int:
    agent = PROrchestrationAgent(
        checkpoint_db=args.checkpoint_db,
        use_checkpoint=not args.no_checkpoint,
    )
    severities = [s.strip() for s in args.severities.split(",") if s.strip()]
    verbose = not args.quiet

    try:
        if args.resume:
            result = await agent.resume(
                args.repo, args.pr,
                thread_id=args.thread_id,
                verbose=verbose,
            )
        else:
            result = await agent.run(
                args.repo, args.pr,
                max_iter=args.max_iter,
                severities=severities,
                enable_tester=not args.no_tester,
                tester_timeout_s=args.tester_timeout,
                thread_id=args.thread_id,
                verbose=verbose,
            )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    if verbose:
        _print_result(result)
    return 0 if result.get("success") else 1


def main() -> None:
    sys.exit(asyncio.run(_run(_parse_args())))


if __name__ == "__main__":
    main()
