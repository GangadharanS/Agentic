# Orchestration — Azure Container Apps

Deploy the LangGraph PR orchestrator (`PROrchestrationAgent`) as a Container App alongside ReAct and `github-mcp`.

CI/CD mirrors ReAct:

| Workflow | Purpose |
|----------|---------|
| `orchestration-build-and-push.yml` | Build `ghcr.io/<owner>/pr-orchestrator:latest` |
| `orchestration-deploy-azure.yml` | `az containerapp update` with new image + `MCP_SERVER_URL` |

---

## Prerequisites

- Same Azure resource group / Container Apps environment as ReAct (e.g. `rg-react-pr`)
- **`github-mcp`** Container App running (internal ingress) — see `ReAct/AZURE_DEPLOYMENT.md`
- GitHub Actions secrets: `AZURE_CREDENTIALS` or OIDC trio (same as ReAct deploy)
- GitHub Actions **variables**:

| Variable | Example |
|----------|---------|
| `ORCH_AZURE_RG` | `rg-react-pr` |
| `ORCH_APP_NAME` | `pr-orchestrator` |
| `ORCH_MCP_APP_NAME` | `github-mcp` (optional; default `github-mcp`) |

---

## First-time create (one-time)

Replace placeholders with your values:

```bash
RG=rg-react-pr
ENV_NAME=cae-react-pr          # az containerapp env list -g $RG -o table
LOCATION=eastus
OWNER=gangadharans   # GitHub user/org for GHCR image

az containerapp create \
  -g $RG -n pr-orchestrator --environment $ENV_NAME \
  --image ghcr.io/$OWNER/pr-orchestrator:latest \
  --target-port 8091 \
  --ingress external \
  --min-replicas 0 --max-replicas 2 \
  --cpu 0.5 --memory 1Gi \
  --registry-server ghcr.io \
  --registry-username $OWNER \
  --registry-password "$GITHUB_PAT_WITH_read_packages" \
  --secrets \
    gemini-key="<GEMINI_API_KEY>" \
    github-token="<GITHUB_PAT_repo_scope>" \
  --env-vars \
    PORT=8091 \
    MCP_SERVER_URL=http://github-mcp \
    ORCH_CHECKPOINT_DB=/data/.orchestration_state.db \
    GEMINI_API_KEY=secretref:gemini-key \
    GITHUB_TOKEN=secretref:github-token \
    GEMINI_MODEL=gemini-2.0-flash \
    ORCH_MAX_ITERATIONS=5 \
    ORCH_FIX_SEVERITIES=blocking,major \
    ORCH_TESTER_TIMEOUT=600
```

Optional: mount Azure Files at `/data` so SQLite checkpoints survive restarts.

After the app exists, GitHub Actions **deploy** workflow only updates the image and `MCP_SERVER_URL`.

---

## Trigger a run (HTTP)

The container runs `uvicorn server:app` (wraps the same logic as `python main.py`).

```bash
FQDN=$(az containerapp show -g $RG -n pr-orchestrator --query properties.configuration.ingress.fqdn -o tsv)

curl -s "https://${FQDN}/api/health" | jq .

curl -s -X POST "https://${FQDN}/api/orchestrate" \
  -H 'Content-Type: application/json' \
  -d '{
    "repo": "owner/repo",
    "pr": 42,
    "max_iter": 5,
    "enable_tester": true
  }'
```

Resume from checkpoint:

```bash
curl -s -X POST "https://${FQDN}/api/orchestrate" \
  -H 'Content-Type: application/json' \
  -d '{"repo":"owner/repo","pr":42,"resume":true}'
```

**Note:** A full run can take many minutes (CI polling). Increase Container Apps ingress timeout or run from a client with a long HTTP timeout.

---

## Local Docker smoke test

```bash
docker build -f Orchestration/Dockerfile -t pr-orchestrator:local .
docker run --rm -p 8091:8091 \
  -e GEMINI_API_KEY=... \
  -e GITHUB_TOKEN=... \
  -e MCP_SERVER_URL=http://host.docker.internal:8000 \
  pr-orchestrator:local
```

---

## CLI (unchanged)

Local runs still use:

```bash
cd Orchestration && python main.py --repo owner/repo --pr 42
```
