# Orchestration_ADK — Google ADK PR Review Orchestrator

A **Google Agent Development Kit (ADK)** port of the LangGraph orchestrator in
[`../Orchestration`](../Orchestration). Same supervisor flow, same GitHub PR
review/auto-fix/CI loop — but built on ADK primitives, using **GCP Gemini
models** and the **remote GitHub MCP server** (no self-hosted MCP, no Azure).

```
            ┌──────────┐
            │   init   │  one-time: PR metadata, fork detection, ai-fixes branch
            └────┬─────┘
                 ▼
            ┌──────────┐
            │ reviewer │◄──────────────────────────────┐
            └────┬─────┘                                │
        fix │     push_clean/no_fixable/max_iter        │
            ▼                  └────────────► pusher     │
            ┌──────────┐                                 │
            │  fixer   │                                 │
            └────┬─────┘                                 │
                 ▼                                       │
            ┌──────────┐ tests_pass / tests_skip ────────┘
            │  tester  │
            └────┬─────┘ tests_fail (iter<max) ─► fixer (with synthetic <ci> comments)
                 │       tests_fail (iter>=max) ─► pusher
                 ▼
            ┌──────────┐
            │  pusher  │ → COMMENT review + (fork-mode) stacked PR
            └──────────┘
```

## How this differs from the LangGraph version

| Concern | LangGraph (`../Orchestration`) | This (`Orchestration_ADK`) |
|---------|-------------------------------|----------------------------|
| Framework | `langgraph.StateGraph` + conditional edges | Google ADK `BaseAgent` agents |
| Orchestration | Graph nodes + `route_*` edge functions | Custom `PROrchestrator(BaseAgent)` driving sub-agents |
| Shared state | Typed `OrchestrationState` + reducers | `ctx.session.state` dict + `state.append()` helper |
| LLM (fixer/init/pusher) | `google.generativeai` (AI Studio) | `google-genai` → **Vertex AI** or AI Studio |
| Reviewer | Reuses `ReAct/PRReviewAgent` | Reuses `ReAct/PRReviewAgent` (unchanged) |
| MCP | `MCP_SERVER_URL` (self-host / Azure) | `MCP_SERVER_URL` = **remote** `api.githubcopilot.com/mcp/` |
| Persistence | SQLite checkpoint + `--resume` | In-memory ADK session (no resume yet) |

> **Why a custom `BaseAgent`?** ADK's `SequentialAgent` / `LoopAgent` express
> linear and repeat-until flows, but this graph has conditional branches the
> reviewer can take straight to the pusher, and the tester loops back to either
> the fixer *or* the reviewer. ADK's documented pattern for that is a custom
> `BaseAgent` with explicit Python control flow — see `agents/orchestrator.py`.

## Agents

| File | ADK type | Role |
|------|----------|------|
| `agents/init_agent.py` | `BaseAgent` | PR metadata, fork detection, `ai-fixes/pr-N` branch, SLM brief |
| `agents/reviewer_agent.py` | `BaseAgent` | Wraps ReAct `PRReviewAgent`; sets `next_action` |
| `agents/fixer_agent.py` | `BaseAgent` | Gemini file rewrite + MCP `create_or_update_file` (fork-aware) |
| `agents/tester_agent.py` | `BaseAgent` | Polls `list_check_runs_for_ref`; synthetic CI comments |
| `agents/pusher_agent.py` | `BaseAgent` | `create_pull_request_review` + fork stacked PR |
| `agents/orchestrator.py` | `BaseAgent` | Supervisor routing (mirrors `graph.py`) |

Helpers: `state.py` (session-state schema), `gcp_llm.py` (Vertex/AI-Studio
Gemini), `mcp_client.py` (remote MCP via ReAct's client), `prompts.py`.

## Setup

```bash
cd Orchestration_ADK
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r ../ReAct/requirements.txt
cp .env.example .env
# Fill in either Vertex AI (GOOGLE_CLOUD_PROJECT + gcloud ADC) or GOOGLE_API_KEY,
# plus GEMINI_API_KEY (reviewer) and GITHUB_TOKEN.
```

### GCP models — two options

1. **Vertex AI (true GCP):**
   ```bash
   gcloud auth application-default login
   # in .env:
   GOOGLE_GENAI_USE_VERTEXAI=TRUE
   GOOGLE_CLOUD_PROJECT=your-project-id
   GOOGLE_CLOUD_LOCATION=us-central1
   ```
2. **Google AI Studio key:** set `GOOGLE_API_KEY` (and `GEMINI_API_KEY`).

> The **Reviewer** reuses ReAct's `PRReviewAgent`, which uses the Gemini API key
> (`GEMINI_API_KEY`). The **Fixer / Init / Pusher** use `gcp_llm`, which targets
> Vertex AI when enabled. Everything is a Google Gemini model — no Azure.

### Remote MCP (Option C)

```env
MCP_SERVER_URL=https://api.githubcopilot.com/mcp/
GITHUB_TOKEN=ghp_...        # PAT, sent as Bearer; scope: repo (or public_repo)
```

## Run

```bash
# Defaults: max 5 iters, blocking+major severities, tester ON
python main.py --repo owner/repo --pr 42

# Tight loop, blocking only, no CI wait
python main.py --repo owner/repo --pr 42 --max-iter 3 --severities blocking --no-tester
```

### Run via ADK tooling

`agent.py` exposes `root_agent`, so `adk run` / `adk web` can discover it. Those
entry points do **not** seed the PR target into session state, so prefer
`main.py` (which seeds `repo_owner` / `repo_name` / `pr_number` before running).

## Notes / not-yet-ported

- **Resume/checkpoint**: the LangGraph version persists to SQLite and supports
  `--resume`. This ADK port uses an in-memory session. Swap
  `InMemorySessionService` for `DatabaseSessionService` to persist.
- **Reviewer on Vertex**: to run the ReAct review loop on Vertex AI too, replace
  the `PRReviewAgent` reuse with a native `google-genai` function-calling loop.
