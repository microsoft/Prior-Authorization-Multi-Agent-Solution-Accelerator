# Deployment Guide

## Overview

This guide walks you through deploying the **Prior Authorization Review — Multi-Agent Solution Accelerator** to Azure. The deployment supports three paths: **Local Development** (Docker Compose), **Azure Cloud** (Azure Container Apps via CLI), and **Azure Cloud** (Azure Developer CLI / `azd`). Local deployment takes approximately 5 minutes; cloud deployment takes approximately 15–20 minutes including infrastructure provisioning.

> 🆘 **Need Help?** If you encounter any issues during deployment, check our [Troubleshooting Guide](./troubleshooting.md) for solutions to common problems.

---

## Step 1: Prerequisites & Setup

### 1.1 Azure Account Requirements

Ensure you have access to an [Azure subscription](https://azure.microsoft.com/free/) with the following permissions:

| Role | Scope | Purpose |
|------|-------|---------|
| Contributor | Subscription level | Create and manage Azure resources |
| User Access Administrator | Subscription level | Manage user access and role assignments |

> 🔍 **How to Check Your Permissions:**
>
> 1. Go to [Azure Portal](https://portal.azure.com/)
> 2. Navigate to **Subscriptions** (search for "subscriptions" in the top search bar)
> 3. Click on your target subscription
> 4. In the left menu, click **Access control (IAM)**
> 5. Scroll down to verify your assigned roles include **Contributor** and **User Access Administrator**

### 1.2 Required Software

| Tool | Version | Required For | Installation |
|------|---------|-------------|-------------|
| Python | 3.11+ | Backend (local dev) | [python.org](https://www.python.org/downloads/) |
| Node.js | 18+ | Frontend (local dev) | [nodejs.org](https://nodejs.org/) |
| Docker Desktop | Latest | Container builds | [docker.com](https://www.docker.com/products/docker-desktop/) |
| Azure CLI | Latest | Cloud deployment | [Install Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli) |
| Azure Developer CLI (azd) | 1.18.0+ | Cloud deployment (recommended) | [Install azd](https://learn.microsoft.com/en-us/azure/developer/azure-developer-cli/install-azd) |
| Git | Latest | Repository clone | [git-scm.com](https://git-scm.com/) |

### 1.3 Check Service Availability & Quota

> ⚠️ **CRITICAL:** Before proceeding with cloud deployment, ensure your chosen Azure region has all required services available.

**Required Azure Services:**

| Service | Purpose | Pricing |
|---------|---------|---------|
| [Azure AI Foundry](https://learn.microsoft.com/en-us/azure/ai-foundry/) | Claude Sonnet 4.6 model inference | [Pricing](https://azure.microsoft.com/en-us/pricing/details/ai-foundry/) |
| [Azure Container Apps](https://learn.microsoft.com/en-us/azure/container-apps/) | Hosting backend and frontend containers | [Pricing](https://azure.microsoft.com/en-us/pricing/details/container-apps/) |
| [Azure Container Registry](https://learn.microsoft.com/en-us/azure/container-registry/) | Storing Docker images | [Pricing](https://azure.microsoft.com/en-us/pricing/details/container-registry/) |
| [Azure Application Insights](https://learn.microsoft.com/en-us/azure/azure-monitor/app/app-insights-overview) | Observability and tracing (optional) | [Pricing](https://azure.microsoft.com/en-us/pricing/details/monitor/) |

**Recommended Regions:** East US, East US 2, West US 2, West Europe, Sweden Central

> 🔍 **Check Availability:** Use [Azure Products by Region](https://azure.microsoft.com/en-us/explore/global-infrastructure/products-by-region/) to verify service availability in your chosen region.

### 1.4 Claude Model Quota Check

> 💡 **RECOMMENDED:** Verify that your Azure AI Foundry account has access to Claude Sonnet 4.6 before deployment.

**Steps to verify:**

1. Go to [Azure AI Foundry](https://ai.azure.com/)
2. Navigate to your project → **Model catalog**
3. Search for **Claude Sonnet 4.6** (model ID: `claude-sonnet-4-6`)
4. Verify the model is available in your selected region
5. Note your **API key** and **endpoint URL** — you'll need these in Step 3

> 📖 **Learn More:** See [Microsoft AI Foundry Claude Models](https://learn.microsoft.com/en-us/azure/ai-foundry/foundry-models/how-to/use-foundry-models-claude) for setup instructions.

---

## Step 2: Choose Your Deployment Environment

Select one of the following options to deploy the solution:

### Environment Comparison

| Environment | Best For | Requirements | Setup Time |
|-------------|----------|-------------|------------|
| **Docker Compose** | Quick local demo, development | Docker Desktop | ~5 minutes |
| **Local (no Docker)** | Development with hot reload | Python 3.11+, Node.js 18+ | ~10 minutes |
| **Azure Container Apps (azd)** | Cloud deployment (recommended) | Azure subscription, azd 1.18.0+ | ~10 minutes |
| **Azure Container Apps (CLI)** | Cloud deployment, manual control | Azure subscription, Azure CLI | ~15–20 minutes |

> 💡 **Recommendation:** For cloud deployment, use **`azd up`** — a single command that provisions infrastructure and deploys both containers. For local development, start with **Docker Compose**.

---

## Step 3: Configure Environment

### 3.1 Clone the Repository

```bash
git clone https://github.com/amitmukh/prior-auth-maf.git
cd prior-auth-maf
```

### 3.2 Set Environment Variables

Create a `backend/.env` file with your Microsoft AI Foundry credentials:

```env
AZURE_FOUNDRY_API_KEY=your-azure-foundry-api-key
AZURE_FOUNDRY_ENDPOINT=https://your-endpoint.services.ai.azure.com
CLAUDE_MODEL=claude-sonnet-4-6

# Skills-based approach (default: true)
USE_SKILLS=true

# Azure Application Insights (optional)
APPLICATION_INSIGHTS_CONNECTION_STRING=InstrumentationKey=...;IngestionEndpoint=...
```

### 3.3 MCP Server Configuration (Optional)

The MCP server endpoints are pre-configured with defaults. Override them only if you're using custom or self-hosted MCP servers:

| Environment Variable | Default Endpoint | Provider | Purpose |
|---------------------|------------------|----------|---------|
| `MCP_NPI_REGISTRY` | `https://mcp.deepsense.ai/npi_registry/mcp` | DeepSense | Provider NPI validation |
| `MCP_ICD10_CODES` | `https://mcp.deepsense.ai/icd10_codes/mcp` | DeepSense | Diagnosis code lookup |
| `MCP_CMS_COVERAGE` | `https://mcp.deepsense.ai/cms_coverage/mcp` | DeepSense | Medicare LCD/NCD policies |
| `MCP_CLINICAL_TRIALS` | `https://mcp.deepsense.ai/clinical_trials/mcp` | DeepSense | Clinical trial search |
| `MCP_PUBMED` | `https://pubmed.mcp.claude.com/mcp` | Anthropic | PubMed literature search |

---

## Step 4: Deploy the Solution

### Option A: Docker Compose (Recommended for Quick Start)

<details open>
<summary><b>Deploy with Docker Compose</b></summary>

**4A.1 Build and start containers:**

```bash
docker compose up --build
```

**4A.2 Verify deployment:**

| Service | URL | Expected Response |
|---------|-----|-------------------|
| Frontend | http://localhost:3000 | Application UI loads |
| Backend health | http://localhost:8000/health | `{"status": "healthy"}` |

**4A.3 Container details:**

The `docker-compose.yml` reads your `backend/.env` file and maps credentials:

| Your `.env` variable | Maps to (container) | Purpose |
|----------------------|---------------------|---------|
| `AZURE_FOUNDRY_API_KEY` | `ANTHROPIC_FOUNDRY_API_KEY` | Microsoft AI Foundry auth |
| `AZURE_FOUNDRY_ENDPOINT` | `ANTHROPIC_FOUNDRY_BASE_URL` | Foundry endpoint URL |
| (set automatically) | `CLAUDE_CODE_USE_FOUNDRY=true` | Enables Foundry mode |

> ⏱️ **Expected Duration:** ~2 minutes for initial build, ~30 seconds for subsequent starts.

</details>

### Option B: Local Development (Without Docker)

<details>
<summary><b>Deploy locally with hot reload</b></summary>

**4B.1 Backend setup:**

```bash
cd backend

# Create and activate virtual environment
python -m venv .venv

# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

**4B.2 Frontend setup:**

```bash
cd frontend
npm install

# Configure environment (optional — defaults work for local dev)
cp .env.example .env.local
```

**4B.3 Start both servers (in separate terminals):**

**Backend** (runs on port 8000):
```bash
cd backend
uvicorn app.main:app --reload
```

**Frontend** (runs on port 3000):
```bash
cd frontend
cp .env.example .env.local   # sets NEXT_PUBLIC_API_BASE=http://localhost:8000/api
npm run dev
```

**4B.4 Verify deployment:**

Open `http://localhost:3000` in your browser.

> **Note:** The frontend calls the backend directly (not through a Next.js rewrite proxy) because multi-agent reviews take 3–5 minutes — longer than the dev server proxy's default timeout.

</details>

### Option C: Azure Container Apps via azd (Recommended for Cloud)

<details>
<summary><b>Deploy with Azure Developer CLI (azd)</b></summary>

> **Prerequisites:** [Azure Developer CLI (azd) 1.18.0+](https://learn.microsoft.com/en-us/azure/developer/azure-developer-cli/install-azd) and an Azure subscription.

**4C.1 Authenticate with Azure:**

```bash
azd auth login
```

**4C.2 Initialize and deploy (single command):**

```bash
azd up
```

This will:
1. Prompt you for an **environment name** (e.g., `prior-auth-dev`)
2. Prompt you for an **Azure region** (e.g., `eastus`)
3. Prompt you for **Azure Foundry API key** and **endpoint**
4. Provision all Azure resources (Container Registry, Container Apps Environment, Log Analytics, Application Insights)
5. Build and push Docker images to Azure Container Registry
6. Deploy both backend and frontend Container Apps
7. Display the frontend URL when complete

**4C.3 Set Azure Foundry credentials (if not set during `azd up`):**

```bash
azd env set AZURE_FOUNDRY_API_KEY <your-api-key>
azd env set AZURE_FOUNDRY_ENDPOINT https://<resource>.services.ai.azure.com/anthropic
azd up
```

**4C.4 View deployed resources:**

```bash
azd show
```

> ⏱️ **Expected Duration:** ~10 minutes for initial provisioning + deployment.

</details>

### Option D: Azure Container Apps via CLI (Manual)

<details>
<summary><b>Deploy to Azure Container Apps</b></summary>

**4C.1 Authenticate with Azure:**

```bash
az login
```

For specific tenants:
```bash
az login --tenant-id <tenant-id>
```

**4C.2 Create a Resource Group:**

```bash
az group create \
  --name prior-auth-rg \
  --location eastus
```

**4C.3 Create Azure Container Registry:**

```bash
az acr create \
  --name priorauthacr \
  --resource-group prior-auth-rg \
  --sku Basic \
  --admin-enabled true
```

**4C.4 Build and push container images:**

```bash
# Build backend image
az acr build \
  --registry priorauthacr \
  --image prior-auth-backend:latest \
  --file backend/Dockerfile ./backend

# Build frontend image
az acr build \
  --registry priorauthacr \
  --image prior-auth-frontend:latest \
  --file frontend/Dockerfile ./frontend
```

**4C.5 Create Container Apps Environment:**

```bash
az containerapp env create \
  --name prior-auth-env \
  --resource-group prior-auth-rg \
  --location eastus
```

**4C.6 Deploy the backend (internal ingress):**

```bash
az containerapp create \
  --name prior-auth-backend \
  --resource-group prior-auth-rg \
  --environment prior-auth-env \
  --image priorauthacr.azurecr.io/prior-auth-backend:latest \
  --registry-server priorauthacr.azurecr.io \
  --target-port 8000 \
  --ingress internal \
  --min-replicas 1 \
  --max-replicas 3 \
  --cpu 1 --memory 2Gi \
  --env-vars \
    CLAUDE_CODE_USE_FOUNDRY=true \
    ANTHROPIC_FOUNDRY_API_KEY=<your-api-key> \
    ANTHROPIC_FOUNDRY_BASE_URL=https://<resource>.services.ai.azure.com/anthropic \
    CLAUDE_MODEL=claude-sonnet-4-6 \
    USE_SKILLS=true \
    FRONTEND_ORIGIN=https://prior-auth-frontend.<env-unique-id>.<region>.azurecontainerapps.io
```

**4C.7 Get backend internal FQDN:**

```bash
az containerapp show \
  --name prior-auth-backend \
  --resource-group prior-auth-rg \
  --query "properties.configuration.ingress.fqdn" -o tsv
```

> ⚠️ **Important:** Note the backend FQDN — you'll need to update `frontend/nginx.conf` to proxy `/api` requests to this URL instead of `http://backend:8000` before building the frontend image. Update the `proxy_pass` line:
>
> ```nginx
> proxy_pass http://<backend-internal-fqdn>;
> ```

**4C.8 Deploy the frontend (external ingress):**

```bash
az containerapp create \
  --name prior-auth-frontend \
  --resource-group prior-auth-rg \
  --environment prior-auth-env \
  --image priorauthacr.azurecr.io/prior-auth-frontend:latest \
  --registry-server priorauthacr.azurecr.io \
  --target-port 80 \
  --ingress external \
  --min-replicas 1 \
  --max-replicas 3 \
  --cpu 0.5 --memory 1Gi
```

**4C.9 Get the application URL:**

```bash
az containerapp show \
  --name prior-auth-frontend \
  --resource-group prior-auth-rg \
  --query "properties.configuration.ingress.fqdn" -o tsv
```

> ⏱️ **Expected Duration:** ~15–20 minutes total for infrastructure + deployment.

</details>

---

## Step 5: Post-Deployment Verification

### 5.1 Verify Application Health

| Check | Command / URL | Expected Result |
|-------|--------------|-----------------|
| Frontend loads | Open application URL | PA request form displays |
| Backend health | `GET /health` | `{"status": "healthy"}` |
| MCP connectivity | Submit a sample case | Agent progress events stream |

### 5.2 Test the Application

**Quick Test Steps:**

1. Open the application in your browser
2. Click **"Load Sample Case"** to populate the form with demo data
3. Click **"Submit for Review"**
4. Monitor the progress tracker — you should see all 5 phases complete
5. Review the agent results in the dashboard tabs (Compliance, Clinical, Coverage)
6. Use the **Decision Panel** to Accept or Override the recommendation
7. Download the audit PDF and notification letter

> 📖 **Sample Case:** The built-in sample case demonstrates a prior authorization request for lumbar spinal fusion (CPT 22612) with degenerative disc disease (ICD-10 M51.16) — a common PA scenario requiring medical necessity evaluation.

### 5.3 Verify Observability (Optional)

If you configured Azure Application Insights:

1. Open [Azure Portal](https://portal.azure.com/) → your Application Insights resource
2. Navigate to **Application Map** to see the backend service topology
3. Use **Transaction Search** to find review traces
4. Check **Live Metrics** during an active review to see real-time telemetry

---

## Step 6: Clean Up (Optional)

### Remove All Azure Resources

**If deployed with `azd` (recommended):**

```bash
azd down
```

This deletes all Azure resources provisioned by `azd up`, including the resource group, Container Registry, Container Apps, Log Analytics, and Application Insights.

**If deployed manually with Azure CLI:**

```bash
# Delete the entire resource group and all resources within it
az group delete --name prior-auth-rg --yes --no-wait
```

### Stop Local Containers

```bash
# Stop and remove containers
docker compose down

# Remove built images (optional)
docker compose down --rmi all
```

### Manual Cleanup (if needed)

If deployment fails or you need to clean up manually:

1. Go to [Azure Portal](https://portal.azure.com/)
2. Navigate to **Resource groups**
3. Select your resource group (e.g., `prior-auth-rg`)
4. Click **Delete resource group**
5. Type the resource group name to confirm

---

## Troubleshooting

### Common Deployment Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| `ANTHROPIC_FOUNDRY_API_KEY` not set | Missing `.env` file | Create `backend/.env` with your credentials (see Step 3.2) |
| Backend health check fails | Port mismatch or dependency error | Check logs: `docker compose logs backend` |
| MCP server timeouts | Network/firewall blocking MCP endpoints | Verify outbound HTTPS access to `mcp.deepsense.ai` and `pubmed.mcp.claude.com` |
| Frontend shows CORS error | `FRONTEND_ORIGIN` mismatch | Set `FRONTEND_ORIGIN` to match the frontend's URL |
| Container build fails | Docker not running | Start Docker Desktop and retry |
| Azure quota exceeded | Insufficient Claude model quota | Check quota in Azure AI Foundry (see Step 1.4) |
| Agent reviews take >5 min | Claude model capacity limits | Retry during off-peak hours or check Foundry service status |

> 📖 **Detailed Troubleshooting:** See [Troubleshooting Guide](./troubleshooting.md) for comprehensive solutions.

---

## Next Steps

Now that your deployment is complete and tested, explore these resources:

| Resource | Description |
|----------|-------------|
| [Architecture](./architecture.md) | Multi-agent architecture, MCP integration, decision rubric, confidence scoring |
| [API Reference](./api-reference.md) | REST API endpoints, request/response schemas, SSE events |
| [Extending the Application](./extending.md) | Add new agents, MCP servers, customize rubric and notification letters |
| [Technical Notes](./technical-notes.md) | Windows SDK patches, MCP headers, structured output, observability |
| [Production Migration](./production-migration.md) | PostgreSQL, Azure Blob Storage, migration steps |

---

## Need Help?

- 🐛 **Issues:** Check [Troubleshooting Guide](./troubleshooting.md)
- 💬 **Support:** Open an issue on [GitHub](https://github.com/amitmukh/prior-auth-maf/issues)
- 📖 **Architecture:** See [Architecture Guide](./architecture.md) for system design details
