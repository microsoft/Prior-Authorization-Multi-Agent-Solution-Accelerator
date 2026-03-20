```skill
---
name: foundry-multi-agent-solution-accelerator
description: "Scaffold a complete Microsoft Foundry Multi-Agent Solution Accelerator from scratch. USE FOR: generate project structure, README, Azure Bicep infra, Foundry Hosted Agent code, FastAPI orchestrator backend, Next.js frontend, Docker Compose, agent registration scripts, observability setup, and Responsible AI docs for any multi-agent domain vertical. Produces a fully azd-deployable template with one 'azd up' command. DO NOT USE FOR: modifying existing agents, deploying to Foundry (use microsoft-foundry skill), general Azure resource management."
---

# Foundry Multi-Agent Solution Accelerator — Scaffold Skill

This skill generates a complete, production-pattern multi-agent solution accelerator deployable to **Microsoft Foundry** with `azd up`. It produces every file needed: project structure, README, Bicep infra, agent containers, backend orchestrator, frontend, Docker Compose, and Responsible AI documentation.

---

## Required Workflow

Follow these steps **in order**. Do not skip steps.

---

### Step 1 — Gather Domain Context

Before generating any files, collect:

| Question | Why it matters |
|---|---|
| **Domain / vertical** (e.g. Healthcare, Finance, Legal) | Drives agent names, skill descriptions, README language |
| **Number of specialist agents** (recommend 3–5) | Determines folder structure and orchestration pattern |
| **Agent names and responsibilities** | Each agent needs a distinct, non-overlapping scope |
| **External MCP tools needed** (optional) | Determines which agents need `MCPStreamableHTTPTool` wiring |
| **Primary Azure region** | Constrained by model availability (gpt-5.4: `eastus2`, `swedencentral`) |
| **Model deployment name** | Default: `gpt-5.4` |

---

### Step 2 — Generate Project Structure

Create the following folder layout. Replace `<agent-N>` with the actual agent names collected in Step 1.

```
<project-root>/
├── azure.yaml                        # azd project descriptor + hooks
├── docker-compose.yml                # Local dev: all containers
├── README.md
├── TRANSPARENCY_FAQ.md               # Responsible AI FAQ
├── CODE_OF_CONDUCT.md
├── CONTRIBUTING.md
├── SECURITY.md
├── SUPPORT.md
├── SKILL.md                          # This file
│
├── agents/
│   ├── <agent-1>/
│   │   ├── agent.yaml                # Foundry Hosted Agent descriptor
│   │   ├── Dockerfile
│   │   ├── main.py                   # MAF entry point (from_agent_framework)
│   │   ├── requirements.txt
│   │   ├── schemas.py                # Pydantic output model
│   │   └── skills/
│   │       └── <agent-1>-skill/
│   │           └── skill.md          # Domain rules for this agent
│   └── <agent-N>/  (repeat pattern)
│
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── e2e_test.py
│   └── app/
│       ├── __init__.py
│       ├── main.py                   # FastAPI app factory
│       ├── config.py                 # Settings (pydantic-settings)
│       ├── observability.py          # OTel / App Insights setup
│       ├── agents/
│       │   ├── __init__.py
│       │   ├── <agent-1>.py          # Per-agent HTTP dispatcher
│       │   ├── orchestrator.py       # Fan-out/fan-in coordinator
│       │   └── hosted_agents.py      # Two-mode dispatcher
│       ├── models/
│       │   ├── __init__.py
│       │   └── schemas.py            # Shared API schemas
│       ├── routers/
│       │   ├── __init__.py
│       │   ├── agents.py
│       │   └── review.py
│       └── services/
│           ├── __init__.py
│           └── storage.py            # In-memory store (swap for DB in prod)
│
├── frontend/
│   ├── Dockerfile
│   ├── nginx.conf
│   ├── next.config.ts
│   ├── package.json
│   ├── tsconfig.json
│   ├── app/
│   │   ├── globals.css
│   │   ├── layout.tsx
│   │   └── page.tsx
│   ├── components/
│   │   ├── upload-form.tsx
│   │   ├── progress-tracker.tsx
│   │   ├── decision-panel.tsx
│   │   └── header.tsx
│   └── lib/
│       ├── api.ts
│       ├── types.ts
│       └── utils.ts
│
├── infra/
│   ├── main.bicep                    # Subscription-scoped entry point
│   ├── main.parameters.json          # azd parameter defaults
│   ├── abbreviations.json
│   └── modules/
│       ├── ai-foundry.bicep          # Foundry resource + project + model deploy
│       ├── container-registry.bicep  # ACR
│       ├── container-apps-env.bicep  # Managed Environment + Log Analytics
│       ├── container-app.bicep       # Reusable per-app module
│       ├── monitoring.bicep          # App Insights + Log Analytics workspace
│       └── role-assignments.bicep    # RBAC (Cognitive Services OpenAI User, AI User)
│
├── scripts/
│   ├── register_agents.py            # Foundry agent registration + start
│   └── check_agents.py              # Health check
│
└── docs/
    ├── architecture.md
    ├── api-reference.md
    ├── DeploymentGuide.md
    ├── extending.md
    └── images/
        └── readme/
            ├── solution-architecture.svg
            ├── agentic-architecture.svg
            └── interface.png          # 1600×900 UI screenshot
