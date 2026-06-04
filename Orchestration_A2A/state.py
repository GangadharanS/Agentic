"""Shared A2A orchestration state for the PR review workflow."""
from __future__ import annotations

from typing import Literal, TypedDict


class ReviewComment(TypedDict, total=False):
    file: str
    line: int
    text: str
    severity: str          # blocking | major | minor
    category: str
    type: str
    source: str            # "reviewer" | "tester"


class FixAttempt(TypedDict, total=False):
    file: str
    success: bool
    commit_sha: str
    message: str
    error: str


class TestRun(TypedDict, total=False):
    success: bool
    conclusion: str         # success | failure | timed_out | no_ci | skipped
    head_sha: str
    summary: str
    failed_checks: list[dict]
    timed_out: bool


class OrchestrationState(TypedDict, total=False):
    # ---- Inputs (set by main.py) ----
    repo_owner: str                 # BASE repo (where the PR lives)
    repo_name: str
    pr_number: int
    base_branch: str
    pr_title: str

    # ---- Resolved by init agent ----
    head_branch: str                # PR's source branch name
    head_sha: str                   # PR's current HEAD commit
    head_repo_owner: str            # for forks: fork owner; for same-repo: == repo_owner
    head_repo_name: str             # for forks: fork repo; for same-repo: == repo_name
    is_fork: bool
    ai_fix_branch: str              # fork mode: "ai-fixes/pr-<N>" created in base repo
    init_done: bool
    init_brief: str                 # SLM-generated context for downstream agents

    # ---- Configuration ----
    max_iterations: int
    fix_severities: list[str]       # e.g. ["blocking", "major"]
    enable_tester: bool
    tester_timeout_s: int

    # ---- Loop state ----
    iteration: int
    review_comments: list[ReviewComment]
    review_history: list[list[ReviewComment]]
    fixes_history: list[list[FixAttempt]]
    react_steps_log: list[dict]
    test_history: list[TestRun]

    # ---- Supervisor decision ----
    next_action: Literal[
        "fix",
        "push_clean",
        "push_max_iter",
        "push_no_fixable",
        "tests_pass",
        "tests_fail",
        "tests_skip",
    ]

    # ---- A2A routing (decided by each agent, followed by the supervisor) ----
    # The agent that just ran advertises which agent should run next. ``None`` /
    # END means the workflow is finished and the supervisor stops driving it.
    next_agent: str | None

    # ---- A2A trace/debug ----
    a2a_events: list[dict]

    # ---- Final ----
    summary_review_url: str | None
    stacked_pr_url: str | None
    error: str | None


PUSH_ACTIONS = {"push_clean", "push_no_fixable", "push_max_iter", "tests_fail"}

# Sentinel returned by an agent's routing decision when the workflow is complete.
END = None

# Agents that can be addressed over A2A.
AGENT_KEYS = ("init", "reviewer", "fixer", "tester", "pusher")
