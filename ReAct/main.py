#!/usr/bin/env python3
"""
ReAct PR Review CLI — review any GitHub PR using MCP tools.

Prerequisites:
  1. MCP server running (docker-compose up from project root, port 8000)
  2. GEMINI_API_KEY set (free tier: https://aistudio.google.com/apikey)
  3. GITHUB_TOKEN set on the MCP server (docker-compose / root .env)

Usage:
  cd ReAct
  python main.py --repo owner/repo --pr 123
  python main.py --repo owner/repo --pr 123 --post
  python main.py --repo owner/repo --pr 123 --output review.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from dotenv import load_dotenv

from pr_reviewer import PRReviewAgent

load_dotenv()


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Review a GitHub PR using ReAct + MCP"
    )
    parser.add_argument(
        "--repo",
        required=True,
        help="GitHub repository as owner/repo-name",
    )
    parser.add_argument(
        "--pr",
        required=True,
        help="Pull request number",
    )
    parser.add_argument(
        "--post",
        action="store_true",
        help="Post the review to GitHub after analysis",
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Write review JSON to this file",
    )
    parser.add_argument(
        "--mcp-url",
        default=None,
        help="MCP server URL (default: MCP_SERVER_URL env or http://localhost:8000)",
    )
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=8,
        help="Max ReAct tool rounds (default: 8)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Less console output",
    )
    args = parser.parse_args()

    agent = PRReviewAgent(mcp_server_url=args.mcp_url)
    deps = await agent.check_dependencies()

    if not deps["mcp_server"]:
        print("ERROR: MCP server not reachable. Start it: docker-compose up -d (project root)")
        return 1
    if not deps["gemini"]:
        print("ERROR: GEMINI_API_KEY not set. Copy .env.example → .env and add your key.")
        print("       Free key: https://aistudio.google.com/apikey")
        return 1

    print(f"LLM: Gemini ({deps.get('gemini_model', 'gemini-2.0-flash')})")
    print(f"MCP tools: {deps['tools_discovered']}")
    print(f"Reviewing {args.repo} PR #{args.pr} ...\n")

    result = await agent.review(
        repo=args.repo,
        pr_id=args.pr,
        verbose=not args.quiet,
        max_rounds=args.max_rounds,
    )

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        print(f"\nWrote {args.output}")

    comments = result.get("comments") or []
    print(f"\n{'=' * 60}")
    print(f"Review complete: {len(comments)} comment(s)")
    if result.get("summary"):
        print(json.dumps(result["summary"], indent=2))
    if comments:
        for i, c in enumerate(comments, 1):
            print(f"\n{i}. [{c.get('severity', '?')}] {c.get('file', '?')}:{c.get('line', '?')}")
            print(f"   {c.get('text', '')}")
    elif result.get("raw_response"):
        print("\nRaw LLM response:")
        print(result["raw_response"][:2000])

    if args.post:
        print("\nPosting review to GitHub...")
        post = await agent.post_review(
            repo=args.repo,
            pr_id=args.pr,
            review=result.get("review") or {"comments": comments},
            verbose=not args.quiet,
        )
        print(json.dumps(post, indent=2, default=str))
        if not post.get("success"):
            return 1

    return 0 if result.get("success") else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