```

---

### Step 3 — Generate README.md

The README must contain these sections in order:

1. **Title + badges** — License, Azure Deployable, Agent Framework
2. **One-paragraph summary** — What the solution does, how many agents, key outcome (e.g. decision in <2 min), tech stack
3. **Runtime modes table** — Foundry Hosted Agent mode vs Local/Docker Compose mode
4. **Solution Overview** — Architecture diagram reference, agentic pipeline diagram, key features (collapsible `<details>` blocks)
5. **Quick Deploy** — Prerequisites list, step-by-step `azd up` instructions, environment variables table
6. **Business Scenario** — Domain problem being solved, value proposition
7. **Local Development** — `docker compose up` instructions, env var setup
8. **Agent Details** — Table of all agents with name, responsibility, MCP tools used, model
9. **Project Structure** — Annotated tree (condensed)
10. **Extending the Solution** — How to add a new agent, swap a model, add MCP tools
11. **Supporting Documentation** — Links to docs/ files
12. **Responsible AI** — Links to TRANSPARENCY_FAQ.md, Microsoft AI principles

**README conventions:**
- Use SVG diagrams (not PNG) for architecture diagrams — they scale cleanly in GitHub
- All section anchors must be lowercase with hyphens for GitHub linking
- Include `> [!NOTE]` callout for the Responsible AI disclaimer near the top
- Interface screenshot: 1600×900 PNG, named `docs/images/readme/interface.png`

---

### Step 4 — Generate Azure Bicep Infrastructure

#### `infra/main.bicep` — Subscription-scoped entry point

```bicep
targetScope = 'subscription'

// Required parameters
param environmentName string     // azd environment name
param location string            // eastus2 or swedencentral for gpt-5.4
param azureOpenAIDeploymentName string = 'gpt-5.4'
param deploymentSkuName string = 'GlobalStandard'  // or DataZoneStandard

// Pattern: create resource group, then call modules
resource rg 'Microsoft.Resources/resourceGroups@2021-04-01' = {
  name: '${abbrs.resourcesResourceGroups}${environmentName}'
  location: location
  tags: tags
}

// Modules to call (in dependency order):
// 1. monitoring   → Log Analytics + App Insights
// 2. ai-foundry   → Foundry resource + project + gpt-5.4 model deployment
// 3. container-registry → ACR (Premium for geo-replication option)
// 4. container-apps-env → Managed Environment linked to Log Analytics
// 5. container-app (×N) → one per agent + backend + frontend
// 6. role-assignments → grant app identities Cognitive Services OpenAI User + Azure AI User
```

#### `infra/modules/ai-foundry.bicep` — Key patterns

```bicep
// Foundry resource uses kind='AIServices', sku.name='S0'
resource foundryAccount 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: '${name}-foundry'
  kind: 'AIServices'
  sku: { name: 'S0' }
  properties: {
    customSubDomainName: '${name}-foundry'
    publicNetworkAccess: 'Enabled'
  }
}

