# Deploy ReAct (UI + backend) to Azure

Two recommended paths. Pick **one**:

| Path | UI hosting | Backend hosting | Best for |
|------|------------|-----------------|----------|
| **A. Quick & cheap** | Azure Static Web Apps (free) | Azure App Service (Linux Python) | Demo, internal tools |
| **B. Container-based** | Azure Container Apps | Azure Container Apps | Production, scale-to-zero |

Both paths assume your **MCP server** (`mcp_client_app` on port 8000) is already reachable from the backend — either deployed to the same Azure environment or exposed publicly. The backend talks to it via `MCP_SERVER_URL`.

---

## Prerequisites

```bash
# Azure CLI
brew install azure-cli         # macOS
az login
az account set --subscription "<YOUR_SUBSCRIPTION_ID>"

# A resource group (one-time)
az group create -n rg-react-pr -l eastus
```

You also need:
- A `GEMINI_API_KEY` (https://aistudio.google.com/apikey)
- A `GITHUB_TOKEN` with `repo` scope
- An `MCP_SERVER_URL` — public URL of your MCP server (or internal if both run in Container Apps)

---

## Path A — App Service + Static Web Apps

### A1. Deploy the backend (FastAPI) to App Service

```bash
# From the repo root (Agentic/)
RG=rg-react-pr
PLAN=plan-react-pr
APP=react-pr-api-$RANDOM        # must be globally unique
LOCATION=eastus

az appservice plan create -g $RG -n $PLAN --is-linux --sku B1
az webapp create -g $RG -p $PLAN -n $APP --runtime "PYTHON:3.11"

# Set app settings (env vars)
az webapp config appsettings set -g $RG -n $APP --settings \
  GEMINI_API_KEY="..." \
  GEMINI_MODEL="gemini-2.0-flash" \
  GITHUB_TOKEN="ghp_..." \
  MCP_SERVER_URL="https://your-mcp-server.example.com" \
  REACT_MAX_ROUNDS=8 \
  SCM_DO_BUILD_DURING_DEPLOYMENT=true

# Tell App Service which file to run — backend.py lives in ReAct/.
# Easiest: zip the ReAct/ folder + mcp_client.py and deploy.
mkdir -p /tmp/react-pr-deploy/mcp_client_app
cp -R ReAct/* /tmp/react-pr-deploy/
cp mcp_client_app/mcp_client.py /tmp/react-pr-deploy/mcp_client_app/

# App Service expects a startup command — use uvicorn directly.
az webapp config set -g $RG -n $APP \
  --startup-file "uvicorn backend:app --host 0.0.0.0 --port 8000"

# Bundle and deploy
cd /tmp/react-pr-deploy && zip -r ../react-pr.zip . && cd -
az webapp deploy -g $RG -n $APP --src-path /tmp/react-pr.zip --type zip
```

After deployment, verify:

```bash
curl https://$APP.azurewebsites.net/api/health
```

Note the URL — you'll use it for the UI proxy.

### A2. Deploy the UI to Azure Static Web Apps

**Option 1 — Linked backend (cleanest, no CORS):**

1. In Azure Portal → create a **Static Web App** (free tier).
2. Source: **Other** (or your GitHub repo if you push there).
3. Build settings:
   - App location: `ReAct/ui`
   - Output location: `dist`
   - Build command: `npm run build`
4. After it's created, go to **APIs → Link an existing API** and link the App Service from A1. SWA will route `/api/*` to it automatically — no `VITE_API_BASE` needed.

**Option 2 — Public proxy via `staticwebapp.config.json`:**

Edit `ReAct/ui/staticwebapp.config.json` and replace `REPLACE-WITH-BACKEND.azurewebsites.net` with your App Service hostname, then deploy:

```bash
npm install -g @azure/static-web-apps-cli
cd ReAct/ui
npm run build
swa deploy ./dist --env production
```

Either way, **enable CORS** on the App Service (so the SWA domain can call it):

```bash
az webapp cors add -g $RG -n $APP --allowed-origins "https://<YOUR-SWA-HOST>.azurestaticapps.net"
```

---

## Path B — Container Apps (both)

### B1. Build & push the images

```bash
RG=rg-react-pr
ACR=acrreactpr$RANDOM          # globally unique, lowercase
LOCATION=eastus

az acr create -g $RG -n $ACR --sku Basic --admin-enabled true
az acr login -n $ACR

# Build the backend (Dockerfile is at ReAct/Dockerfile but its COPY paths
# are relative to the repo root, so run from Agentic/).
docker build -t $ACR.azurecr.io/react-pr-api:latest -f ReAct/Dockerfile .
docker push $ACR.azurecr.io/react-pr-api:latest

# Build the UI (Dockerfile at ReAct/ui/Dockerfile is self-contained).
# Pass the backend URL at build time — or leave empty and use nginx env subst.
docker build -t $ACR.azurecr.io/react-pr-ui:latest ReAct/ui
docker push $ACR.azurecr.io/react-pr-ui:latest
```

### B2. Create a Container Apps environment

```bash
ENV=cae-react-pr
az containerapp env create -g $RG -n $ENV -l $LOCATION
```

### B3. Deploy the backend

```bash
ACR_PASS=$(az acr credential show -n $ACR --query passwords[0].value -o tsv)

az containerapp create \
  -g $RG -n react-pr-api --environment $ENV \
  --image $ACR.azurecr.io/react-pr-api:latest \
  --registry-server $ACR.azurecr.io \
  --registry-username $ACR \
  --registry-password $ACR_PASS \
  --target-port 8090 \
  --ingress external \
  --min-replicas 0 --max-replicas 3 \
  --secrets gemini-key="..." github-token="ghp_..." \
  --env-vars \
    GEMINI_API_KEY=secretref:gemini-key \
    GITHUB_TOKEN=secretref:github-token \
    GEMINI_MODEL=gemini-2.0-flash \
    MCP_SERVER_URL="https://your-mcp-server.example.com" \
    REACT_MAX_ROUNDS=8 \
    PORT=8090

API_URL=$(az containerapp show -g $RG -n react-pr-api --query properties.configuration.ingress.fqdn -o tsv)
echo "Backend at: https://$API_URL"
```

### B4. Deploy the UI

The UI's `nginx.conf` proxies `/api/*` to `$BACKEND_URL`. Build the UI image with the backend URL baked in:

```bash
docker build -t $ACR.azurecr.io/react-pr-ui:latest \
  --build-arg VITE_API_BASE="https://$API_URL" \
  ReAct/ui
docker push $ACR.azurecr.io/react-pr-ui:latest

az containerapp create \
  -g $RG -n react-pr-ui --environment $ENV \
  --image $ACR.azurecr.io/react-pr-ui:latest \
  --registry-server $ACR.azurecr.io \
  --registry-username $ACR \
  --registry-password $ACR_PASS \
  --target-port 80 \
  --ingress external \
  --min-replicas 1 --max-replicas 2

UI_URL=$(az containerapp show -g $RG -n react-pr-ui --query properties.configuration.ingress.fqdn -o tsv)
echo "UI at: https://$UI_URL"
```

If you prefer **internal-only** backend (private to the env), set `--ingress internal` on the API and have the UI's nginx use `http://react-pr-api` as the upstream. Container Apps DNS resolves sibling apps by name inside the env.

---

## Hooking up the GitHub MCP server

The backend now uses **GitHub's official MCP server** (`github/github-mcp-server`). Three options:

### Option 1 — Self-host as a Container App (recommended)

Deploy the official image into the same Container Apps environment with internal-only ingress:

```bash
az containerapp create \
  -g $RG -n github-mcp --environment $ENV_NAME \
  --image ghcr.io/github/github-mcp-server:latest \
  --target-port 8082 \
  --ingress internal \
  --min-replicas 0 --max-replicas 2 \
  --secrets gh-pat="<GITHUB_PAT_with_repo_scope>" \
  --env-vars GITHUB_PERSONAL_ACCESS_TOKEN=secretref:gh-pat \
  --command "/server/github-mcp-server" \
  --args "http" "--port" "8082"
```

Then on the **backend Container App**, set `MCP_SERVER_URL=http://github-mcp`. The backend's Streamable HTTP client will hit `POST /mcp` on that internal hostname and forward `GITHUB_TOKEN` as a Bearer header.

### Option 2 — GitHub-hosted remote MCP

Skip hosting entirely:

```bash
az containerapp update -g $RG -n $API_NAME --set-env-vars \
  MCP_SERVER_URL="https://api.githubcopilot.com/mcp/" \
  MCP_AUTH_TOKEN=secretref:github-token
```

Most endpoints require a GitHub Copilot subscription. If you have one, this is the zero-infra option.

### Option 3 — Your existing custom MCP server

If you still want `mcp_client_app`'s custom tools (e.g. `analyze_pr_logic_changes`), deploy it the same way as Option 1 and set `MCP_SERVER_URL=http://mcp-client-app`. You'll need to revert `ReAct/prompts.py` to the custom tool names — see the git history of `prompts.py` for the previous version.

---

## Secrets management (production)

Replace inline secrets with Azure Key Vault references:

```bash
# Create a Key Vault, store the secret
az keyvault create -g $RG -n kv-react-pr -l $LOCATION
az keyvault secret set --vault-name kv-react-pr -n gemini-key --value "..."

# Grant the web app a managed identity + read access to KV
az webapp identity assign -g $RG -n $APP
PRINCIPAL=$(az webapp identity show -g $RG -n $APP --query principalId -o tsv)
az keyvault set-policy -n kv-react-pr --object-id $PRINCIPAL --secret-permissions get

# Reference it from app settings
az webapp config appsettings set -g $RG -n $APP --settings \
  GEMINI_API_KEY="@Microsoft.KeyVault(SecretUri=https://kv-react-pr.vault.azure.net/secrets/gemini-key/)"
```

---

## CI/CD (optional)

Add a GitHub Action at `.github/workflows/azure-deploy.yml`:

```yaml
on:
  push:
    branches: [main]
    paths: ['ReAct/**', 'mcp_client_app/mcp_client.py']

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: azure/login@v2
        with:
          creds: ${{ secrets.AZURE_CREDENTIALS }}
      - name: Build & push API
        run: |
          az acr login -n ${{ secrets.ACR_NAME }}
          docker build -t ${{ secrets.ACR_NAME }}.azurecr.io/react-pr-api:${{ github.sha }} -f ReAct/Dockerfile .
          docker push ${{ secrets.ACR_NAME }}.azurecr.io/react-pr-api:${{ github.sha }}
      - name: Update Container App
        run: |
          az containerapp update -g rg-react-pr -n react-pr-api \
            --image ${{ secrets.ACR_NAME }}.azurecr.io/react-pr-api:${{ github.sha }}
```

---

## Verifying the deployment

```bash
# Backend
curl https://<api-host>/api/health

# Expect:
# {
#   "status": "ok",
#   "mcp_server": {"url": "...", "connected": true, "tools": 40+},
#   "gemini": {"configured": true, "model": "gemini-2.0-flash"},
#   "github": {"ok": true, "login": "<your-user>"}
# }
```

Then open the UI URL — header should show three green dots.

---

## Cost notes (May 2026 pricing, approximate)

| Service | Tier | Monthly |
|---------|------|---------|
| App Service B1 (Linux) | Basic | ~$13 |
| Static Web Apps | Free | $0 |
| Container Apps (consumption, scale-to-zero) | — | ~$0–$10 for light use |
| ACR Basic | — | ~$5 |

For demos use **Path A** with App Service F1 (free) — but F1 doesn't support `Always On`, so cold starts are slow. B1 is the cheapest tier that runs continuously.
