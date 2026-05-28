# Orchestration — Multi-Agent PR Review with LangGraph

Five-node Supervisor/Orchestrator graph with **CI feedback loop**, **persistent checkpoints**, and **fork-PR support**.

> 📖 **For a deep dive on how every piece works — state model, routing, execution traces, failure modes — see [`HOW_IT_WORKS.md`](./HOW_IT_WORKS.md).**

```
       ┌─────────┐
       │  START  │
       └────┬────┘
            ▼
        ┌────────┐   one-time: resolves head/base/fork, prepares ai-fixes/ branch
        │  init  │
        └────┬───┘
             ▼
        ┌──────────┐
        │ Reviewer │◄────────────────────────────────┐
        └────┬─────┘                                 │
             │ route_after_reviewer                  │
             │                                       │
         fix │   push_clean/push_no_fixable/push_max │
             ▼                                       │
        ┌──────────┐                                 │
        │  Fixer   │                                 │
        └────┬─────┘                                 │
             ▼                                       │
        ┌──────────┐                                 │
        │  Tester  │ ─tests_pass / tests_skip────────┘
        └────┬─────┘
             │ tests_fail (iter<max) ─► back to Fixer with CI-derived comments
             │ tests_fail_max_iter   ─► Pusher
             ▼
        ┌──────────┐
        │  Pusher  │ → summary review + (fork-mode) stacked PR
        └────┬─────┘
             ▼
            END
```

## Agents

| Node | Role |
|------|------|
| **init** | One-time: calls `get_pull_request`, captures `head_sha`/`head_branch`/`base_branch`, detects forks (`head.repo.full_name ≠ base.repo.full_name`), idempotently creates `ai-fixes/pr-<N>` in the base repo when needed. |
| **Reviewer** | Reuses `ReAct/PRReviewAgent` — ReAct loop over GitHub MCP tools, returns structured `comments[]` with severities. |
| **Fixer** | For each file with fixable comments: reads current source, asks Gemini to rewrite it, commits via `create_or_update_file`. **Fork-aware**: reads from the fork's `head_sha`, writes to `ai-fixes/pr-<N>` in the base repo. |
| **Tester** | Polls `list_check_runs_for_ref` for the latest commit on the PR branch (or `ai-fixes/...` for forks). If runs fail, converts failures into synthetic `blocking` comments and routes back to Fixer. |
| **Pusher** | Always posts a `COMMENT` review on the original PR (never auto-approves). In fork mode, also opens a stacked PR `ai-fixes/pr-<N>` → `base_branch`. |

## Routing logic

**Reviewer →**
| State | Next |
|-------|------|
| No comments | `pusher` (clean) |
| Only minor comments | `pusher` (no_fixable) |
| Iteration ≥ max | `pusher` (max_iter) |
| Fixable comments + budget | `fixer` |

**Tester →**
| State | Next |
|-------|------|
| All checks pass | `reviewer` (verify with a fresh ReAct pass) |
| No CI configured / no tool available | `reviewer` (skipped) |
| Failures + budget | `fixer` (with synthetic test-failure comments) |
| Failures + iteration ≥ max | `pusher` (tests_fail) |

## Persistence & resume

Every state transition is checkpointed to **`.orchestration_state.db`** (SQLite via `AsyncSqliteSaver`) under a stable `thread_id` (default `pr-<num>`).

```bash
# First run — orchestrator crashes/network drops/Ctrl-C
python main.py --repo owner/repo --pr 42

# Resume from where it stopped — same thread_id
python main.py --repo owner/repo --pr 42 --resume

# Custom thread id (e.g. multiple agents running same PR)
python main.py --repo owner/repo --pr 42 --thread-id pr-42-security
```

Disable persistence: `--no-checkpoint` (in-memory `MemorySaver` only).

## Fork-PR support

When the init node detects `head.repo ≠ base.repo`:

1. Creates `ai-fixes/pr-<N>` in the **base repo** (branched from `base_branch`).
2. **Fixer reads** files from the fork at the PR's `head_sha` (cross-repo read is fine with MCP).
3. **Fixer writes** the corrected versions to `ai-fixes/pr-<N>` in the base repo.
4. **Pusher opens a stacked PR**: `ai-fixes/pr-<N>` → `base_branch`, and posts a summary comment on the original PR linking to it.

