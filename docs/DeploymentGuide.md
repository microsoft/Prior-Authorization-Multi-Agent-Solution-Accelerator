# Deployment Guide

## Overview

This guide walks you through deploying the **Prior Authorization Review — Multi-Agent Solution Accelerator** to Azure. The deployment process takes approximately 10 minutes for the default configuration and includes both infrastructure provisioning and application setup.

🆘 **Need Help?** If you encounter any issues during deployment, check our [Troubleshooting Guide](./troubleshooting.md) for solutions to common problems.

---

## Step 1: Prerequisites & Setup

### 1.1 Azure Account Requirements

Ensure you have access to an [Azure subscription](https://azure.microsoft.com/free/) with the following permissions:

| **Required Permission/Role** | **Scope** | **Purpose** |
|------------------------------|-----------|-------------|
| **Contributor** | Subscription level | Create and manage Azure resources |
| **User Access Administrator** | Subscription level | Manage user access and role assignments |

**🔍 How to Check Your Permissions:**

1. Go to [Azure Portal](https://portal.azure.com/)
2. Navigate to **Subscriptions** (search for "subscriptions" in the top search bar)
3. Click on your target subscription
4. In the left menu, click **Access control (IAM)**
5. Scroll down to see the table with your assigned roles — you should see:
   - **Contributor**
   - **User Access Administrator**

### 1.2 Check Service Availability & Quota

⚠️ **CRITICAL:** Before proceeding, ensure your chosen region has all required services available:

**Required Azure Services:**

| **Service** | **Purpose** | **Pricing** |
|-------------|-------------|-------------|
| [Microsoft Foundry](https://learn.microsoft.com/en-us/azure/ai-foundry/) | AI Foundry Hub + Project (auto-provisioned) | [Pricing](https://azure.microsoft.com/en-us/pricing/details/ai-foundry/) |
| [Azure Container Apps](https://learn.microsoft.com/en-us/azure/container-apps/) | Hosting backend and frontend containers | [Pricing](https://azure.microsoft.com/en-us/pricing/details/container-apps/) |
| [Azure Container Registry](https://learn.microsoft.com/en-us/azure/container-registry/) | Storing Docker images | [Pricing](https://azure.microsoft.com/en-us/pricing/details/container-registry/) |
| [Azure Application Insights](https://learn.microsoft.com/en-us/azure/azure-monitor/app/app-insights-overview) | Observability and tracing (optional) | [Pricing](https://azure.microsoft.com/en-us/pricing/details/monitor/) |

> **Note:** The AI Foundry Hub and Project are automatically provisioned by `azd up`. You only need to deploy the Claude model manually after provisioning (see Step 4.3).

**Supported Regions:** Claude models on Microsoft Foundry are currently available only in **East US 2** and **Sweden Central**. You must deploy to one of these regions.

🔍 **Check Availability:** See [Use Foundry Models Claude](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/how-to/use-foundry-models-claude) for the latest region availability.

### 1.3 Claude Model Access (Pre-check)

💡 **OPTIONAL:** Before deployment, you can verify that Claude Sonnet 4.6 is available in your target region.

1. Go to [Microsoft Foundry](https://ai.azure.com/)
2. Click the **Discover** tab → select **Models** in the left menu
3. Search for **Claude Sonnet 4.6** (model ID: `claude-sonnet-4-6`)
4. Verify the model is listed for **East US 2** or **Sweden Central**

> **Note:** The AI Foundry Hub and Project are created automatically during deployment. You will deploy the Claude model and configure its API key/endpoint in Step 4.3 after `azd up` completes.

📖 **Learn More:** See [Use Foundry Models Claude](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/how-to/use-foundry-models-claude) for detailed setup instructions.

---

## Step 2: Choose Your Deployment Environment

Select one of the following options to set up your deployment environment:

### Environment Comparison

| **Option** | **Best For** | **Prerequisites** | **Setup Time** |
|------------|--------------|-------------------|----------------|
| **GitHub Codespaces** | Quick deployment, no local setup required | GitHub account | ~3–5 minutes |
| **VS Code Dev Containers** | Fast deployment with local tools | Docker Desktop, VS Code | ~5–10 minutes |
| **VS Code Web** | Quick deployment, no local setup required | Azure account | ~2–4 minutes |
| **Local Environment** | Full control, custom development | All tools individually | ~15–30 minutes |

**💡 Recommendation:** For fastest deployment, start with **GitHub Codespaces** — no local installation required.

---

<details>
<summary><b>Option A: GitHub Codespaces (Easiest)</b></summary>

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/amitmukh/prior-auth-maf)

1. Click the badge above (may take several minutes to load)
2. Accept default values on the Codespaces creation page
3. Wait for the environment to initialize (includes all deployment tools)
4. **Authenticate with Azure** (both CLI tools are required):
   ```bash
   azd auth login --use-device-code
   az login --use-device-code
   ```
   > **Note:** Codespaces runs on GitHub-hosted VMs. If your organization enforces Conditional Access policies (e.g., IP/location restrictions), your corporate Azure account may be blocked. In that case, use a personal or non-corp Azure account for deployment.
5. Proceed to [Step 3: Configure Deployment Settings](#step-3-configure-deployment-settings)

</details>

<details>
<summary><b>Option B: VS Code Dev Containers</b></summary>

[![Open in Dev Containers](https://img.shields.io/static/v1?style=for-the-badge&label=Dev%20Containers&message=Open&color=blue&logo=visualstudiocode)](https://vscode.dev/redirect?url=vscode://ms-vscode-remote.remote-containers/cloneInVolume?url=https://github.com/amitmukh/prior-auth-maf)

**Prerequisites:**
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- [VS Code](https://code.visualstudio.com/) with [Dev Containers extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers)

**Steps:**
1. Start Docker Desktop
2. Click the badge above to open in Dev Containers
3. Wait for the container to build and start (includes all deployment tools)
4. Proceed to [Step 3: Configure Deployment Settings](#step-3-configure-deployment-settings)

</details>

<details>
<summary><b>Option C: Visual Studio Code Web</b></summary>

[![Open in Visual Studio Code Web](https://img.shields.io/static/v1?style=for-the-badge&label=Visual%20Studio%20Code%20(Web)&message=Open&color=blue&logo=visualstudiocode&logoColor=white)](https://vscode.dev/azure/?vscode-azure-exp=foundry&agentPayload=eyJiYXNlVXJsIjogImh0dHBzOi8vcmF3LmdpdGh1YnVzZXJjb250ZW50LmNvbS9hbWl0bXVraC9wcmlvci1hdXRoLW1hZi9yZWZzL2hlYWRzL21haW4vaW5mcmEvdnNjb2RlX3dlYiIsICJpbmRleFVybCI6ICIvaW5kZXguanNvbiIsICJ2YXJpYWJsZXMiOiB7ImFnZW50SWQiOiAiIiwgImNvbm5lY3Rpb25TdHJpbmciOiAiIiwgInRocmVhZElkIjogIiIsICJ1c2VyTWVzc2FnZSI6ICIiLCAicGxheWdyb3VuZE5hbWUiOiAiIiwgImxvY2F0aW9uIjogIiIsICJzdWJzY3JpcHRpb25JZCI6ICIiLCAicmVzb3VyY2VJZCI6ICIiLCAicHJvamVjdFJlc291cmNlSWQiOiAiIiwgImVuZHBvaW50IjogIiJ9LCAiY29kZVJvdXRlIjogWyJhaS1wcm9qZWN0cy1zZGsiLCAicHl0aG9uIiwgImRlZmF1bHQtYXp1cmUtYXV0aCIsICJlbmRwb2ludCJdfQ==)

1. Click the badge above (may take a few minutes to load)
2. Sign in with your Azure account when prompted
3. Select the subscription where you want to deploy the solution
4. Wait for the environment to initialize (includes all deployment tools)
5. When prompted in the VS Code Web terminal, choose one of the available options
6. **Authenticate with Azure** (VS Code Web requires device code authentication):
   ```shell
   az login --use-device-code
   ```
   > **Note:** In VS Code Web environment, the regular `az login` command may fail. Use the `--use-device-code` flag to authenticate via device code flow. Follow the prompts in the terminal to complete authentication.

7. Proceed to [Step 3: Configure Deployment Settings](#step-3-configure-deployment-settings)

</details>

<details>
<summary><b>Option D: Local Environment</b></summary>

**Required Tools:**

| **Tool** | **Version** | **Installation** |
|----------|-------------|------------------|
| [Python](https://www.python.org/downloads/) | 3.11+ | Backend runtime (local dev only) |
| [Node.js](https://nodejs.org/) | 18+ | Frontend build (local dev only) |
| [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli) | Latest | Azure resource management |
| [Azure Developer CLI (azd)](https://learn.microsoft.com/en-us/azure/developer/azure-developer-cli/install-azd) | 1.18.0+ | Infrastructure deployment |
| [Git](https://git-scm.com/) | Latest | Repository clone |

**Setup Steps:**

1. Install all required deployment tools listed above
2. Clone the repository:

   ```bash
   git clone https://github.com/amitmukh/prior-auth-maf.git
   cd prior-auth-maf
   ```

3. Open the project folder in your IDE or terminal
4. Proceed to [Step 3: Configure Deployment Settings](#step-3-configure-deployment-settings)

**PowerShell Users:** If you encounter script execution issues, run:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

</details>

---

## Step 3: Configure Deployment Settings

Review the configuration options below. You can customize any settings that meet your needs, or leave them as defaults to proceed with a standard deployment.

### 3.1 Set Environment Variables

Create a `backend/.env` file with your Microsoft Foundry credentials:

```env
AZURE_FOUNDRY_API_KEY=your-azure-foundry-api-key
AZURE_FOUNDRY_ENDPOINT=https://<resource-name>.services.ai.azure.com/anthropic
CLAUDE_MODEL=claude-sonnet-4-6

# Skills-based approach (default: true)
USE_SKILLS=true

# Azure Application Insights (optional)
APPLICATION_INSIGHTS_CONNECTION_STRING=InstrumentationKey=...;IngestionEndpoint=...
```

> **Where to find these values:**
>
> 1. Go to [ai.azure.com](https://ai.azure.com/) → select your project
> 2. On the **Home** tab you will see three fields at the top:
>    - **Project API key** — This is your `AZURE_FOUNDRY_API_KEY`.
>    - **Project endpoint** (e.g., `https://<resource-name>.services.ai.azure.com`) — Append `/anthropic` to get your `AZURE_FOUNDRY_ENDPOINT`.
>    - **Azure OpenAI endpoint** — Not used for Claude models.
> 3. The **deployment name** of your Claude model (e.g., `claude-sonnet-4-6`) is your `CLAUDE_MODEL`. Find it under the **Build** tab → **Deployments** in the left menu.
>
> ```
> Project endpoint = "https://<resource-name>.services.ai.azure.com"   + "/anthropic"  →  AZURE_FOUNDRY_ENDPOINT
> Project API key  = "F8RHd..."                                                        →  AZURE_FOUNDRY_API_KEY
> Deployment name  = "claude-sonnet-4-6"                                                →  CLAUDE_MODEL
> ```

### 3.2 Advanced Configuration (Optional)

<details>
<summary><b>MCP Server Endpoints</b></summary>

The MCP server endpoints are pre-configured with defaults. Override them only if you're using custom or self-hosted MCP servers:

| **Environment Variable** | **Default Endpoint** | **Provider** | **Purpose** |
|--------------------------|----------------------|--------------|-------------|
| `MCP_NPI_REGISTRY` | `https://mcp.deepsense.ai/npi_registry/mcp` | DeepSense | Provider NPI validation |
| `MCP_ICD10_CODES` | `https://mcp.deepsense.ai/icd10_codes/mcp` | DeepSense | Diagnosis code lookup |
| `MCP_CMS_COVERAGE` | `https://mcp.deepsense.ai/cms_coverage/mcp` | DeepSense | Medicare LCD/NCD policies |
| `MCP_CLINICAL_TRIALS` | `https://mcp.deepsense.ai/clinical_trials/mcp` | DeepSense | Clinical trial search |
| `MCP_PUBMED` | `https://pubmed.mcp.claude.com/mcp` | Anthropic | PubMed literature search |

</details>

<details>
<summary><b>Choose Deployment Method</b></summary>

| **Aspect** | **azd up (Default)** | **Docker Compose** | **Local Dev** |
|------------|----------------------|--------------------|--------------------|
| **Target** | Azure Container Apps | Local Docker | Local processes |
| **Best For** | Cloud deployment | Quick demo | Development with hot reload |
| **Setup Time** | ~10 minutes | ~5 minutes | ~10 minutes |
| **Infrastructure** | Fully provisioned | Local only | Local only |

> **Note:** Step 4 below covers the default `azd up` deployment. For Docker Compose or local development alternatives, see [Alternative Deployment Methods](#alternative-deployment-methods).

</details>

---

## Step 4: Deploy the Solution

💡 **Before You Start:** If you encounter any issues during deployment, check our [Troubleshooting Guide](./troubleshooting.md) for common solutions.

⚠️ **Critical: Redeployment Warning** — If you have previously run `azd up` in this folder (i.e., a `.azure` folder exists), you must [create a fresh environment](#creating-a-new-environment) to avoid conflicts and deployment failures.

### 4.1 Authenticate with Azure

Both `azd` and `az` CLI must be authenticated. The pre-flight checks verify both.

```bash
azd auth login
az login
```

**For Codespaces / VS Code Web** (device code flow required):
```bash
azd auth login --use-device-code
az login --use-device-code
```

**For specific tenants:**
```bash
azd auth login --tenant-id <tenant-id>
az login --tenant <tenant-id>
```

> **Conditional Access note:** If your organization enforces Conditional Access policies, `azd auth login` from Codespaces may fail with Error 53003. Use a non-corporate Azure account or deploy from your local machine instead.

**Finding Tenant ID:**
1. Open the [Azure Portal](https://portal.azure.com/)
2. Navigate to **Microsoft Entra ID** from the left-hand menu
3. Under the **Overview** section, locate the **Tenant ID** field. Copy the value displayed

### 4.2 Start Deployment

```bash
azd up
```

> **💡 Automated Pre-Flight Checks:** Before provisioning any Azure resources, `azd up` automatically runs a 7-step verification that checks Azure CLI authentication, subscription permissions, required CLI extensions, project files, soft-deleted Key Vault conflicts, resource provider registration, and resource quotas. If any issues are found, you'll see clear guidance on how to fix them — saving you from a failed deployment after a long wait.

**During deployment, you'll be prompted for:**
1. **Environment name** (e.g., `prior-auth-dev`)
2. **Azure subscription** selection
3. **Azure region** — select **East US 2** (`eastus2`) or **Sweden Central** (`swedencentral`)
4. **Azure Foundry API key** and **endpoint** — leave blank for now (you'll configure these after deploying the Claude model in Step 4.3)

**What gets deployed:**
- **AI Foundry Hub + Project** (for Claude model deployment)
- Azure Container Registry (also used for remote image builds — no local Docker required)
- Azure Container Apps Environment
- Backend Container App (Python/FastAPI, port 8000)
- Frontend Container App (Next.js/nginx, port 80)
- Log Analytics workspace
- Application Insights
- Storage Account and Key Vault (AI Foundry dependencies)

> **Note:** Container images are built remotely on Azure Container Registry, so no local Docker installation is required for deployment. This works on any machine architecture (x86, ARM64) and any OS.

**Expected Duration:** ~10 minutes for initial provisioning + deployment.

**⚠️ Deployment Issues:** If you encounter errors or timeouts, try the other supported region (East US 2 or Sweden Central) as there may be capacity constraints. For detailed error solutions, see our [Troubleshooting Guide](./troubleshooting.md).

### 4.3 Deploy Claude Model & Configure Credentials

After `azd up` completes, the AI Foundry Hub and Project are provisioned. Now deploy the Claude model:

**Step 1: Open the AI Foundry Portal**

The portal URL is displayed in the deployment output, or navigate directly:

```bash
azd show
```

Look for the `AI_FOUNDRY_PORTAL_URL` output and open it in your browser, or go to [ai.azure.com](https://ai.azure.com/) and select the provisioned project.

**Step 2: Deploy the Claude Model**

1. In the Foundry portal, click the **Discover** tab → select **Models** in the left menu
2. Search for **Claude Sonnet 4.6** (or your preferred Claude model)
3. Click the model → **Deploy** and follow the prompts
4. Once deployed, the **Project API key** and **Project endpoint** are available on the **Home** tab

📖 **Detailed Instructions:** See [Use Foundry Models Claude](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/how-to/use-foundry-models-claude) for step-by-step guidance.

**Step 3: Configure the Backend with Claude Credentials**

Set the API key, base URL, and deployment name in your azd environment. These values come from the **Home** tab of the Foundry portal (see [Step 3.1](#31-set-environment-variables) for where to find them):

```bash
azd env set AZURE_FOUNDRY_API_KEY <your-api-key>
azd env set AZURE_FOUNDRY_ENDPOINT https://<resource-name>.services.ai.azure.com/anthropic
azd env set CLAUDE_MODEL claude-sonnet-4-6    # Must match your deployment name
```

> **Important:** The endpoint URL must include the `/anthropic` suffix. Copy the **Project endpoint** from the Foundry Home tab and append `/anthropic`.

Then redeploy to apply the credentials:

```bash
azd up
```

### 4.4 Get Application URL

After successful deployment:

```bash
azd show
```

The frontend URL will be displayed in the deployment output. You can also find it in the [Azure Portal](https://portal.azure.com/) under your resource group → Frontend Container App → **Application Url**.

⚠️ **Important:** Complete [Post-Deployment Steps](#step-5-post-deployment-configuration) before accessing the application.

---

## Step 5: Post-Deployment Configuration

### 5.1 Verify Application Health

| **Check** | **Command / URL** | **Expected Result** |
|-----------|-------------------|---------------------|
| Frontend loads | Open application URL | PA request form displays |
| Backend health | `GET /health` | `{"status": "healthy"}` |
| MCP connectivity | Submit a sample case | Agent progress events stream |

### 5.2 Test the Application

**Quick Test Steps:**

1. **Access the application** using the URL from Step 4.4
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

### 5.4 Register Agents in Foundry Control Plane (Optional)

You can optionally register the multi-agent system in **Microsoft Foundry Control Plane** for centralized observability, fleet monitoring, and organizational inventory. Registration lets you view agent traces, runs, and error rates in the Foundry portal — it does **not** change the app's runtime behavior or traffic flow. The frontend continues to call the backend Container App directly regardless of whether agents are registered.

#### What You Get

| Feature | Without Registration | With Registration |
|---------|---------------------|-------------------|
| Agent traces in App Insights | ✅ | ✅ |
| Container logs in Log Analytics | ✅ | ✅ |
| Agent listed in Foundry portal | ❌ | ✅ |
| Block/Unblock agent from Foundry | ❌ | ✅ * |
| Fleet monitoring dashboard (runs, error rates, cost) | ❌ | ✅ |
| Centralized trace viewer in Foundry | ❌ | ✅ |

> **\* Important — Block/Unblock limitation:** Block/Unblock only affects traffic routed through the Foundry AI Gateway proxy URL. In the default deployment, the frontend calls the backend Container App directly — **Block/Unblock has no operational effect on this app** unless you adopt the proxy routing pattern described in the [Production Enhancement](#production-enhancement-enable-foundry-proxy-for-operational-control) section below.

#### Architecture

The Prior Auth system uses a fan-out/fan-in orchestration pattern. The **Orchestrator** is the production entry point, and each sub-agent also has a dedicated endpoint for evaluation, red-teaming, and Foundry registration.

```
Default traffic flow (Foundry registration does NOT change this):

  Frontend → Backend Container App /api/review/stream → Orchestrator
                                                          ├── Clinical Agent  (in-process)
                                                          ├── Compliance Agent (in-process)
                                                          ├── Coverage Agent   (in-process)
                                                          └── Synthesis Agent  (in-process)

Foundry registration (observability side-channel only):

  Foundry Portal ← traces/metrics ← Backend (via App Insights)

Per-agent endpoints (eval / red-team / Foundry registration):
  POST /api/agents/clinical
  POST /api/agents/compliance
  POST /api/agents/coverage
  POST /api/agents/synthesis
```

**Registration options:**

| Strategy | When to use |
|----------|-------------|
| **Orchestrator only** | Minimal setup. Registers a single entry in Foundry for fleet-level trace visibility. |
| **Orchestrator + individual agents** | Full per-agent trace visibility in Foundry. Useful for per-agent evaluation, red-teaming, and organizational inventory. |

#### Prerequisites

- Deployment completed (Steps 4.1–4.4)
- Access to the [Foundry (new) portal](https://ai.azure.com/) — look for the `(new)` toggle in the portal banner

#### Step 1: Enable AI Gateway

The AI Gateway is a free, Foundry-managed feature (backed by Azure API Management) that enables agent registration, traffic proxying, and governance.

1. Go to [ai.azure.com](https://ai.azure.com/) and ensure the **Foundry (new)** toggle is on
2. On the toolbar, select **Operate**
3. On the left pane, select **Admin**
4. Open the **AI Gateway** tab
5. Check if your Foundry resource has an associated AI gateway
6. If not listed, click **Add AI Gateway** and follow the prompts

> **Note:** An AI gateway is free to set up and unlocks governance features like security, diagnostic data, and rate limits.

📖 **Detailed Instructions:** See [Create an AI gateway](https://learn.microsoft.com/en-us/azure/foundry/configuration/enable-ai-api-management-gateway-portal#create-an-ai-gateway).

#### Step 2: Verify Application Insights Connection

Foundry Control Plane uses the Application Insights resource associated with your project for tracing and diagnostics.

1. In the Foundry portal, select **Operate** → **Admin**
2. Under **All projects**, search for your project
3. Select the project → **Connected resources** tab
4. Verify that an **AppInsights** resource is listed
5. If missing, click **Add connection** → **Application Insights** and select the one created by `azd up`

#### Step 3: Register the Orchestrator Agent

1. In the Foundry portal, select **Operate** → **Overview**
2. Click **Register agent**
3. Fill in the agent details:

| Field | Value |
|-------|-------|
| **Agent URL** | `https://<your-backend-fqdn>/api/review/stream` (the backend Container App URL) |
| **Protocol** | HTTP |
| **OpenTelemetry Agent ID** | `prior-auth-orchestrator` |
| **Admin portal URL** | *(optional)* Your Azure Portal resource group URL |
| **Project** | Select the auto-provisioned AI Foundry project |
| **Agent name** | `Prior Auth Orchestrator` |
| **Description** | Multi-agent prior authorization review system. Orchestrates Clinical Reviewer, Compliance Validation, Coverage Assessment, and Synthesis agents in a fan-out/fan-in pattern to produce structured PA recommendations for human reviewers. |

4. Save the registration

> **Finding your backend URL:** Run `azd show` and look for the `backendUrl` output, or check the Azure Portal under your resource group → Backend Container App → **Application Url**.

#### Step 3b: Register Individual Agents (Optional)

If you need per-agent evaluation, red-teaming, or independent governance controls, register each sub-agent as a separate custom agent:

| Agent Name | Agent URL | OpenTelemetry Agent ID |
|------------|-----------|------------------------|
| Prior Auth Clinical Reviewer | `https://<backend-fqdn>/api/agents/clinical` | `prior-auth-clinical` |
| Prior Auth Compliance Validator | `https://<backend-fqdn>/api/agents/compliance` | `prior-auth-compliance` |
| Prior Auth Coverage Assessor | `https://<backend-fqdn>/api/agents/coverage` | `prior-auth-coverage` |
| Prior Auth Synthesis Decision | `https://<backend-fqdn>/api/agents/synthesis` | `prior-auth-synthesis` |

Repeat the Step 3 registration flow for each agent above. All agents share the same backend Container App — no additional infrastructure is needed.

> **Tip:** See [API Reference — Per-Agent Endpoints](./api-reference.md#per-agent-endpoints) for request/response schemas and curl examples.

#### Step 4: Verify (No Client Changes Needed)

After registration, Foundry generates a **proxy URL** for each registered agent (e.g., `https://apim-<resource>.azure-api.net/prior-auth-orchestrator/`). However, **no changes are needed** for this application:

- The **frontend** continues to call the backend Container App directly
- The **orchestrator** calls sub-agents in-process (no network calls)
- The Foundry proxy URL is **not used** by any component in this app

The proxy URL is only relevant if external third-party consumers need governed access to your agents through the Foundry AI Gateway.

> **Note:** If you want Block/Unblock to have operational effect on this app, see the [Production Enhancement](#production-enhancement-enable-foundry-proxy-for-operational-control) section below.

#### Step 5: Verify Registration

1. In the Foundry portal, select **Operate** → **Assets**
2. Use the **Source** filter → select **Custom** to see your registered agent
3. Verify the status shows **Running**
4. Submit a test PA request and check the **Traces** tab to confirm traces are flowing

#### Lifecycle Management

Once registered, you can manage the agent from the Foundry portal:

| Action | How | Effect |
|--------|-----|--------|
| **Block** | Assets → Select agent → Update status → Block | Blocks requests routed through the Foundry proxy URL only. **Has no effect on this app** in the default deployment because the frontend calls the backend directly. |
| **Unblock** | Assets → Select agent → Update status → Unblock | Re-enables requests through the Foundry proxy URL. Same caveat: no effect unless traffic is routed through the proxy. |
| **View traces** | Assets → Select agent → Traces tab | Shows each HTTP call to the agent with trace details including sub-agent spans. |

> **Important:** Block/Unblock controls the Foundry AI Gateway proxy — not your backend Container App. Since this app calls the backend directly, blocking an agent in Foundry does not prevent the app from processing PA requests. To stop the underlying infrastructure entirely, scale down the Container App: `az containerapp update --name <app> --resource-group <rg> --min-replicas 0 --max-replicas 0`

#### Production Enhancement: Enable Foundry Proxy for Operational Control

In the default deployment, Block/Unblock has no effect because the frontend calls the backend directly. To make Foundry's Block/Unblock a real operational control for the entire pipeline, route frontend traffic through the Foundry AI Gateway proxy:

**Step 1: Update frontend to use the Foundry proxy URL**

```bash
# Copy the proxy URL from Foundry portal → Assets → Select agent → Agent URL → Copy
azd env set BACKEND_URL https://apim-<foundry-resource>.azure-api.net/prior-auth-orchestrator/
azd up
```

**Step 2: Lock down direct backend access (recommended)**

Set the backend Container App ingress to internal-only so the **only** public path is through the Foundry proxy. In `infra/modules/container-app.bicep`, update the backend's ingress:

```bicep
ingress: {
  external: false   // was: true — now only reachable via Foundry proxy
  targetPort: targetPort
  transport: 'auto'
  allowInsecure: false
}
```

Redeploy with `azd up`. Now blocking the agent in Foundry effectively stops all incoming PA requests.

**Per-agent Block/Unblock**

To block/unblock individual agents independently, you would need to split each agent into its own container and have the orchestrator call agents via their Foundry proxy URLs instead of in-process. This is a larger architectural change (microservices pattern) and is beyond the scope of this solution accelerator.

---

#### Observability Progression

The level of trace detail visible in Foundry depends on upstream framework releases:

| What | When | Trace Detail |
|------|------|-------------|
| **HTTP-level traces** | Available now | Request/response to `/review` endpoint (duration, status code) |
| **Agent-level traces** | After [MAF PR #4326](https://github.com/microsoft/agent-framework/pull/4326) merges | `invoke_agent` spans with agent name, duration, response capture, exception tracking |
| **Tool-level traces** | After [Claude SDK #611](https://github.com/anthropics/claude-agent-sdk-python/issues/611) is resolved | Individual MCP tool call spans (e.g., `npi_lookup`, `validate_code`) as child spans |

To pick up new trace capabilities, update `agent-framework-claude` version in `backend/requirements.txt` and redeploy with `azd up`. No other code changes are needed — the existing `enable_instrumentation()` call in the observability module automatically captures all emitted spans.

📖 **Learn More:**
- [Register a custom agent in Foundry Control Plane](https://learn.microsoft.com/en-us/azure/foundry/control-plane/register-custom-agent)
- [Manage agents in Foundry Control Plane](https://learn.microsoft.com/en-us/azure/foundry/control-plane/how-to-manage-agents)
- [Monitor agent health across your fleet](https://learn.microsoft.com/en-us/azure/foundry/control-plane/monitoring-across-fleet)

---

## Step 6: Clean Up (Optional)

### Remove All Resources

```bash
azd down
```

This deletes all Azure resources provisioned by `azd up`, including the resource group, Container Registry, Container Apps, Log Analytics, and Application Insights.

### Manual Cleanup (if needed)

If deployment fails or you need to clean up manually:

1. Go to [Azure Portal](https://portal.azure.com/)
2. Navigate to **Resource groups**
3. Select your resource group (e.g., `prior-auth-rg`)
4. Click **Delete resource group**
5. Type the resource group name to confirm

---

## Managing Multiple Environments

<details>
<summary><b>Recover from Failed Deployment</b></summary>

**If your deployment failed or encountered errors:**

1. **Try the other supported region:** Create a new environment and select **East US 2** or **Sweden Central** during deployment
2. **Clean up and retry:** Use `azd down` to remove failed resources, then `azd up` to redeploy
3. **Check troubleshooting:** Review [Troubleshooting Guide](./troubleshooting.md) for specific error solutions
4. **Fresh start:** Create a completely new environment with a different name

**Example Recovery Workflow:**
```bash
# Remove failed deployment (optional)
azd down

# Create new environment
azd env new priorauthretry

# Deploy with different settings/region
azd up
```

</details>

<details>
<summary><b>Creating a New Environment</b></summary>

**Create Environment Explicitly:**
```bash
# Create a new named environment
azd env new <new-environment-name>

# Select the new environment
azd env select <new-environment-name>

# Deploy to the new environment
azd up
```

**Example:**
```bash
# Create a new environment for production
azd env new priorauthprod

# Switch to the new environment
azd env select priorauthprod

# Deploy with fresh settings
azd up
```

</details>

<details>
<summary><b>Switch Between Environments</b></summary>

**List Available Environments:**
```bash
azd env list
```

**Switch to Different Environment:**
```bash
azd env select <environment-name>
```

**View Current Environment:**
```bash
azd env get-values
```

</details>

### Best Practices for Multiple Environments

- **Use descriptive names:** `priorauthdev`, `priorauthprod`, `priorauthtest`
- **Different regions:** Deploy to East US 2 or Sweden Central for testing quota availability
- **Separate configurations:** Each environment can have different parameter settings
- **Clean up unused environments:** Use `azd down` to remove environments you no longer need

---

## Alternative Deployment Methods

<details>
<summary><b>Docker Compose (Local Quick Start)</b></summary>

**Build and start containers:**

```bash
docker compose up --build
```

**Verify deployment:**

| **Service** | **URL** | **Expected Response** |
|-------------|---------|----------------------|
| Frontend | http://localhost:3000 | Application UI loads |
| Backend health | http://localhost:8000/health | `{"status": "healthy"}` |

**Container details:**

The `docker-compose.yml` reads your `backend/.env` file and maps credentials:

| **Your `.env` variable** | **Maps to (container)** | **Purpose** |
|--------------------------|-------------------------|-------------|
| `AZURE_FOUNDRY_API_KEY` | `ANTHROPIC_FOUNDRY_API_KEY` | Microsoft Foundry auth |
| `AZURE_FOUNDRY_ENDPOINT` | `ANTHROPIC_FOUNDRY_BASE_URL` | Foundry endpoint URL |
| (set automatically) | `CLAUDE_CODE_USE_FOUNDRY=true` | Enables Foundry mode |

> ⏱️ **Expected Duration:** ~2 minutes for initial build, ~30 seconds for subsequent starts.

**Stop containers:**
```bash
# Stop and remove containers
docker compose down

# Remove built images (optional)
docker compose down --rmi all
```

</details>

<details>
<summary><b>Local Development (Without Docker)</b></summary>

**Backend setup:**

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

**Frontend setup:**

```bash
cd frontend
npm install

# Configure environment (optional — defaults work for local dev)
cp .env.example .env.local
```

**Start both servers (in separate terminals):**

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

**Verify deployment:**

Open `http://localhost:3000` in your browser.

> **Note:** The frontend calls the backend directly (not through a Next.js rewrite proxy) because multi-agent reviews take 3–5 minutes — longer than the dev server proxy's default timeout.

</details>

<details>
<summary><b>Azure Container Apps via CLI (Manual)</b></summary>

**Authenticate with Azure:**

```bash
az login
```

For specific tenants:
```bash
az login --tenant-id <tenant-id>
```

**Create a Resource Group:**

```bash
az group create \
  --name prior-auth-rg \
  --location eastus
```

**Create Azure Container Registry:**

```bash
az acr create \
  --name priorauthacr \
  --resource-group prior-auth-rg \
  --sku Basic \
  --admin-enabled true
```

**Build and push container images:**

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

**Create Container Apps Environment:**

```bash
az containerapp env create \
  --name prior-auth-env \
  --resource-group prior-auth-rg \
  --location eastus
```

**Deploy the backend (internal ingress):**

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
    ANTHROPIC_FOUNDRY_BASE_URL=https://<resource-name>.services.ai.azure.com/anthropic \
    CLAUDE_MODEL=claude-sonnet-4-6 \
    USE_SKILLS=true \
    FRONTEND_ORIGIN=https://prior-auth-frontend.<env-unique-id>.<region>.azurecontainerapps.io
```

**Get backend internal FQDN:**

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

**Deploy the frontend (external ingress):**

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

**Get the application URL:**

```bash
az containerapp show \
  --name prior-auth-frontend \
  --resource-group prior-auth-rg \
  --query "properties.configuration.ingress.fqdn" -o tsv
```

> ⏱️ **Expected Duration:** ~15–20 minutes total for infrastructure + deployment.

**Clean up manually deployed resources:**

```bash
az group delete --name prior-auth-rg --yes --no-wait
```

</details>

---

## Environment Variables Reference

All environment variables used by the application, organized by purpose.

### Microsoft Foundry (Claude API Routing)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AZURE_FOUNDRY_API_KEY` | **Yes** | — | Your Microsoft Foundry **Project API key**. Found on the Foundry portal **Home** tab (top of page). Set in `backend/.env` for local development; mapped to `ANTHROPIC_FOUNDRY_API_KEY` at runtime by the SDK patches. |
| `AZURE_FOUNDRY_ENDPOINT` | **Yes** | — | Your **Project endpoint** from the Foundry portal Home tab with `/anthropic` appended (e.g., `https://<resource-name>.services.ai.azure.com/anthropic`). Mapped to `ANTHROPIC_FOUNDRY_BASE_URL` at runtime. |
| `CLAUDE_CODE_USE_FOUNDRY` | Auto | `true` | **Anthropic-defined flag** that tells the Claude CLI/SDK to route API calls through Microsoft Foundry instead of directly to `api.anthropic.com`. Set automatically by the backend patches and in Container App config — you do not need to set this manually. |
| `ANTHROPIC_FOUNDRY_API_KEY` | Auto | — | The actual env var consumed by the Claude CLI for Foundry authentication. Auto-mapped from `AZURE_FOUNDRY_API_KEY` by the backend patches. In Azure Container Apps, this is set directly as a secret reference. |
| `ANTHROPIC_FOUNDRY_BASE_URL` | Auto | — | The actual env var consumed by the Claude CLI for the Foundry endpoint. Auto-mapped from `AZURE_FOUNDRY_ENDPOINT` by the backend patches. |

### Model Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `CLAUDE_MODEL` | No | `claude-sonnet-4-6` | The Claude **deployment name** as shown in the Foundry portal under the **Build** tab → **Deployments**. Must exactly match the name of a model deployed in your Microsoft Foundry resource. Common values: `claude-opus-4-5`, `claude-sonnet-4-6`. |
| `USE_SKILLS` | No | `true` | When `true`, agents use `SKILL.md` files via MAF native skill discovery. When `false`, agents use inline system prompt instructions. |

### Application

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `FRONTEND_ORIGIN` | No | `http://localhost:5173` | CORS origin for the frontend. Set to the frontend's deployed URL (e.g., `https://ca-frontend-xxx.azurecontainerapps.io`) in production. |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | No | — | Azure Application Insights connection string for observability. Auto-provisioned by Bicep when deploying with `azd up`. |

### MCP Servers (Optional)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `MCP_NPI_REGISTRY` | No | `https://mcp.deepsense.ai/npi_registry/mcp` | NPI Registry — provider verification (CMS NPPES) |
| `MCP_ICD10_CODES` | No | `https://mcp.deepsense.ai/icd10_codes/mcp` | ICD-10 diagnosis code validation (2026 code set) |
| `MCP_CMS_COVERAGE` | No | `https://mcp.deepsense.ai/cms_coverage/mcp` | CMS Coverage — Medicare LCD/NCD policy lookup |
| `MCP_PUBMED` | No | `https://pubmed.mcp.claude.com/mcp` | PubMed biomedical literature search |
| `MCP_CLINICAL_TRIALS` | No | `https://mcp.deepsense.ai/clinical_trials/mcp` | ClinicalTrials.gov search |

> **Note:** All DeepSense MCP servers require the header `User-Agent: claude-code/1.0`, which is configured automatically in `backend/app/tools/mcp_config.py`.

### How Variables Flow in Azure Deployment

```
backend/.env (local)          azd environment (.azure/<env>/.env)
─────────────────────         ─────────────────────────────────────
AZURE_FOUNDRY_API_KEY    →    AZURE_FOUNDRY_API_KEY
AZURE_FOUNDRY_ENDPOINT   →    AZURE_FOUNDRY_ENDPOINT
CLAUDE_MODEL             →    CLAUDE_MODEL
                               ↓ (main.parameters.json mapping)
                         infra/main.bicep parameters
                               ↓ (Container App env vars)
                         ┌──────────────────────────────────────┐
                         │ CLAUDE_CODE_USE_FOUNDRY = true       │
                         │ ANTHROPIC_FOUNDRY_API_KEY (secret)   │
                         │ ANTHROPIC_FOUNDRY_BASE_URL           │
                         │ CLAUDE_MODEL                         │
                         │ APPLICATIONINSIGHTS_CONNECTION_STRING│
                         │ FRONTEND_ORIGIN                      │
                         └──────────────────────────────────────┘
```

---

## Troubleshooting

### Common Deployment Issues

| **Issue** | **Cause** | **Solution** |
|-----------|-----------|--------------|
| `ANTHROPIC_FOUNDRY_API_KEY` not set | Missing `.env` file | Create `backend/.env` with your credentials (see Step 3.1) |
| Backend health check fails | Port mismatch or dependency error | Check logs: `docker compose logs backend` |
| MCP server timeouts | Network/firewall blocking MCP endpoints | Verify outbound HTTPS access to `mcp.deepsense.ai` and `pubmed.mcp.claude.com` |
| Frontend shows CORS error | `FRONTEND_ORIGIN` mismatch | Set `FRONTEND_ORIGIN` to match the frontend's URL |
| Container build fails | Docker not running | Start Docker Desktop and retry |
| Azure quota exceeded | Insufficient Claude model quota | Check quota in Microsoft Foundry (see Step 1.3) |
| Agent reviews take >5 min | Claude model capacity limits | Retry during off-peak hours or check Foundry service status |

> 📖 **Detailed Troubleshooting:** See [Troubleshooting Guide](./troubleshooting.md) for comprehensive solutions.

---

## Next Steps

Now that your deployment is complete and tested, explore these resources to enhance your experience:

📚 **Learn More:**
- [Architecture](./architecture.md) — Multi-agent architecture, MCP integration, decision rubric, confidence scoring
- [API Reference](./api-reference.md) — REST API endpoints, request/response schemas, SSE events
- [Extending the Application](./extending.md) — Add new agents, MCP servers, customize rubric and notification letters
- [Technical Notes](./technical-notes.md) — Windows SDK patches, MCP headers, structured output, observability
- [Production Migration](./production-migration.md) — PostgreSQL, Azure Blob Storage, migration steps

## Need Help?

- 🐛 **Issues:** Check [Troubleshooting Guide](./troubleshooting.md)
- 💬 **Support:** Review [Support Guidelines](../SUPPORT.md) or open an issue on [GitHub](https://github.com/amitmukh/prior-auth-maf/issues)
- 🔧 **Contributing:** See [Contributing Guide](../CONTRIBUTING.md)
- 📖 **Documentation:** See [Architecture](./architecture.md) for system design details
