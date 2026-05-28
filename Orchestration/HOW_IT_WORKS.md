# How the Orchestration Works — Deep Dive

A walkthrough of the LangGraph multi-agent PR review system in `Orchestration/`.

---

## Table of Contents

1. [What the system does](#1-what-the-system-does)
2. [Why the Supervisor / Orchestrator pattern](#2-why-the-supervisor--orchestrator-pattern)
3. [Architecture at a glance](#3-architecture-at-a-glance)
4. [State model — the shared "blackboard"](#4-state-model--the-shared-blackboard)
5. [The five agents in detail](#5-the-five-agents-in-detail)
   - 5.1 [init](#51-init--once-per-thread)
   - 5.2 [Reviewer](#52-reviewer--reuses-the-react-agent)
   - 5.3 [Fixer](#53-fixer--llm-rewrite--mcp-commit)
   - 5.4 [Tester](#54-tester--ci-feedback-loop)
   - 5.5 [Pusher](#55-pusher--final-step)
6. [Routing — how the Supervisor decides](#6-routing--how-the-supervisor-decides)
7. [Execution traces](#7-execution-traces)
   - 7.1 [Trace A: same-repo PR, two iterations, clean exit](#71-trace-a-same-repo-pr-two-iterations-clean-exit)
   - 7.2 [Trace B: fork PR with CI failure mid-loop](#72-trace-b-fork-pr-with-ci-failure-mid-loop)
8. [Checkpointing and resume](#8-checkpointing-and-resume)
9. [GitHub MCP tools used](#9-github-mcp-tools-used)
10. [Same-repo vs fork mode side-by-side](#10-same-repo-vs-fork-mode-side-by-side)
11. [Extension points](#11-extension-points)
12. [Failure modes and how the system handles them](#12-failure-modes-and-how-the-system-handles-them)

---

## 1. What the system does

Given a GitHub PR number, the orchestrator:

1. **Reviews** the PR using a ReAct agent (Thought → Action → Observe) that calls GitHub MCP tools.
2. **Fixes** the issues it finds by asking Gemini to rewrite the affected files and committing the rewrites back to GitHub.
3. **Waits for CI** to validate the fixes. If tests fail, it surfaces failures as new comments and re-enters the fix step.
4. **Re-reviews** after a successful fix-and-test pass, to confirm the issues are gone (or to surface new ones).
5. **Stops** when the PR is clean, only-minor issues remain, or it has burned its iteration budget.
6. **Pushes** a summary review back to the PR (and, for fork PRs, opens a stacked PR carrying the AI fixes).

All of this runs as a stateful graph with persistent checkpointing — you can `Ctrl-C` mid-run and resume right where it stopped.

---

## 2. Why the Supervisor / Orchestrator pattern

We considered four common multi-agent patterns:

| Pattern | Verdict | Why |
|---------|---------|-----|
| Sequential pipeline | ❌ | Can't naturally express the review ⇄ fix ⇄ test loop. Loops would need to be hardcoded outside the graph. |
| Parallel fan-out | ❌ | Steps are strictly sequential and data-dependent — review must happen before fix, fix before test. |
| Hierarchical agents | ⚠️  | Adds a second supervisor layer that doesn't pay for itself at 5 nodes. Worth revisiting only when we add multi-reviewer pools. |
| **Supervisor / Orchestrator** | ✅ | Conditional edges express "after this node, who runs next?" naturally. Same-agent re-entry (Reviewer → Fixer → Reviewer) falls out for free. State is centralised. |

In LangGraph, the "supervisor" is just a **conditional-edge function** that reads the current state and returns the name of the next node. We have two of them: `route_after_reviewer` and `route_after_tester` (both in `graph.py`).

---

## 3. Architecture at a glance

```
       ┌─────────┐
       │  START  │
       └────┬────┘
            ▼
        ┌────────┐   one-time: resolve PR metadata, detect fork, prepare ai-fixes/ branch
        │  init  │
        └────┬───┘
             ▼
        ┌──────────┐
        │ Reviewer │◄─────────────────────────────────┐
        └────┬─────┘                                  │
             │ route_after_reviewer                   │
             │                                        │
         fix │   push_clean / push_no_fixable / max   │
             ▼                                        │
        ┌──────────┐                                  │
        │  Fixer   │                                  │
        └────┬─────┘                                  │
             ▼                                        │
        ┌──────────┐                                  │
        │  Tester  │ ─ tests_pass / tests_skip ───────┘
        └────┬─────┘
             │ tests_fail        ─► Fixer (with CI-derived comments)
             │ tests_fail_max    ─► Pusher
             ▼
        ┌──────────┐
        │  Pusher  │ → summary review + (fork-mode) stacked PR
        └────┬─────┘
             ▼
            END
```

Every arrow is encoded in `graph.py`. Plain arrows are `add_edge`; the branching ones are `add_conditional_edges`.

---

## 4. State model — the shared "blackboard"

Every node receives the same `OrchestrationState` TypedDict, returns a partial dict, and LangGraph merges them. This is the entire conversation between agents — no direct calls, no shared globals.

```python
# state.py (excerpt)
class OrchestrationState(TypedDict, total=False):
    # Inputs
    repo_owner: str
    repo_name: str
    pr_number: int
    base_branch: str

    # Resolved by init_node
    head_branch: str
    head_sha: str
    head_repo_owner: str       # differs from repo_owner for forks
    head_repo_name: str
    is_fork: bool
    ai_fix_branch: str         # ai-fixes/pr-<N> when in fork mode
    init_done: bool

    # Config
    max_iterations: int
    fix_severities: list[str]
    enable_tester: bool
    tester_timeout_s: int

    # Loop state
    iteration: int
    review_comments: list[ReviewComment]                    # latest pass only
    review_history: Annotated[list[list[ReviewComment]], add]  # appended each pass
    fixes_history: Annotated[list[list[FixAttempt]], add]
    react_steps_log: Annotated[list[dict], add]
    test_history: Annotated[list[TestRun], add]

    # Supervisor decision
    next_action: Literal["fix", "push_clean", "push_max_iter",
                         "push_no_fixable", "tests_pass", "tests_fail", "tests_skip"]

    # Final
    summary_review_url: str | None
    stacked_pr_url: str | None
    error: str | None
```

### Reducers (`Annotated[..., add]`)

Fields like `review_history`, `fixes_history`, `react_steps_log`, `test_history` use `operator.add` as a reducer. That means when a node returns `{"review_history": [new_round_comments]}`, LangGraph **appends** instead of overwriting. This is how we keep a per-iteration audit trail without needing explicit accumulation logic in each agent.

Plain fields (without a reducer) — like `review_comments`, `iteration`, `next_action` — are **overwritten** each time. The Fixer clears `review_comments` to `[]` after applying fixes; the Reviewer fills it again on the next pass.

---

## 5. The five agents in detail

### 5.1 init — once per thread

```python
# agents/init_agent.py
async def init_node(state):
    if state.get("init_done"):     # idempotent — resume-safe
        return {}
    ...
```

**Inputs:** `repo_owner`, `repo_name`, `pr_number`
**Outputs (state delta):** `head_branch`, `head_sha`, `base_branch`, `head_repo_owner`, `head_repo_name`, `is_fork`, `ai_fix_branch?`, `pr_title`, `init_done=True`

**Steps:**

1. `get_pull_request(owner, repo, pullNumber)` — single MCP call.
2. Compare `head.repo.full_name` vs `base.repo.full_name`. If different → **fork PR**.
3. If fork: call `create_branch(owner, repo, branch="ai-fixes/pr-<N>", from_branch=base_branch)`. Treats "reference already exists" (HTTP 422) as success — that's how resume works.
4. Returns the delta. `init_done=True` prevents redundant calls on resume.

The fork detection is the only place we ever look at `head.repo` — every downstream agent reads `head_repo_owner` / `head_repo_name` / `is_fork` from state instead.

### 5.2 Reviewer — reuses the ReAct agent

```python
# agents/reviewer_agent.py
async def reviewer_node(state):
    agent = PRReviewAgent(mcp_server_url=os.getenv("MCP_SERVER_URL"))
    result = await agent.review(repo=f"{owner}/{repo}", pr_id=pr_num,
                                 verbose=False, max_rounds=8)
    ...
```

**Inputs:** `repo_owner`, `repo_name`, `pr_number`, current `iteration`, `max_iterations`, `fix_severities`
**Outputs:** `review_comments`, `review_history` (appended), `react_steps_log` (appended), `next_action`

We **reuse** `ReAct/PRReviewAgent.review()` — no reinvention. It runs up to 8 ReAct rounds with these MCP tools available: `get_pull_request`, `get_pull_request_files`, `get_pull_request_diff`, `get_file_contents`, etc. Returns a structured JSON:

```json
{
  "summary": { "source_branch": "feature/x", "destination_branch": "main", "pr_title": "..." },
  "comments": [
    {"file": "src/auth.py", "line": 42, "severity": "blocking",
     "category": "security", "text": "SQL string concatenation — use parameterised query."},
    {"file": "src/utils.py", "line": 17, "severity": "minor",
     "category": "style", "text": "Inconsistent quotes."}
  ]
}
```

After review, the **supervisor function** `_decide_next` runs in-process and sets `next_action`:

```python
# Pseudocode of the decision
fixable = [c for c in comments if c.severity in {"blocking","major"}]

if not comments:              → "push_clean"          # nothing to do
if not fixable:               → "push_no_fixable"     # only minor stuff
if iteration >= max_iter:     → "push_max_iter"       # out of budget
else:                         → "fix"                  # keep looping
```

This decision is **state-only** — no LLM call. The Reviewer never decides whether to loop again; it just produces comments and lets the routing function read the state.

### 5.3 Fixer — LLM rewrite + MCP commit

```python
# agents/fixer_agent.py
async def fixer_node(state):
    # 1. Group fixable comments by file
    # 2. For each file: read → LLM rewrite → write back
```

**Inputs:** `review_comments` (filtered to fixable severities), `is_fork`, `ai_fix_branch`, `head_*` fields
**Outputs:** `fixes_history` (appended), `iteration` (incremented), `review_comments=[]` (cleared)

**Per-file flow:**

```
┌────────────────────────────────────────────────────────────────────────────┐
│ 1. read_target = (head_repo_owner, head_repo_name) if is_fork else base    │
│    read_ref    = head_sha            if is_fork else head_branch           │
│                                                                            │
│ 2. MCP: get_file_contents(read_target, path, read_ref)                     │
│         → decode base64 if needed → (current_content, _)                   │
│                                                                            │
│ 3. Gemini: rewrite the file given comments_block                           │
│         system  = FIXER_SYSTEM_PROMPT                                      │
│         user    = current_content + comments                               │
│         output  = full new file content (no fences, no commentary)         │
│                                                                            │
│ 4. write_target  = (repo_owner, repo_name)                                 │
│    write_branch  = ai_fix_branch   if is_fork else head_branch             │
│    write_sha     = sha of file ON write_branch (separate MCP call)         │
│                                                                            │
│ 5. MCP: create_or_update_file(write_target, path, content, message,        │
│                                branch, sha=write_sha)                      │
│                                                                            │
│ 6. Record FixAttempt {file, success, commit_sha, error}                    │
└────────────────────────────────────────────────────────────────────────────┘
```

**Why two `get_file_contents` calls in fork mode?**
We need to **read** from the fork (because that's where the PR's actual code is) but **write** to our `ai-fixes/...` branch in the base repo (which started from `base_branch`). The two locations have different blob SHAs for the same path, so we fetch both — the content from the fork, the sha from our AI branch — and then PUT.

**Why is `sha` optional?**
For files that don't exist yet on the write branch (e.g. a new file we're copying over from the fork PR), `create_or_update_file` will *create* them. So we only attach `sha` when the file already exists on the write target.

**Failure isolation:** every file is wrapped in its own try-paths. A single LLM hiccup or a stale sha doesn't crash the whole pass — it's logged in `fixes_history[i][k]` with `success=False` and the orchestrator carries on.

### 5.4 Tester — CI feedback loop

```python
# agents/tester_agent.py
async def tester_node(state):
    ref = ai_fix_branch if is_fork else head_branch
    while not deadline_reached:
        runs = list_check_runs_for_ref(owner, repo, ref)
        if all completed:
            break
        sleep(15)
```

**Inputs:** `head_branch` (or `ai_fix_branch`), `tester_timeout_s`, `enable_tester`, current `iteration`
**Outputs:** `next_action`, `test_history` (appended), `review_comments` (set with synthetic CI comments if tests fail)

**Decision matrix:**

| Tester observes | next_action | Routes to |
|-----------------|-------------|-----------|
| All check runs `conclusion=success` | `tests_pass` | Reviewer (re-review for residuals) |
| MCP tool unavailable / no runs found before timeout | `tests_skip` | Reviewer (graceful degrade) |
| Any check `conclusion ∈ {failure, timed_out, cancelled, action_required}` | `tests_fail` | Fixer (with new comments) **or** Pusher if iteration cap hit |
| Polling deadline elapsed while some runs still running | `tests_fail` (with `timed_out=True`) | Pusher (no actionable comments) |

**Synthetic comment shape** (so the Fixer can route them, even if it can't actually patch CI):

```python
{
  "file": "<ci>",                # sentinel — Fixer skips entries with file=="<ci>"
  "line": 0,
  "text": "CI check **pytest** failed: 3 tests failed in tests/test_auth.py",
  "severity": "blocking",
  "category": "test_failure",
  "source": "tester",
}
```

Because `file="<ci>"` is filtered out of `fixable` in `fixer_node`, these synthetic comments don't directly drive file edits. Instead they ensure the next Reviewer pass *re-reads the diff and the test output* and (hopefully) raises file-level comments that explain the failure. This is intentional separation: the Tester reports symptoms, the Reviewer diagnoses, the Fixer patches.

If you'd rather have the Tester drive direct fixes, change `<ci>` to the failing test file path and the Fixer will attempt to patch it.

### 5.5 Pusher — final step

```python
# agents/pusher_agent.py
async def pusher_node(state):
    body = render_summary(state)
    if is_fork and any_fix_succeeded:
        stacked_url = create_pull_request(...)           # ai-fixes/pr-N → base_branch
        body += "📦 Stacked AI fixes PR: " + stacked_url
    review_url = create_pull_request_review(event="COMMENT", body=body)
```

**Inputs:** the whole state — uses `next_action`, `iteration`, `review_history`, `fixes_history`, `test_history`
**Outputs:** `summary_review_url`, `stacked_pr_url` (fork mode only)

**Rules:**

- **Never `APPROVE`** — always posts a `COMMENT` review. Approvals get a human in front of an LLM-generated decision; we don't want that.
- **Fork mode:** opens a stacked PR `ai-fixes/pr-<N>` → `base_branch` **only if at least one fix succeeded**. Otherwise the AI branch is empty / identical to base and a PR would be noise.
- The summary review on the original PR includes a Markdown link to the stacked PR when one is created.

---

## 6. Routing — how the Supervisor decides

There are two conditional-edge functions:

```python
# graph.py
def route_after_reviewer(state):
    return state.get("next_action") or "push_clean"   # set by reviewer_node

def route_after_tester(state):
    action = state.get("next_action") or "tests_skip"
    if action == "tests_fail" and state["iteration"] >= state["max_iterations"]:
        return "tests_fail_max_iter"                  # special: route to pusher
    return action
```

And in the graph wiring:

```python
workflow.add_conditional_edges("reviewer", route_after_reviewer, {
    "fix": "fixer",
    "push_clean": "pusher",
    "push_no_fixable": "pusher",
    "push_max_iter": "pusher",
})

workflow.add_edge("fixer", "tester")           # unconditional

workflow.add_conditional_edges("tester", route_after_tester, {
    "tests_pass": "reviewer",
    "tests_skip": "reviewer",
    "tests_fail": "fixer",
    "tests_fail_max_iter": "pusher",
})
```

Two structural properties this gives you:

1. **The Fixer is the only writer.** All commits flow through one node, which means the audit trail (`fixes_history`) is complete.
2. **The Reviewer is the only path to Pusher in "happy" exits.** Even after a passing test run, we go back to the Reviewer once — which lets it catch a regression the test suite missed.

---

## 7. Execution traces

### 7.1 Trace A: same-repo PR, two iterations, clean exit

Setup:
- `owner/repo#42`
- Original PR has 3 blocking comments and 1 minor comment across 2 files
- After first fix round, 1 new blocking comment surfaces
- After second fix round, all clear; CI passes

```
START
  │
init      head_branch=feature/x  base_branch=main  is_fork=False
  ▼
reviewer  iteration=0
          review_comments=[3 blocking, 1 minor]
          review_history=[[3 blocking, 1 minor]]
          next_action="fix"                                ─► fixer
  ▼
fixer     iteration=1
          (file A) get_file_contents → Gemini → create_or_update_file ✓
          (file B) get_file_contents → Gemini → create_or_update_file ✓
          fixes_history=[[ {A,ok},{B,ok} ]]
          review_comments=[]
  ▼
tester    list_check_runs_for_ref(feature/x)
          poll … all completed conclusion=success
          test_history=[{success:True,...}]
          next_action="tests_pass"                          ─► reviewer
  ▼
reviewer  iteration=1
          review_comments=[1 blocking]
          review_history=[[3+1], [1]]
          next_action="fix"                                 ─► fixer
  ▼
fixer     iteration=2
          (file A) ... ✓
          fixes_history=[[..],[{A,ok}]]
          review_comments=[]
  ▼
tester    all green again
          test_history=[..,{success:True,...}]
          next_action="tests_pass"                          ─► reviewer
  ▼
reviewer  iteration=2
          review_comments=[]
          review_history=[[4],[1],[]]
          next_action="push_clean"                          ─► pusher
  ▼
pusher    create_pull_request_review(event=COMMENT, body=summary)
          summary_review_url=https://github.com/owner/repo/pull/42#pullrequestreview-...
  ▼
END
```

### 7.2 Trace B: fork PR with CI failure mid-loop

Setup:
- `acme/widget#88` opened from `forkuser/widget:feature/bug-fix`
- 2 blocking comments
- After first fix, CI fails on a unit test
- Second fix addresses the test; CI passes; one minor remains

```
START
  │
init      get_pull_request → head.repo=forkuser/widget ≠ base.repo=acme/widget
          is_fork=True
          head_repo_owner=forkuser  head_repo_name=widget
          head_sha=abc123…  head_branch=feature/bug-fix
          create_branch(acme/widget, "ai-fixes/pr-88", from_branch="main") ✓
          ai_fix_branch="ai-fixes/pr-88"
  ▼
reviewer  iteration=0
          review_comments=[2 blocking]
          next_action="fix"                                 ─► fixer
  ▼
fixer     iteration=1
          for each file:
            READ  get_file_contents(forkuser/widget, path, ref=abc123…)
            LLM   Gemini rewrites
            WRITE get_file_contents(acme/widget, path, ref="ai-fixes/pr-88") → sha
                  create_or_update_file(acme/widget, …, branch="ai-fixes/pr-88", sha) ✓
          fixes_history=[[ {f1,ok},{f2,ok} ]]
  ▼
tester    list_check_runs_for_ref(acme/widget, "ai-fixes/pr-88")
          one check failed → conclusion=failure
          review_comments=[{file:"<ci>", severity:blocking, text:"CI check pytest failed: …"}]
          test_history=[{success:False, conclusion:"failure"}]
          next_action="tests_fail"   (iteration 1 < max 5)  ─► fixer
  ▼
fixer     iteration=2
          fixable = [] (only <ci> comments — filtered out)
          fixes_history=[…, []]   # empty round
          review_comments=[]
  ▼
tester    same ref again → CI re-runs on the latest commit (which was the previous round)
          actually still failing → tests_fail
          *but* iteration=2 < max, so → fixer again

  (This is the failure mode noted in §12 — the Tester alone cannot break out
   of the loop if the Fixer has nothing to act on. The graph relies on the
   *Reviewer* being able to re-look at the diff and produce real file-level
   comments next time around. To force a Reviewer re-pass after a tests_fail
   with no fixable file comments, see the "Tester → Reviewer escape" idea
   in §11.)

  Assume the user trips max_iter:
  …
tester    iteration=5 reached → next_action="tests_fail_max_iter" ─► pusher
  ▼
pusher    is_fork && any_fix_ok → create_pull_request(
              owner=acme, repo=widget,
              title="AI fixes for #88: …",
              head="ai-fixes/pr-88",
              base="main")
          stacked_pr_url=https://github.com/acme/widget/pull/89
          create_pull_request_review on #88 with body + link to #89
  ▼
END
```

---

## 8. Checkpointing and resume

Checkpointing in LangGraph is a few lines:

```python
# main.py
async with AsyncSqliteSaver.from_conn_string(args.checkpoint_db) as saver:
    graph = build_graph(checkpointer=saver)
    config = {"configurable": {"thread_id": "pr-42"}, "recursion_limit": 80}
    final = await graph.ainvoke(initial, config=config)
```

What happens under the hood:

1. **Before every node runs**, LangGraph snapshots `OrchestrationState` and writes a row to SQLite keyed by `(thread_id, checkpoint_id)`.
2. **If the process dies** during/before a node, the state is intact on disk.
3. **`graph.ainvoke(None, config=...)` with `--resume`** loads the latest checkpoint for that `thread_id` and continues from the next pending node.

Why this matters in practice:

- The Tester can sit on a `sleep(15)` for ~10 minutes. A laptop sleeping mid-loop won't lose progress.
- An MCP server bounce mid-Fixer-loop only loses the in-flight file; the next resume retries.
- You can run two threads concurrently for the same PR (e.g., `pr-42-security` and `pr-42-perf`) by passing different `--thread-id` values.

**Caveat:** `init_done` is set to `True` after the first `init_node` run. On resume, `init_node` returns `{}` immediately. If you ever change the fork-detection logic and want to re-run init, change the thread_id or wipe the DB row.

---

## 9. GitHub MCP tools used

| Tool | Used by | Purpose |
|------|---------|---------|
| `get_pull_request` | init, Reviewer | PR metadata (head/base, fork, sha) |
| `get_pull_request_files` | Reviewer (ReAct loop) | List changed files |
| `get_pull_request_diff` | Reviewer (ReAct loop) | Read the actual diff |
| `get_file_contents` | Reviewer, Fixer | Read file content + sha |
| `create_branch` | init | Create `ai-fixes/pr-<N>` in fork mode |
| `create_or_update_file` | Fixer | Commit the rewritten file |
| `list_check_runs_for_ref` | Tester | Poll CI runs |
| `get_pull_request_status` | Tester (fallback) | Combined PR status if check runs tool isn't available |
| `create_pull_request` | Pusher (fork only) | Stacked PR for AI fixes |
| `create_pull_request_review` | Pusher | Summary comment on original PR |

All names match `ReAct/prompts.py` constants — that's the source of truth for tool spelling.

---

## 10. Same-repo vs fork mode side-by-side

|                | Same-repo PR | Fork PR |
|----------------|--------------|---------|
| `is_fork` | `False` | `True` |
| `head_repo_owner`/`name` | == `repo_owner`/`name` | the fork's owner/repo |
| `ai_fix_branch` | _unset_ | `ai-fixes/pr-<N>` |
| Fixer **reads** from | base repo @ `head_branch` | fork repo @ `head_sha` |
| Fixer **writes** to | base repo @ `head_branch` | base repo @ `ai_fix_branch` |
| Tester polls CI on | `head_branch` | `ai_fix_branch` |
| Pusher posts | `COMMENT` review on PR | `COMMENT` review on PR + opens stacked PR |
| Human merges by | Approving + merging the PR | Approving stacked PR, then re-syncing original |

---

## 11. Extension points

### Add a multi-reviewer pool (parallel fan-out under the supervisor)

Add three reviewer specialists — `security_reviewer`, `perf_reviewer`, `style_reviewer` — and a "merge_reviews" node that union-deduplicates their comments. The supervisor edge after `merge_reviews` is identical to today's `route_after_reviewer`.

```
init → [security, perf, style] (parallel) → merge_reviews → fixer/pusher → …
```

LangGraph supports parallel branches by attaching `add_edge("init", ...)` to multiple nodes; their outputs naturally merge because the state's history fields use `add` reducers.

### Tester → Reviewer escape hatch

Add a small flag to `route_after_tester`: after N consecutive `tests_fail` rounds with no file-level comments produced, force a route back to Reviewer instead of Fixer. This breaks out of the empty-fixer loop in Trace B.

### Stale-sha retry on `create_or_update_file`

Wrap step (5) of the Fixer with a single retry: on 409/422, re-run step (4) and try again. Concurrent human pushes during the loop won't trigger a `success=False` then.

### Test-runner agent (not just CI poller)

Today's Tester is read-only. A more aggressive version could:
- Dispatch a workflow with `create_workflow_dispatch`
- Stream `get_workflow_run_logs` and pass failures (with stack traces) directly to the Fixer with `file=<actual failing test file>`

### Full-PR carry-over for fork mode

Today the AI branch only contains files we touched. Pre-fill it with the entire fork PR diff:
- `get_pull_request_files` → list of paths
- For each: read from fork @ head_sha, write to AI branch
- *Then* enter the normal loop. The stacked PR will then visually mirror the original PR (with AI tweaks on top).

---

## 12. Failure modes and how the system handles them

| Failure | Behaviour |
|---------|-----------|
| `GEMINI_API_KEY` missing | Fixer returns `error` in state; routes to Pusher with `push_max_iter` label. |
| MCP server down | First `get_pull_request` in init fails; pushes a "no init" error. Resume can pick up once MCP is back. |
| `create_or_update_file` rejected (stale sha) | That file is logged with `success=False`; loop continues with other files. No retry today. |
| LLM returns the same content | Logged as `"LLM produced no change"`; file is skipped. |
| LLM returns code fences despite system prompt | `_strip_code_fences` defensively removes them. |
| CI never runs (no GitHub Actions configured) | Tester returns `tests_skip` after timeout / no runs; routes to Reviewer. |
| CI timeout mid-loop | Tester returns `tests_fail` with `timed_out=True` and no comments; routes to Pusher with max-iter check. |
| Fork's AI branch already exists | `create_branch` returns 422; init treats it as "reuse" (this is how resume works). |
| Reviewer can't produce valid JSON | `parsed=None`, `comments=[]`, treated as `push_clean`. This is the silent-fail mode — keep `verbose=True` if you want to see ReAct steps. |
| Pusher can't post the review and there's no stacked PR | `error` set on state; the CLI exits with code 1. The state still contains everything needed to retry by hand. |

---

## TL;DR

- **One graph, five nodes, two routers, one shared state.**
- The supervisor isn't an LLM — it's a 5-line `if/else` reading state set by the Reviewer and Tester.
- The Fixer is the only writer to GitHub. The Reviewer/Tester only read.
- Fork PRs get a separate `ai-fixes/pr-<N>` branch in the base repo and a stacked PR at the end.
- Every transition is checkpointed; resume is a one-flag operation.
- Nothing is auto-approved — humans always merge.