> **Caveat:** the AI branch starts from `base_branch`, so it contains the fork PR's files *only for the files we touched*. Reviewers can compare the AI diff against the original PR. If you need the AI branch to reflect *all* of the PR's changes, extend `init_node` to list PR files and pre-copy each one from the fork's head sha.

## Setup

```bash
cd Orchestration
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r ../ReAct/requirements.txt
cp .env.example .env
# Fill in GEMINI_API_KEY + GITHUB_TOKEN + MCP_SERVER_URL
```

Make sure the **GitHub MCP server** is reachable (default `http://localhost:8000`):

```bash
docker run -d --name github-mcp -p 8000:8082 \
  -e GITHUB_PERSONAL_ACCESS_TOKEN=$GITHUB_TOKEN \
  ghcr.io/github/github-mcp-server:latest http
```

## Run

```bash
# Defaults: max 5 iters, blocking+major severities, tester ON, SQLite checkpoint
python main.py --repo owner/repo --pr 42

# Tight loop, blocking only, no CI wait
python main.py --repo owner/repo --pr 42 --max-iter 3 --severities blocking --no-tester

# Resume after Ctrl-C
python main.py --repo owner/repo --pr 42 --resume
```

## Configuration

| Env var | Default | CLI flag | Purpose |
|---------|---------|----------|---------|
| `GEMINI_API_KEY` | — | — | Gemini API key (required) |
| `GEMINI_MODEL` | `gemini-2.0-flash` | — | Model for Reviewer + Fixer |
| `MCP_SERVER_URL` | `http://localhost:8000` | — | GitHub MCP server endpoint |
| `GITHUB_TOKEN` | — | — | Bearer to the MCP server |
| `ORCH_MAX_ITERATIONS` | `5` | `--max-iter` | Loop cap |
| `ORCH_FIX_SEVERITIES` | `blocking,major` | `--severities` | Which comments the Fixer addresses |
| `ORCH_TESTER_TIMEOUT` | `600` | `--tester-timeout` | Seconds to wait for CI |
| `ORCH_CHECKPOINT_DB` | `.orchestration_state.db` | `--checkpoint-db` | SQLite checkpoint path |
| — | — | `--no-tester` | Skip the CI wait |
| — | — | `--no-checkpoint` | Use MemorySaver instead of SQLite |
| — | — | `--thread-id` | Override checkpoint thread (default `pr-<num>`) |
| — | — | `--resume` | Resume from prior checkpoint |

## Files

```
Orchestration/
├── README.md
├── requirements.txt
├── .env.example
├── main.py                  # CLI → PROrchestrationAgent
├── pr_orchestrator.py       # PROrchestrationAgent (parallel to ReAct/PRReviewAgent)
├── graph.py                 # LangGraph wiring + routing
├── state.py                 # Shared TypedDict state w/ reducers
├── prompts.py               # Fixer + Pusher templates
├── _react_path.py           # Adds ../ReAct to sys.path
└── agents/
    ├── init_agent.py        # NEW — PR metadata + fork detection + AI branch
    ├── reviewer_agent.py
    ├── fixer_agent.py       # fork-aware reads/writes
    ├── tester_agent.py      # NEW — CI poll + synthetic test-failure comments
    └── pusher_agent.py      # fork-aware: posts review + opens stacked PR
```

## Why this pattern (vs alternatives)

| Pattern | Verdict |
|---------|---------|
| **Supervisor / Orchestrator** | ✅ Chosen — handles conditional loops + termination + same-agent re-entry cleanly with LangGraph conditional edges. |
| Sequential pipeline | ❌ Can't express review ⇄ fix ⇄ test loop without hardcoding iterations. |
| Parallel fan-out | ❌ Steps are sequential and dependent. |
| Hierarchical agents | ⚠️  Overkill at 5 nodes. Reconsider if you add multi-reviewer pools (security, perf, style, etc.). |

## Future ideas

- **Per-comment patches** — replace whole-file rewrite with hunk-level edits to reduce tokens.
- **Multi-reviewer pool** — security/perf/style reviewers running in parallel, supervisor merges their comments.
- **Stale-sha retry** — if `create_or_update_file` rejects due to concurrent push, refetch sha and retry once.
- **Stacked-PR includes full PR contents** — init pre-copies every file from the fork PR before fixes start.
