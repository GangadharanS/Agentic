# CI/CD workflows (monorepo)

Each subproject in this repo has its own workflows, prefixed with the project name.
Workflows only fire when files in their own subproject change.

| Project | Workflow files | Triggered by changes in |
|---------|----------------|--------------------------|
| **ReAct** | `react-build-and-push.yml`, `react-deploy-azure.yml` | `ReAct/**`, `mcp_client_app/mcp_client.py` |
| **Orchestration** | `orchestration-build-and-push.yml`, `orchestration-deploy-azure.yml` | `Orchestration/**`, `ReAct/**`, `mcp_client_app/mcp_client.py` |
| _(future)_ RAG | _e.g._ `rag-build-and-push.yml` | `RAG/**` |
| _(future)_ RAG_LangChain | _e.g._ `rag-langchain-build-and-push.yml` | `RAG_LangChain/**` |

Naming convention: `<project>-<purpose>.yml`. This avoids one workflow rebuilding multiple projects.

---

## ReAct workflows

### `react-build-and-push.yml`

- **Triggers**: push to `main` touching `ReAct/**`, or manual run.
- **Outputs**:
  - `ghcr.io/<owner>/react-pr-api:latest` + `sha-<commit>`
  - `ghcr.io/<owner>/react-pr-ui:latest` + `sha-<commit>`
- **No secrets needed** — uses the built-in `GITHUB_TOKEN` for GHCR.

Optional repository variable:

| Variable | Purpose |
|----------|---------|
| `VITE_API_BASE` | Optional: bake backend URL into the UI bundle instead of nginx proxy. Leave empty if using `BACKEND_URL=http://react-pr-api` on the UI Container App (set automatically by `react-deploy-azure.yml`). |

**UI `/api` proxy:** The UI image must include `nginx.conf.template` + `react-entrypoint.sh`. If `curl https://<ui>/api/health` returns HTML, rebuild the UI image (old GHCR build without the proxy config).

Set at **Settings → Secrets and variables → Actions → Variables → New repository variable**.

### `react-deploy-azure.yml`

- **Triggers**: called automatically from `react-build-and-push.yml` after a successful build on `main`, or manual **Run workflow**.
- **Action**: `az containerapp update --image …:latest` on both the API and UI apps; sets `MCP_SERVER_URL=http://github-mcp` on the API.
- **Note**: uses `workflow_call` (not `workflow_run`) so Azure **secrets** are available. First-time create still goes through `ReAct/AZURE_DEPLOYMENT.md`.

Required GitHub **variables** (Settings → Secrets and variables → Actions → **Variables** tab):

| Variable | Example |
|----------|---------|
| `REACT_AZURE_RG` | `rg-react-pr` |
| `REACT_API_NAME` | `react-pr-api` |
| `REACT_UI_NAME` | `react-pr-ui` |
| `REACT_MCP_APP_NAME` | `github-mcp` (optional; wired to `MCP_SERVER_URL` on the API app) |

Required GitHub **secrets** — use **either** option A or B (Settings → Actions → **Repository secrets**, not Dependabot/Codespaces):

#### Option A — one secret (recommended if OIDC setup is painful)

| Secret | Value |
|--------|--------|
| `AZURE_CREDENTIALS` | Entire JSON file from `az ad sp create-for-rbac ... --sdk-auth` |

```bash
SUB_ID=$(az account show --query id -o tsv)
RG="rg-react-pr"

az ad sp create-for-rbac \
  --name "github-react-pr-deploy" \
  --role contributor \
  --scopes "/subscriptions/${SUB_ID}/resourceGroups/${RG}" \
  --sdk-auth > azure-sp.json

# CLI (repo must match the one that runs Actions)
gh secret set AZURE_CREDENTIALS < azure-sp.json
rm azure-sp.json
```

#### Option B — OIDC (three secrets, no client password)

| Secret | Source |
|--------|--------|
| `AZURE_CLIENT_ID` | `clientId` from SP |
| `AZURE_TENANT_ID` | `tenantId` |
| `AZURE_SUBSCRIPTION_ID` | `subscriptionId` |

Plus federated credential in Entra ID (`subject` must match `repo:<owner>/<repo>:ref:refs/heads/main`).

```bash
gh secret set AZURE_CLIENT_ID -b"<clientId>"
gh secret set AZURE_TENANT_ID -b"<tenantId>"
gh secret set AZURE_SUBSCRIPTION_ID -b"<subscriptionId>"
```

### Secrets “not being set” / login still empty

1. **Wrong tab** — use **Actions → Repository secrets**, not Environment (unless you add `environment:` to the job), Dependabot, or Codespaces.
2. **Wrong repo** — secrets live on the GitHub repo that runs the workflow. Forks do not inherit upstream secrets.
3. **Names** — exact spelling: `AZURE_CREDENTIALS` or `AZURE_CLIENT_ID` (not `AZURE_CLIENT_ID ` with spaces).
4. **Variables vs secrets** — `REACT_AZURE_RG` is a **variable**, not a secret.
5. **Confirm** — after `gh secret set`, run `gh secret list` (names only). Re-run **ReAct — deploy to Azure Container Apps** manually.
6. **Org repo** — if the repo is under an organization, you need permission to add repository secrets (or an org admin must grant the secret to this repo).

---

## Orchestration workflows

### `orchestration-build-and-push.yml`

- **Triggers**: push to `main` touching `Orchestration/**` or `ReAct/**`, or manual run.
- **Output**: `ghcr.io/<owner>/pr-orchestrator:latest` + `sha-<commit>`
- **No Azure secrets** — uses `GITHUB_TOKEN` for GHCR.

### `orchestration-deploy-azure.yml`

- **Triggers**: called automatically from `orchestration-build-and-push.yml` after a successful build on `main`, or manual **Run workflow**.
- **Action**: updates the orchestrator Container App image and sets `MCP_SERVER_URL=http://github-mcp`.
- **Note**: uses `workflow_call` (not `workflow_run`) so Azure **secrets** are available. First-time create: `Orchestration/AZURE_DEPLOYMENT.md`.

GitHub **variables**:

| Variable | Example |
|----------|---------|
| `ORCH_AZURE_RG` | `rg-react-pr` |
| `ORCH_APP_NAME` | `pr-orchestrator` |
| `ORCH_MCP_APP_NAME` | `github-mcp` (optional) |

Uses the same Azure login **secrets** as ReAct (`AZURE_CREDENTIALS` or OIDC trio).

---

## Image tags

- `:latest` — always points at the latest successful build on `main`
- `:sha-<7-char-commit>` — pinnable for rollback

```bash
# Roll back ReAct backend to a specific commit
az containerapp update -g $RG -n react-pr-api \
  --image ghcr.io/<owner>/react-pr-api:sha-abc1234
```

---

## Adding a workflow for another project

Copy `react-build-and-push.yml`, then:

1. Rename to `<project>-build-and-push.yml`
2. Change `name:` to `<Project> — build & push images to GHCR`
3. Update `on.push.paths` to that project's folder
4. Update `BACKEND_IMAGE` / `UI_IMAGE` env vars
5. Update `cache-from`/`cache-to` scopes so caches don't collide
