# Orchestration_A2A

Multi-agent PR review/fix/push workflow using a lightweight **A2A-style protocol**.

This folder mirrors `Orchestration/` but replaces LangGraph node calls with HTTP
A2A messages:

```text
Supervisor (A2A client) — owns NO workflow graph
  ├─ discovers Agent Cards
  ├─ sends shared PR state via JSON-RPC `message/send`
  ├─ polls `tasks/get` until the task is completed/failed
  └─ follows whichever agent the result advertises in `next_agent`

A2A agent servers — each decides its own next hop
  ├─ init     → resolve PR metadata + fork strategy   (→ reviewer)
  ├─ reviewer → ReAct PR review via GitHub MCP         (→ fixer | pusher)
  ├─ fixer    → Gemini rewrite + MCP commit            (→ tester | pusher)
  ├─ tester   → poll CI checks through MCP             (→ reviewer | fixer | pusher)
  └─ pusher   → summary review + optional stacked PR   (→ END)
```

See **[WORKFLOW.md](WORKFLOW.md)** for sequence diagrams, the supervisor driver
loop, shared-state fields, and failure modes.

## What is different from `Orchestration/`?

| Area | `Orchestration/` | `Orchestration_A2A/` |
|------|------------------|----------------------|
| Agent communication | In-process LangGraph node calls | HTTP A2A JSON-RPC calls |
| Agent identity | Python functions | Agent Card + HTTP endpoint |
| Shared state | LangGraph state | JSON state artifact in A2A task responses |
| Task lifecycle | Synchronous return | `submitted → working → completed/failed`, polled via `tasks/get` |
| Routing | `StateGraph` conditional edges (central) | Decentralized: each agent advertises `next_agent`; supervisor just follows it |
| Checkpoint | LangGraph SQLite / memory | JSON checkpoint per `thread_id` |

The actual agent logic is intentionally the same: it reuses the ReAct reviewer,
GitHub MCP calls, Gemini fixer, CI tester, and pusher behavior.

## Files

```text
Orchestration_A2A/
├── a2a_types.py       # minimal Agent Card / task / message shapes
├── a2a_server.py      # FastAPI JSON-RPC adapter for one agent
├── a2a_client.py      # supervisor-side JSON-RPC client
├── agent_cards.py     # five Agent Cards + default local ports
├── agent_apps.py      # wraps existing node logic as A2A handlers (+ next_agent)
├── run_agents.py      # starts all five local A2A servers
├── orchestrator.py    # generic A2A task driver (no workflow graph)
├── main.py            # CLI
├── WORKFLOW.md        # sequence diagrams + end-to-end flow
├── state.py           # shared PR state schema (incl. next_agent)
├── state_utils.py     # state merge/checkpoint helpers
└── agents/
    ├── routing.py     # per-agent next-hop decisions (the only routing code)
    ├── init_agent.py / init_server.py
    ├── reviewer_agent.py / reviewer_server.py
    ├── fixer_agent.py / fixer_server.py
    ├── tester_agent.py / tester_server.py
    └── pusher_agent.py / pusher_server.py
```

## Setup

```bash
cd Orchestration_A2A
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`:

```env
GEMINI_API_KEY=...
GITHUB_TOKEN=...
MCP_SERVER_URL=http://localhost:8000
GEMINI_MODEL=gemini-2.5-flash
```

Make sure GitHub MCP is reachable, same as `Orchestration/` and `ReAct/`.

## Run locally

Terminal 1 — start the five A2A agent servers:

```bash
cd Orchestration_A2A
source .venv/bin/activate
python run_agents.py
```

Default local endpoints:

| Agent | URL |
|-------|-----|
| init | `http://127.0.0.1:9101` |
| reviewer | `http://127.0.0.1:9102` |
| fixer | `http://127.0.0.1:9103` |
| tester | `http://127.0.0.1:9104` |
| pusher | `http://127.0.0.1:9105` |

Terminal 2 — run the supervisor:

