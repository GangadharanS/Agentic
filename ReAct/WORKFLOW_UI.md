# ReAct PR Review — UI End-to-End Flow (Sequence Diagrams)

How the **React UI** drives a PR review from browser click through FastAPI,
Gemini ReAct loop, and GitHub MCP.

**Stack:** Vite `:5173` → proxy `/api` → FastAPI `:8090` → `ReActAgent` + `MCPClient` → GitHub MCP `:8000`

---

## 1. App startup & health

```mermaid
sequenceDiagram
    actor User
    participant UI as React App<br/>(App.jsx)
    participant API as api.js
    participant Vite as Vite dev proxy<br/>:5173
    participant BE as backend.py<br/>:8090
    participant MCP as GitHub MCP<br/>:8000
    participant GH as GitHub REST API

    User->>UI: Open http://localhost:5173
    UI->>API: health()
    API->>Vite: GET /api/health
    Vite->>BE: GET /api/health
    BE->>MCP: health_check + discover_tools
    MCP-->>BE: OK, tool count
    BE->>GH: github_health (GITHUB_TOKEN)
    GH-->>BE: token OK
    BE-->>Vite: { status, mcp_server, gemini, github }
    Vite-->>API: JSON
    API-->>UI: health payload
    UI->>UI: HealthBadge renders (poll every 15s)
```

---

## 2. PR Review tab — browse repos & PRs (no ReAct yet)

Repo/PR lists use **direct GitHub REST** (`github_api.py`), not MCP.

```mermaid
sequenceDiagram
    actor User
    participant RT as ReviewTab.jsx
    participant API as api.js
    participant BE as backend.py
    participant GH as GitHub REST API

    User->>RT: Open PR Review tab
    RT->>API: listRepos()
    API->>BE: GET /api/repos
    BE->>GH: GET /user/repos (Bearer GITHUB_TOKEN)
    GH-->>BE: repo list
    BE-->>RT: { repos: [...] }

    User->>RT: Select repository
    RT->>API: listPRs(owner, repo, state)
    API->>BE: GET /api/repos/{owner}/{repo}/prs?state=open
    BE->>GH: GET /repos/{owner}/{repo}/pulls
    GH-->>BE: PR list
    BE-->>RT: { prs: [...] }

    User->>RT: Select pull request
    Note over RT: selectedRepo + selectedPR ready for Run ReAct
```

---

## 3. Run ReAct review (main flow, SSE stream)

```mermaid
sequenceDiagram
    actor User
    participant RT as ReviewTab.jsx
    participant API as api.js<br/>reviewStream()
    participant BE as backend.py<br/>review_stream
    participant RA as ReActAgent<br/>react_agent.py
    participant Gemini as Google Gemini
    participant MCP as GitHub MCP
    participant GH as GitHub API<br/>(via MCP tools)

    User->>RT: Click Run ReAct (optional: Post to GitHub)
    RT->>RT: Clear steps, reviewResult, statusLog
    RT->>API: POST /api/review/stream<br/>{ owner, repo, pr_id, post }

    API->>BE: SSE POST /api/review/stream
    BE-->>RT: event: status — Starting review…
    BE->>MCP: discover_tools()
    BE-->>RT: event: status — MCP discovered N tools

    BE->>RA: run(system_prompt, user_message,<br/>tool_filter=allowlist, max_rounds)

    loop ReAct rounds (max 8 default)
        RA->>Gemini: chat.send_message (thought or user kickoff)
        Gemini-->>RA: text + optional function_call

        alt Final answer (no function calls)
            RA-->>BE: { success, text: JSON review, steps[] }
        else Tool call(s)
            RA->>RA: Thought = model text
            RA->>MCP: call_tool(name, args)<br/>e.g. get_pull_request
            MCP->>GH: GitHub REST (tool-specific)
            GH-->>MCP: PR / files / diff / contents
            MCP-->>RA: tool result
            RA->>RA: Observation (truncated ≤8k chars)
            RA->>Gemini: function_response → next round
        end
    end

    loop For each completed step
        BE-->>RT: event: step { round, thought, action,<br/>action_input, observation }
        RT->>RT: ReActSteps.jsx updates
    end

    BE->>BE: parse_json_from_text → comments, summary
    BE-->>RT: event: review { comments, summary, … }
    RT->>RT: ReviewResult.jsx renders

    opt post === true
        BE-->>RT: event: status — Posting review…
        BE->>MCP: create_pull_request_review
        MCP->>GH: POST review + inline comments
        GH-->>MCP: review created
        MCP-->>BE: success
        BE-->>RT: event: posted { review_action, … }
    end

    BE-->>RT: event: done { ok: true }
    RT->>RT: running = false
```

