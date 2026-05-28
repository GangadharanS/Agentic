# ReAct — GitHub PR Review (Gemini + MCP) with React UI

Review any GitHub pull request through a **ReAct loop** (Reason → Act → Observe) powered by **Google Gemini** and your existing **MCP server**. Ships with a React UI for browsing repos/PRs and configuring the agent.

## Architecture

```
React UI (Vite, :5173)
    ↓  /api/* (proxy)
FastAPI backend (:8090)              ┌─ direct GitHub REST API (list repos/PRs)
    ├─ ReActAgent (Gemini 2.0 Flash) │
    │       ↓ function calling        ↓
    └─ MCPClient → GitHub MCP server → GitHub PR tools
                  (github/github-mcp-server)
```

Uses [GitHub's official MCP server](https://github.com/github/github-mcp-server) — either self-hosted (Docker) or the remote `api.githubcopilot.com/mcp/`. The repo/PR list in the UI is fetched directly from the GitHub REST API (independent of MCP).

- **UI** lets the user pick a repo → pick a PR → run a ReAct review.
- **MCP Tools tab** lists every tool the MCP server exposes; you can enable/disable any tool for the agent and test calls.
- **Settings tab** changes the MCP URL, Gemini model, and max rounds at runtime.

## Folder layout

```
ReAct/
├── backend.py              # FastAPI for the UI
├── github_api.py           # GitHub REST for repo/PR listing
├── react_agent.py          # ReAct loop (Gemini + MCP tools)
├── pr_reviewer.py          # PR review orchestration + post review
├── prompts.py              # System prompts + default tool allowlist
├── mcp_bridge.py           # Imports MCPClient from ../mcp_client_app/
├── main.py                 # CLI version (same agent, no UI)
├── requirements.txt
├── .env.example
└── ui/                     # React + Vite app
    ├── index.html
    ├── vite.config.js
    ├── package.json
    └── src/
        ├── App.jsx
        ├── api.js
        ├── styles.css
        ├── main.jsx
        └── components/
            ├── HealthBadge.jsx
            ├── ReviewTab.jsx
            ├── ReActSteps.jsx
            ├── ReviewResult.jsx
            ├── ToolsTab.jsx
            └── SettingsTab.jsx
```

## Prerequisites

1. **GitHub MCP server**. Pick one:

   **Self-host (recommended):**
   ```bash
   docker rm -f github-mcp 2>/dev/null
   docker run -d --name github-mcp -p 8000:8082 \
     -e GITHUB_PERSONAL_ACCESS_TOKEN=$GITHUB_TOKEN \
     ghcr.io/github/github-mcp-server:latest http --port 8082
   ```
   Set `MCP_SERVER_URL=http://localhost:8000`.

   **Or use GitHub's hosted MCP** (requires GitHub Copilot subscription on most endpoints):
   `MCP_SERVER_URL=https://api.githubcopilot.com/mcp/`. The PAT is sent as a Bearer token automatically.

2. **Gemini API key** (free): https://aistudio.google.com/apikey

3. **GitHub token** with `repo` scope. The backend uses it to list repos/PRs and (when using the remote MCP) to authenticate MCP calls.

## Setup

```bash
cd ReAct
pip install -r requirements.txt
cp .env.example .env
# Edit .env — set GEMINI_API_KEY and GITHUB_TOKEN
```

Edit `ReAct/.env`:

```bash
GEMINI_API_KEY=your-gemini-key
GEMINI_MODEL=gemini-2.0-flash
GITHUB_TOKEN=ghp_your_token
MCP_SERVER_URL=http://localhost:8000
REACT_BACKEND_PORT=8090
```

## Run

**Backend** (terminal 1):

```bash
cd ReAct
python backend.py
# → http://localhost:8090
```

**UI** (terminal 2):

```bash
cd ReAct/ui
npm install
npm run dev
# → http://localhost:5173
```

Open `http://localhost:5173`:

- **PR Review** — pick a repo, pick a PR, click **Run ReAct**. The UI streams Thought → Action → Observation rounds as Gemini reasons.
- **MCP Tools** — every MCP tool with checkbox to add/remove from the agent allowlist; expand to view JSON schema and call the tool with custom args.
- **Settings** — change MCP URL, Gemini model, max ReAct rounds without restarting.

## CLI (no UI)

The original CLI still works:

```bash
cd ReAct
python main.py --repo owner/repo --pr 123
python main.py --repo owner/repo --pr 123 --post
```

## REST API (backend)

| Method | Path | Purpose |
|--------|------|---------|
| GET    | `/api/health` | MCP / Gemini / GitHub status |
| GET    | `/api/repos` | List repos accessible to GITHUB_TOKEN |
| GET    | `/api/repos/{owner}/{repo}/prs?state=open\|closed\|all` | List PRs |
| GET    | `/api/repos/{owner}/{repo}/prs/{pr}` | PR summary |
| POST   | `/api/review` | Run ReAct review (sync) |
| POST   | `/api/review/stream` | Run ReAct review (SSE) |
| GET    | `/api/mcp/tools` | List MCP tools + allowlist |
| GET    | `/api/mcp/config` | Read runtime config |
| POST   | `/api/mcp/config` | Update runtime config |
| POST   | `/api/mcp/tools/{name}/test` | Call any MCP tool directly |

## Default ReAct tool allowlist (GitHub MCP)

| Tool | Used for |
|------|----------|
| `get_pull_request` | PR metadata |
| `get_pull_request_files` | Changed files + patches |
| `get_pull_request_diff` | Full unified diff |
| `get_file_contents` | Full file context |
| `list_pull_requests` | Browsing PRs from inside the agent |
| `create_pull_request_review` | Posting review (used by `--post`) |

Toggle any other MCP tool on the **MCP Tools** tab to expose it to the agent. The agent never sees disabled tools.