// Foundry project is a child of the account
resource foundryProject 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: foundryAccount
  name: projectName
  properties: { description: projectDescription }
}

// Model deployment under the account (not project)
resource modelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: foundryAccount
  name: deploymentName   // e.g. 'gpt-5.4'
  sku: { name: deploymentSkuName, capacity: deploymentCapacityK }
  properties: {
    model: { format: 'OpenAI', name: 'gpt-5.4', version: '2026-03-05' }
  }
}

// IMPORTANT: Output the project endpoint in this format:
output projectEndpoint string = 'https://${foundryAccount.properties.customSubDomainName}.services.ai.azure.com/api/projects/${foundryProject.name}'
```

#### `infra/modules/role-assignments.bicep` — Required RBAC

```bicep
// Grant each agent + backend container app's managed identity these roles:
// - Cognitive Services OpenAI User (roleId: 5e0bd9bd-7b93-4f28-af87-19fc36ad61bd)
// - Azure AI User (roleId: 53ca9b11-8b9d-4b51-acae-26b3df39f6f0)
// Scope: the Foundry account resource
```

#### `infra/main.parameters.json`

```json
{
  "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
  "contentVersion": "1.0.0.0",
  "parameters": {
    "environmentName": { "value": "${AZURE_ENV_NAME}" },
    "location": { "value": "${AZURE_LOCATION}" },
    "azureOpenAIDeploymentName": { "value": "${AZURE_OPENAI_DEPLOYMENT_NAME}" },
    "deploymentSkuName": { "value": "${AZURE_OPENAI_DEPLOYMENT_SKU}" }
  }
}
```

---

### Step 5 — Generate `azure.yaml` (azd project descriptor)

```yaml
name: <project-slug>
metadata:
  template: <project-slug>@1.0
requiredVersions:
  azd: '>= 1.18.0'

hooks:
  preprovision:          # Validate region + prompt for SKU selection
    windows: { run: ..., shell: pwsh }
    posix:   { run: ..., shell: sh }
  postprovision:         # Build ACR images + run register_agents.py
    windows: { run: ..., shell: pwsh }
    posix:   { run: ..., shell: sh }

# Key postprovision steps:
# 1. az acr login --name $ACR_NAME
# 2. az acr build for each agent image + backend + frontend
# 3. export IMAGE_TAG=$(date -u +%Y%m%d%H%M%S)
# 4. python scripts/register_agents.py
```

---

### Step 6 — Generate Foundry Hosted Agent Files (per agent)

#### `agents/<name>/agent.yaml`

```yaml
# agent.yaml — Foundry Hosted Agent descriptor
name: <agent-name>                  # kebab-case, matches registration name
description: >
  One-paragraph description visible in Foundry portal agent list.
  Describe what this agent does, what tools it uses, and what it outputs.
runtime: agent-framework
version: "1.0.0"

resources:
  cpu: "1"       # "0.5" for lightweight reasoning-only agents
  memory: "2Gi"  # "1Gi" for lightweight agents

env:
  - name: AZURE_AI_PROJECT_ENDPOINT
    secretRef: azure-ai-project-endpoint
  - name: AZURE_OPENAI_DEPLOYMENT_NAME
    value: gpt-5.4
  # Add MCP server URLs for agents that use external tools
  - name: APPLICATION_INSIGHTS_CONNECTION_STRING
    secretRef: app-insights-connection-string
```

#### `agents/<name>/main.py` — MAF entry point pattern

```python
"""<AgentName> Hosted Agent — MAF entry point."""
import os
from agent_framework import SkillsProvider  # + MCPStreamableHTTPTool if using MCP
from agent_framework.azure import AzureOpenAIResponsesClient
from azure.ai.agentserver.agentframework import from_agent_framework
from azure.identity import DefaultAzureCredential
from schemas import <OutputSchema>