### Typical MCP tool order inside the loop

| Round | Action (example) | Observation |
|-------|------------------|-------------|
| 1 | `get_pull_request` | PR title, branches, body |
| 2 | `get_pull_request_files` | Changed files + patches |
| 3+ | `get_file_contents` / `get_pull_request_diff` | Extra context |
| Last | *(none)* | Final JSON `{ comments, summary }` |

---

## 4. MCP Tools tab — allowlist & test call

```mermaid
sequenceDiagram
    actor User
    participant TT as ToolsTab.jsx
    participant API as api.js
    participant BE as backend.py
    participant MCP as GitHub MCP

    User->>TT: Open MCP Tools tab
    TT->>API: listTools()
    API->>BE: GET /api/mcp/tools
    BE->>MCP: discover_tools (if needed)
    BE-->>TT: tools[] + allowlist + enabled flags

    User->>TT: Toggle tool checkbox
    TT->>API: updateConfig({ tool_allowlist })
    API->>BE: POST /api/mcp/config
    BE->>BE: CONFIG.tool_allowlist updated (in-memory)
    BE-->>TT: new config

    User->>TT: Test tool with JSON args
    TT->>API: testTool(name, args)
    API->>BE: POST /api/mcp/tools/{name}/test
    BE->>MCP: call_tool(name, args)
    MCP-->>BE: raw result
    BE-->>TT: display JSON result
```

---

## 5. Settings tab — runtime config

```mermaid
sequenceDiagram
    actor User
    participant ST as SettingsTab.jsx
    participant API as api.js
    participant BE as backend.py
    participant App as App.jsx

    User->>ST: Open Settings tab
    ST->>API: getConfig()
    API->>BE: GET /api/mcp/config
    BE-->>ST: mcp_server_url, gemini_model,<br/>max_rounds, tool_allowlist

    User->>ST: Edit MCP URL / model / max rounds → Save
    ST->>API: updateConfig({ ... })
    API->>BE: POST /api/mcp/config
    BE->>BE: CONFIG updated (process lifetime)
    BE-->>ST: saved
    ST->>App: onSaved() → refreshHealth()
```

---

## 6. Component ↔ API map

| UI component | API (`api.js`) | Backend route |
|--------------|----------------|---------------|
| `HealthBadge` | `health()` | `GET /api/health` |
| `ReviewTab` | `listRepos`, `listPRs` | `GET /api/repos`, `GET .../prs` |
| `ReviewTab` | `reviewStream` | `POST /api/review/stream` |
| `ReActSteps` | *(SSE `step` events)* | — |
| `ReviewResult` | *(SSE `review` event)* | — |
| `ToolsTab` | `listTools`, `updateConfig`, `testTool` | `GET/POST /api/mcp/*` |
| `SettingsTab` | `getConfig`, `updateConfig` | `GET/POST /api/mcp/config` |

---

## 7. Dev proxy (how `/api` reaches the backend)

```text
Browser  http://localhost:5173/api/health
    ↓  vite.config.js proxy
FastAPI  http://localhost:8090/api/health
```

```6:14:ReAct/ui/vite.config.js
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8090',
        changeOrigin: true,
      },
    },
  },
```

---

## 8. SSE event types (`POST /api/review/stream`)

| Event | When | UI handler |
|-------|------|------------|
| `status` | Start, MCP ready, posting | `statusLog` |
| `step` | After agent completes (per round) | `steps[]` → `ReActSteps` |
| `review` | Parsed JSON review | `reviewResult` → `ReviewResult` |
| `posted` | After `create_pull_request_review` | `statusLog` |
| `error` | Failure | `statusLog` |
| `done` | Stream finished | `statusLog`, `running=false` |

---

## Run locally

```bash
# Terminal 1 — GitHub MCP
docker run -d --name github-mcp -p 8000:8082 \
  -e GITHUB_PERSONAL_ACCESS_TOKEN=$GITHUB_TOKEN \
  ghcr.io/github/github-mcp-server:latest http --port 8082

# Terminal 2 — API
cd ReAct && python backend.py

# Terminal 3 — UI
cd ReAct/ui && npm install && npm run dev
# → http://localhost:5173
```

See also [README.md](README.md) for CLI (`main.py`) and environment variables.
