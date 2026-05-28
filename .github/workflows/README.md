# CI/CD workflows (monorepo)

Each subproject in this repo has its own workflows, prefixed with the project name.
Workflows only fire when files in their own subproject change.

| Project | Workflow files | Triggered by changes in |
|---------|----------------|--------------------------|
| **ReAct** | `react-build-and-push.yml`, `react-deploy-azure.yml` | `ReAct/**`, `mcp_client_app/mcp_client.py` |
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
| `VITE_API_BASE` | Backend FQDN baked into the UI bundle (e.g. `https://react-pr-api.xyz.eastus.azurecontainerapps.io`). Set after the first Azure deploy. |

Set at **Settings → Secrets and variables → Actions → Variables → New repository variable**.

### `react-deploy-azure.yml`

- **Triggers**: automatically after a successful build, or manual run.
- **Action**: `az containerapp update --image …:latest` on both the API and UI apps.
- **Note**: it only **updates** existing Container Apps — the first-time create still goes through `ReAct/AZURE_DEPLOYMENT.md`.

Required GitHub **secrets** (Settings → Secrets and variables → Actions → Secrets):

| Secret | Source |
|--------|--------|
| `AZURE_CLIENT_ID` | `clientId` of the federated SP (see below) |
| `AZURE_TENANT_ID` | Same |
| `AZURE_SUBSCRIPTION_ID` | Same |

Required GitHub **variables** (same screen, Variables tab):

| Variable | Example |
|----------|---------|
| `REACT_AZURE_RG` | `rg-react-pr` |
| `REACT_API_NAME` | `react-pr-api` |
| `REACT_UI_NAME` | `react-pr-ui` |

Setup the federated service principal once:

```bash
# 1. Create the SP scoped to your resource group
az ad sp create-for-rbac \
  --name "github-react-pr-ci" \
  --role contributor \
  --scopes /subscriptions/<SUB_ID>/resourceGroups/<RG_NAME> \
  --json-auth

# 2. Trust your repo's main branch
az ad app federated-credential create --id <clientId> --parameters '{
  "name": "github-main",
  "issuer": "https://token.actions.githubusercontent.com",
  "subject": "repo:<GH_OWNER>/<GH_REPO>:ref:refs/heads/main",
  "audiences": ["api://AzureADTokenExchange"]
}'
```

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
