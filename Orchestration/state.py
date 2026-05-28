"""Shared LangGraph state for the PR review orchestrator."""
from __future__ import annotations

from operator import add
from typing import Annotated, Literal, TypedDict


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

    # ---- Resolved by init_node ----
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
    review_history: Annotated[list[list[ReviewComment]], add]
    fixes_history: Annotated[list[list[FixAttempt]], add]
    react_steps_log: Annotated[list[dict], add]
    test_history: Annotated[list[TestRun], add]

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

    # ---- Final ----
    summary_review_url: str | None
    stacked_pr_url: str | None
    error: str | None