def main() -> None:
    # 1. App Insights env var normalization
    _ai_conn = os.environ.get("APPLICATION_INSIGHTS_CONNECTION_STRING")
    if _ai_conn:
        os.environ.setdefault("APPLICATIONINSIGHTS_CONNECTION_STRING", _ai_conn)

    # 2. Skills provider (loads skills/<name>-skill/skill.md)
    skills = SkillsProvider.from_directory("skills")

    # 3. (If MCP) Wire tools via MCPStreamableHTTPTool
    # tools = [MCPStreamableHTTPTool(server_url=os.environ["MCP_URL"], ...)]

    # 4. Azure OpenAI client
    client = AzureOpenAIResponsesClient(
        endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"],
        credential=DefaultAzureCredential(),
        model=os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-5.4"),
    )

    # 5. Start agent server with structured output
    from_agent_framework(
        client=client,
        skills=skills,
        # tools=tools,  # uncomment if using MCP
        default_options={"response_format": <OutputSchema>},
    ).run()

if __name__ == "__main__":
    main()
```

#### `agents/<name>/schemas.py`

```python
from pydantic import BaseModel, Field
from typing import Literal

class <OutputSchema>(BaseModel):
    """Structured output schema for <AgentName>."""
    # Define all output fields with Field(description=...) for every property
    # Include a confidence_score: float (0.0-1.0)
    # Include a confidence_level: Literal["HIGH", "MEDIUM", "LOW"]
    # Include a summary: str
    # Include domain-specific fields
    # Include an errors: list[str] = Field(default_factory=list)
```

#### `agents/<name>/Dockerfile`

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["python", "main.py"]
```

#### `agents/<name>/requirements.txt` (minimum)

```
azure-ai-agentserver>=1.0.0b17
agent-framework>=0.1.0
azure-identity>=1.19.0
openai>=1.65.0
pydantic>=2.0.0
httpx>=0.27.0
python-dotenv>=1.0.0
```

#### `agents/<name>/skills/<name>-skill/skill.md`

```markdown
# <Agent Name> — Domain Skill

## Role
You are a specialized <domain> agent responsible for <specific responsibility>.

## Instructions
<Detailed domain-specific instructions. Be explicit about:>
- What inputs you receive
- What external tools you call and when
- Decision criteria and thresholds
- What your output must contain
- Edge cases and fallback behavior

## Output Requirements
Always return a valid JSON response matching the <OutputSchema> Pydantic model.
Never return free-form text — all output must be structured.
```

---

### Step 7 — Generate Backend (FastAPI Orchestrator)

#### Orchestration pattern — `backend/app/agents/orchestrator.py`

```python
"""Multi-Agent Orchestrator — fan-out/fan-in coordination pattern."""
import asyncio

async def run_full_review(case_data: dict) -> dict:
    # Phase 1: Parallel agents (independent of each other)
    results = await asyncio.gather(
        run_agent_1(case_data),
        run_agent_2(case_data),
        return_exceptions=True,
    )

    # Phase 2: Sequential agents (depend on Phase 1 output)
    phase3_result = await run_agent_3({**case_data, "phase1_results": results})

    # Phase 3: Synthesis (receives all prior outputs)
    final = await run_synthesis({
        "phase1": results,
        "phase2": phase3_result,
    })
    return final
```

#### Two-mode dispatcher — `backend/app/agents/hosted_agents.py`

```python
"""Two-mode dispatcher: direct HTTP (local) or Foundry routing (production)."""
import os, httpx
from azure.identity.aio import DefaultAzureCredential

FOUNDRY_MODE = bool(os.environ.get("AZURE_AI_PROJECT_ENDPOINT"))

async def dispatch(agent_name: str, payload: dict) -> dict:
    if FOUNDRY_MODE:
        # Route through Foundry project endpoint with agent_reference
        endpoint = os.environ["AZURE_AI_PROJECT_ENDPOINT"]
        cred = DefaultAzureCredential()
        token = await cred.get_token("https://cognitiveservices.azure.com/.default")
        url = f"{endpoint}/responses"
        body = {**payload, "agent_reference": agent_name}
        headers = {"Authorization": f"Bearer {token.token}"}
    else:
        # Direct HTTP to local container
        host = os.environ.get(f"{agent_name.upper().replace('-','_')}_URL", f"http://{agent_name}:8000")
        url = f"{host}/responses"
        headers = {}
        body = payload

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(url, json=body, headers=headers)
        resp.raise_for_status()
        return resp.json()
```