```bash
cd Orchestration_A2A
source .venv/bin/activate
python main.py --repo owner/repo --pr 42
```

Other examples:

```bash
python main.py --repo owner/repo --pr 42 --max-iter 3
python main.py --repo owner/repo --pr 42 --severities blocking
python main.py --repo owner/repo --pr 42 --no-tester
python main.py --repo owner/repo --pr 42 --resume
```

## A2A discovery

Each server exposes:

```text
GET  /.well-known/agent-card.json
POST /a2a            # JSON-RPC: message/send, tasks/get
GET  /health
```

Example:

```bash
curl http://127.0.0.1:9102/.well-known/agent-card.json
```

The supervisor reads the five URLs from:

```env
A2A_INIT_URL=http://127.0.0.1:9101
A2A_REVIEWER_URL=http://127.0.0.1:9102
A2A_FIXER_URL=http://127.0.0.1:9103
A2A_TESTER_URL=http://127.0.0.1:9104
A2A_PUSHER_URL=http://127.0.0.1:9105
```

## Protocol shape

1. The supervisor submits the PR state with `message/send`:

```json
{
  "jsonrpc": "2.0",
  "method": "message/send",
  "params": {
    "id": "pr-42:reviewer:2",
    "message": {
      "role": "user",
      "parts": [
        {"kind": "text", "text": "Run reviewer step..."},
        {"kind": "data", "mimeType": "application/vnd.agentic.pr-state+json", "data": {"repo_owner": "..."}}
      ]
    }
  }
}
```

2. The agent immediately returns a non-terminal task and runs the skill in the
   background:

```json
{ "id": "pr-42:reviewer:2", "status": {"state": "submitted"}, "artifacts": [] }
```

3. The supervisor polls `tasks/get` (`{"id": "pr-42:reviewer:2"}`) until the
   task is `completed` (or `failed`). The completed task carries the updated
   state, including the agent's own `next_agent` routing decision:

```json
{
  "id": "pr-42:reviewer:2",
  "status": {"state": "completed"},
  "artifacts": [
    {
      "name": "reviewer-state",
      "parts": [
        {"kind": "text", "text": "pr-reviewer-agent completed"},
        {"kind": "data", "mimeType": "application/vnd.agentic.pr-state+json",
         "data": {"next_action": "fix", "next_agent": "fixer"}}
      ]
    }
  ]
}
```

## Routing (decentralized)

There is **no workflow graph in the supervisor**. It is a generic driver:

```text
current = init
while current is not None:
    state   = call(current, state)   # send + poll tasks/get to completion
    current = state["next_agent"]     # whatever that agent advertised
```

Each agent owns only its own next hop (`agents/routing.py`). The familiar shape
is an emergent result of those local decisions:

```text
init      -> reviewer                       (pusher if init fails fatally)
reviewer  -- fix ------------------------> fixer
reviewer  -- push_* ---------------------> pusher
fixer     -- ok -------------------------> tester     (pusher if fix failed/maxed)
tester    -- tests_pass/tests_skip ------> reviewer
tester    -- tests_fail, iter < max -----> fixer
tester    -- tests_fail, iter >= max ----> pusher
pusher    -> END
```

A step budget in the supervisor guards against a misbehaving routing decision
looping forever.

## Checkpoints

After every A2A call, the supervisor writes JSON to:

```text
.a2a_checkpoints/pr-<N>.json
```

Resume with:

```bash
python main.py --repo owner/repo --pr 42 --resume
```

## Notes

- This is an HTTP A2A local mesh, not LangGraph and not ADK.
- It intentionally reuses `ReAct/PRReviewAgent` and `ReAct/mcp_bridge.py`.
- Write operations still go through GitHub MCP (`create_or_update_file`,
  `create_pull_request_review`, `create_pull_request`).
- For fork PRs, fixes are written to `ai-fixes/pr-<N>` and the pusher opens a
  stacked PR in the base repo, same as `Orchestration/`.