#### `backend/app/config.py`

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    azure_ai_project_endpoint: str = ""
    azure_openai_deployment_name: str = "gpt-5.4"
    application_insights_connection_string: str = ""
    # Add per-agent URL overrides for local dev
    # e.g. agent_1_url: str = "http://agent-1:8000"

    class Config:
        env_file = ".env"
        extra = "allow"
```

---

### Step 8 — Generate `scripts/register_agents.py`

This script is the azd `postprovision` hook that registers and starts Foundry Hosted Agents.

**Must implement:**
1. `_create_mcp_connections()` — PUT idempotent MCP tool connections via ARM REST API (only if agents use MCP)
2. Per-agent dict with: `name`, `description`, `image`, `cpu`, `memory`, `env`, `tools`
3. `client.agents.create_version()` with `description=` passed explicitly (required for Foundry portal visibility)
4. `az cognitiveservices agent start` subprocess call to start each deployment
5. ACR image existence validation before registration

```python
# Key pattern for agent registration
agent_version = client.agents.create_version(
    agent_name=name,
    description=agent_def["description"],   # REQUIRED for Foundry portal Description column
    definition=HostedAgentDefinition(
        container_protocol_versions=[
            ProtocolVersionRecord(protocol=AgentProtocol.RESPONSES, version="v1")
        ],
        cpu=agent_def["cpu"],
        memory=agent_def["memory"],
        image=agent_def["image"],             # Full ACR image URI with tag
        environment_variables=agent_def["env"],
        tools=agent_def["tools"],
    ),
)
```

---

### Step 9 — Generate `docker-compose.yml`

```yaml
# Local development — all containers + required env vars
services:
  backend:
    build: ./backend
    ports: ["8000:8000"]
    environment:
      # No AZURE_AI_PROJECT_ENDPOINT → enables direct container routing
      - AZURE_OPENAI_DEPLOYMENT_NAME=gpt-5.4
    depends_on: [agent-1, agent-2, ...]

  agent-1:
    build: ./agents/<agent-1>
    ports: ["8001:8000"]
    environment:
      - AZURE_AI_PROJECT_ENDPOINT=${AZURE_AI_PROJECT_ENDPOINT}
      - AZURE_OPENAI_DEPLOYMENT_NAME=gpt-5.4

  frontend:
    build: ./frontend
    ports: ["3000:80"]
    environment:
      - NEXT_PUBLIC_API_URL=http://localhost:8000
```

---

### Step 10 — Generate Responsible AI Documents

#### `TRANSPARENCY_FAQ.md` — Must answer all of:

1. What is this solution?
2. What can it do?
3. What are its intended uses?
4. How was it evaluated?
5. What are its limitations?
6. What operational factors affect performance?

#### Key statements to include:
- This is a **solution accelerator, not a production-ready application**
- All AI outputs require **human review** before action
- The solution does **not include RBAC, authentication, or persistent storage** by default
- Production deployments require **compliance with applicable regulations**
- In-memory storage is used by default — **production requires a database**

---

### Step 11 — Generate `spec.yaml` (Foundry Template Gallery)

```yaml
type: apptemplate
name: <display-name>
version: 1
display_name: <display-name>
description: "<one-sentence value prop>"
longDescription: "<3-5 sentence description covering agents, tech stack, deployment>"
repository: https://github.com/microsoft/<repo-name>
languages:
 - python
 - typescript
author: Microsoft
models:
 - gpt-5.4
services:
 - "Microsoft Foundry"
 - "Microsoft Agent Framework"
 - "Azure OpenAI"
 - "Azure Container Apps"
 - "Azure Container Registry"
 - "Azure Monitor"
 - "Azure Application Insights"
templateType: SolutionTemplate
path: ./images
license: MIT
industry:
 - <Industry>
tags:
 - multi-agent
 - agent-framework
 - foundry-hosted-agents
 - azure-container-apps
 - <domain-specific-tag>
regions:
 - eastus2
 - swedencentral
disclaimer: "With any AI solutions you create using these templates, you are responsible for assessing all associated risks, and for complying with all applicable laws and safety standards."
```

---

### Step 12 — Generate Frontend (Next.js)

**Use Next.js 15 + TypeScript + Tailwind CSS + shadcn/ui.**

Key components to generate:

| Component | Purpose |
|---|---|
| `upload-form.tsx` | File/text input to submit a case for review |
| `progress-tracker.tsx` | Real-time pipeline phase indicators (polling) |
| `decision-panel.tsx` | Final decision display with confidence score + human override |
| `agent-details.tsx` | Expandable per-agent result cards |
| `confidence-bar.tsx` | Visual confidence indicator |
| `header.tsx` | App header with branding |

**`lib/api.ts`** — Typed API client wrapping `fetch` calls to the FastAPI backend.
**`lib/types.ts`** — TypeScript interfaces mirroring the backend Pydantic schemas.

---

### Step 13 — Observability Setup

Every agent `main.py` and the backend must:

1. Normalize env var: `APPLICATIONINSIGHTS_CONNECTION_STRING` ← `APPLICATION_INSIGHTS_CONNECTION_STRING`
2. The MAF `from_agent_framework().run()` handles OTel setup automatically when the env var is set
3. For the backend, configure OTel manually:

```python
# backend/app/observability.py
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter

def setup_observability(connection_string: str) -> None:
    if not connection_string:
        return
    exporter = AzureMonitorTraceExporter(connection_string=connection_string)
    provider = TracerProvider()
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
```

---

## Quality Checklist

Before delivering the scaffold, verify:

- [ ] Every `agent.yaml` has a `description:` field with meaningful content
- [ ] Every agent's `main.py` passes `default_options={"response_format": Schema}` for structured output
- [ ] `register_agents.py` passes `description=` to `create_version()`
- [ ] `main.bicep` outputs `AZURE_AI_PROJECT_ENDPOINT` in the format: `https://<subdomain>.services.ai.azure.com/api/projects/<project>`
- [ ] Role assignments grant both `Cognitive Services OpenAI User` + `Azure AI User` to agent identities
- [ ] `azure.yaml` postprovision hook builds ACR images with timestamp tag (`IMAGE_TAG=$(date -u +%Y%m%d%H%M%S)`)
- [ ] `docker-compose.yml` omits `AZURE_AI_PROJECT_ENDPOINT` from backend to trigger local mode
- [ ] `TRANSPARENCY_FAQ.md` explicitly states the solution is a **prototype/accelerator**, not production-ready
- [ ] README includes both runtime modes (Foundry Hosted Agent + Local Docker Compose)
- [ ] `spec.yaml` has `industry`, `tags`, and `regions` fields populated
- [ ] Interface screenshot is 1600×900 (scale-to-fit, no distortion)

---

## Architecture Diagram Reference

The solution follows this Azure-native architecture:

```
Internet
    │
    ▼
Frontend (Next.js)
Azure Container Apps
    │  REST
    ▼
Backend Orchestrator (FastAPI)
Azure Container Apps
    │
    ├──► Agent 1 ──► Foundry Hosted Agent ──► Azure OpenAI (gpt-5.4)
    │                     │                        via Foundry Project
    ├──► Agent 2 ──► Foundry Hosted Agent ──► Azure OpenAI (gpt-5.4)
    │                     │
    ├──► Agent 3 ──► Foundry Hosted Agent ──► Azure OpenAI (gpt-5.4)
    │                     │                        │
    │                     └──► MCP Tools ──────────┘
    │                          (ICD-10, NPI, CMS, PubMed...)
    │
    └──► Synthesis ──► Foundry Hosted Agent ──► Azure OpenAI (gpt-5.4)

Cross-cutting:
  Azure Application Insights ◄── All containers (OTel traces)
  Azure Container Registry   ◄── All Docker images
  Azure Monitor              ◄── Log Analytics workspace
```

**Bicep resource dependency order:**
`monitoring` → `ai-foundry` → `container-registry` → `container-apps-env` → `container-app (×N)` → `role-assignments`
```
