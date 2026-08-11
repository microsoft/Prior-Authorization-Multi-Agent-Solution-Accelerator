# Extending the Application

## Add a New Agent

The multi-agent pipeline can be extended with additional agent roles (e.g., a
Pharmacy Benefits agent, Prior Treatment Verification agent, or Financial
Review agent). Each agent follows a consistent pattern across seven files:

**Step 1 — Agent container** (`agents/new-agent/main.py` + `agents/new-agent/schemas.py`):

Create a new agent container following the same pattern as the four existing agents:

**`agents/new-agent/schemas.py`** — declare the structured output model:

```python
from pydantic import BaseModel
from typing import Optional

class NewAgentResult(BaseModel):
    status: str
    findings: list[str]
    confidence: int
    summary: Optional[str] = None
```

**`agents/new-agent/main.py`** — refreshed Hosted Agents preview wiring:

```python
import os
from pathlib import Path

from agent_framework import Agent, SkillsProvider
from agent_framework.foundry import FoundryChatClient
from agent_framework_foundry_hosting import ResponsesHostServer
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

from schemas import NewAgentResult

load_dotenv(override=True)  # override=True required for Foundry-deployed env vars


def main() -> None:
    # MCP tools are wired in-container via MCPStreamableHTTPTool. Read the
    # MCP_* env var declared in agents/<name>/agent.yaml (Foundry deploy) or
    # docker-compose.yml (local dev) and append to `tools` below. See
    # agents/clinical/main.py for a working example.

    skills_provider = SkillsProvider.from_paths(
        str(Path(__file__).parent / "skills"),
        # Required for unattended use: skill tools default to
        # approval_mode="always_require", which makes the agent stop on an
        # mcp_approval_request instead of returning a result.
        disable_load_skill_approval=True,
        disable_read_skill_resource_approval=True,
    )

    project_endpoint = os.environ.get(
        "FOUNDRY_PROJECT_ENDPOINT"
    ) or os.environ["AZURE_AI_PROJECT_ENDPOINT"]
    model = os.environ.get(
        "MODEL_DEPLOYMENT_NAME"
    ) or os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"]

    chat_client = FoundryChatClient(
        project_endpoint=project_endpoint,
        model=model,
        credential=DefaultAzureCredential(),
        allow_preview=True,
    )

    agent = Agent(
        client=chat_client,
        name="new-agent",
        id="new-agent",  # Must match the agent name registered with `azd ai agent` (used in Foundry Traces)
        instructions="You are a ... agent for prior authorization requests.",
        tools=[],                                      # in-container tools, if any
        context_providers=[skills_provider],
        default_options={"response_format": NewAgentResult, "store": False},
    )

    ResponsesHostServer(agent).run()


if __name__ == "__main__":
    main()
```

Key conventions:
- `schemas.py` declares the Pydantic output model; the framework enforces it at inference time (no JSON parsing needed)
- Import `FoundryChatClient` from `agent_framework.foundry` and `Agent` from `agent_framework`
- `FoundryChatClient` takes `project_endpoint` + `model` + `credential=DefaultAzureCredential()` + `allow_preview=True` — no API keys
- `name`, `instructions`, `tools`, `context_providers`, and `default_options` all go on `Agent(...)`
- `SkillsProvider` is passed via `context_providers=[skills_provider]`
- `default_options` must include `"store": False` because the refreshed preview manages conversation history at the platform level
- **MCP tools are wired in-container** via `MCPStreamableHTTPTool` — read the URL from an `MCP_*` env var declared in `agents/<name>/agent.yaml`. The base class handles transport-level reconnects automatically; all current MCPs in this accelerator are stateless and need no extra wrapping
- `load_dotenv(override=True)` is required — `override=True` ensures env vars set by the `azd ai agent` extension take precedence

> **Alternative — Foundry-hosted Tools (preview).** If your MCP servers are
> session-stable (no idle reconnects required) and you want per-tool RBAC and
> centralised audit logging at the project level, you can swap in-container
> tools for Foundry-hosted tools: register the MCP under `tools:` in the project,
> reference it from each agent's `agent.yaml` `tools:` block, and remove the
> `MCPStreamableHTTPTool` instantiation from `main.py`. Trade-offs to weigh:
> (1) the platform doesn't expose MCP session-reconnect hooks — servers like
>     PubMed that drop idle sessions still need the in-container path;
> (2) you lose the shared `httpx.AsyncClient` connection pool across MCPs;
> (3) you add a hop (`agent → tool runtime → MCP`) and a new role assignment
>     for each agent's instance identity. The default in-container path stays
>     simpler for public, session-stable MCPs and avoids preview-on-preview risk.
- `ResponsesHostServer(agent).run()` exposes the agent on the dedicated Foundry endpoint (port `8088` locally)
- Agents that need upstream results receive them as JSON in the request payload

**Step 2 — SKILL.md** (`agents/new-agent/skills/new-agent/SKILL.md`):

```markdown
# [Role Name] Skill

## Description
One-liner describing what this agent does.

## Instructions
[Same content as NEW_AGENT_INSTRUCTIONS — keep synced]

### Available MCP Tools (if applicable)
- `mcp__server-name__tool_name(param)` — Description

### Output Format
Return JSON:
{
    "field": "value"
}

### Quality Checks
Before completing, verify:
- [ ] All required fields present in output
- [ ] Output is valid JSON

### Common Mistakes to Avoid
- Do NOT generate fake data when a tool call fails
- Do NOT make final approval/denial decisions (synthesis agent does that)
```

**Step 3 — MCP tool wiring** (`agents/new-agent/agent.yaml` + `agents/new-agent/main.py`):

Declare the MCP endpoint as an env var in `agent.yaml` and wire it in-container
in `main.py` via `MCPStreamableHTTPTool`. The `azd ai agent` extension
propagates the env var to the running container at `create_version()` time.

```yaml
# agents/new-agent/agent.yaml
env_vars:
  MCP_NEW_SERVER: https://mcp.example.com/new-server/mcp
```

```python
# agents/new-agent/main.py
from agent_framework import MCPStreamableHTTPTool

tools = [
    MCPStreamableHTTPTool(
        name="new-server",
        description="...",
        url=os.environ["MCP_NEW_SERVER"],
        headers={"User-Agent": "claude-code/1.0"},  # if required
    ),
]
agent = Agent(client=chat_client, tools=tools, ...)
```

For servers with session-expiry quirks, you can subclass
`MCPStreamableHTTPTool` and override `call_tool()` to catch
`McpError('Session terminated')` and reconnect. None of the current MCPs in
this accelerator require this workaround — all five are stateless.

See [Add a New MCP Server](#add-a-new-mcp-server) for the full pattern.

**Step 4 — Orchestrator** (`backend/app/agents/orchestrator.py`):

Import and register the agent in `run_multi_agent_review()`:

```python
from app.agents.new_agent import run_new_review
```

The pipeline has four phases:

```
Phase 1 (parallel):   Compliance + Clinical  → asyncio.gather()
Phase 2 (sequential): Coverage (needs Clinical findings)
Phase 3 (synthesis):  Reasoning-only, all results as input
Phase 4 (audit):      Build audit trail + justification PDF
```

To add a parallel agent:
```python
new_task = asyncio.create_task(
    _safe_run("New Agent", run_new_review, request_data)
)
compliance_result, clinical_result, new_result = await asyncio.gather(
    compliance_task, clinical_task, new_task
)
```

To add a sequential agent:
```python
new_result = await _safe_run(
    "New Agent", run_new_review, request_data, clinical_result
)
```

**Step 5 — Synthesis prompt** (`backend/app/agents/orchestrator.py`):

Add the new agent's output to the synthesis prompt:

```python
prompt = f"""...existing synthesis prompt...

--- NEW AGENT REPORT ---
{json.dumps(new_result, indent=2, default=str)}

--- END REPORTS ---
..."""
```

**Step 6 — SSE progress events** (`backend/app/agents/orchestrator.py`):

Add the new agent to progress event emissions:

```python
await _emit({
    "phase": "phase_1",
    "agents": {
        "compliance": {"status": "running", "detail": "..."},
        "clinical": {"status": "running", "detail": "..."},
        "new_agent": {"status": "running", "detail": "Starting..."},
    },
})
```

Update `frontend/lib/types.ts` and `ProgressTracker` for the new agent.

**Step 7 — Audit trail and PDF** (optional):

Update `_build_audit_trail()`, `_generate_audit_justification()`, and
`generate_audit_justification_pdf()` for the new agent's data.

**Summary of files touched:**

| File | Change |
|------|--------|
| `agents/new-agent/main.py` | New file: Agent definition + `ResponsesHostServer` + in-container MCP tool wiring (read `MCP_*` env vars and instantiate `MCPStreamableHTTPTool`) |
| `agents/new-agent/schemas.py` | New file: Pydantic output model (must match SKILL.md output format exactly — the framework enforces schema at token level) |
| `agents/new-agent/skills/new-agent/SKILL.md` | New file: skill instructions |
| `agents/new-agent/Dockerfile` | New file: container image. Copy an existing agent's Dockerfile verbatim — it must run as **root** (Foundry mounts the per-session state volume at `$HOME=/home/session` as root; a non-root UID cannot create `$HOME/.sessions` and the container dies before `/readiness` binds). |
| `agents/new-agent/requirements.txt` | New file: `agent-framework-core>=1.13.0,<2`, `agent-framework-foundry>=1.10.4,<2`, `agent-framework-foundry-hosting>=1.0.0b260730,<2`, `azure-ai-agentserver-core>=2.0.0,<3`, `azure-identity`, `python-dotenv`, `httpx`, `mcp>=1.24.0,<2` (the last two are required for in-container `MCPStreamableHTTPTool`) |
| `docker-compose.yml` | Add new agent service + env vars |
| `agents/new-agent/agent.yaml` | New file: hosted agent descriptor consumed by the `azd ai agent` extension during `azd deploy`. Declares kind, image, cpu, memory, `container_protocol_versions`, and `env_vars` (including `MCP_*` URLs). |
| `azure.yaml` | The `azd ai agent` extension auto-discovers agents under `agents/` — no manual entry needed. |
| `backend/app/models/schemas.py` | Add matching Pydantic model (must stay in sync with `agents/new-agent/schemas.py`) |
| `azure.yaml` | Add `az acr build` call for the new agent image in the postprovision hook (only needed if you build images outside the `azd ai agent` flow); also add the agent name to `scripts/grant_agent_rbac.py`'s `HOSTED_AGENTS` tuple |
| `backend/app/config.py` | Add `HOSTED_AGENT_NEW_NAME` setting (Foundry agent name) and optionally `NEW_AGENT_URL` (docker-compose URL) |
| `backend/app/services/hosted_agents.py` | Add dispatch call for new agent |
| `backend/app/agents/orchestrator.py` | Import, phase registration, synthesis prompt, SSE events |
| `frontend/lib/types.ts` | Add agent ID to types |
| `frontend/components/progress-tracker.tsx` | Render new agent status |
| `backend/app/services/audit_pdf.py` | Render new agent data in PDF (optional) |

---

## Add a New MCP Server

All MCP servers in this accelerator are wired **in-container** via
`MCPStreamableHTTPTool` (see [architecture.md](architecture.md#mcp-integration)).
The refreshed Foundry preview's platform-managed `MCPTool` model is currently
rejected by the agent-server runtime, so a single in-container path is used
uniformly. The same code paths run in both Foundry and `docker-compose` modes —
only the source of the `MCP_*` env vars differs.

### Step 1 — Declare the endpoint in `agents/<target-agent>/agent.yaml`

```yaml
env_vars:
  MCP_CPT_VALIDATOR: https://mcp.example.com/cpt-validator/mcp
```

Also add the same env var to the agent's service block in `docker-compose.yml`
so local-dev mode can reach the server.

### Step 2 — SKILL.md (`agents/<target-agent>/skills/<skill-name>/SKILL.md`)

```markdown
#### CPT Validator MCP (cpt-validator)
- `mcp__cpt-validator__validate_cpt(code)` — Check if CPT code is valid
- `mcp__cpt-validator__lookup_cpt(code)` — Get description and RVU value
```

### Step 3 — Wire the tool in `agents/<target-agent>/main.py`

Append an `MCPStreamableHTTPTool` (or a session-aware subclass) to the agent's
`tools` list:

```python
# agents/<target-agent>/main.py
from agent_framework import MCPStreamableHTTPTool

tools = [
    MCPStreamableHTTPTool(
        name="cpt-validator",
        description="Validate CPT codes and get RVU values",
        url=os.environ["MCP_CPT_VALIDATOR"],
        headers={"User-Agent": "claude-code/1.0"},  # if the server requires it
    ),
]
agent = Agent(client=chat_client, tools=tools, ...)
```

For servers with session-expiry quirks, subclass `MCPStreamableHTTPTool` and
catch `McpError('Session terminated')` to reconnect. None of the MCPs
currently used by this accelerator need this workaround — all are stateless.

### Step 4 — Orchestrator

Only if adding a new agent role.

### Architecture summary

```
agents/<agent>/agent.yaml             → MCP_* env var declarations (Foundry mode)
docker-compose.yml                    → MCP_* env var declarations (local mode)
agents/<agent>/main.py                → MCPStreamableHTTPTool wiring (single code path)
agents/<agent>/skills/*/SKILL.md      → Usage instructions for the model
backend/app/agents/orchestrator.py    → Pipeline phases (only if adding a new agent role)
```

---

## Change the Decision Rubric

Edit the synthesis agent's SKILL.md:

```
agents/synthesis/skills/synthesis-decision/SKILL.md
```

Domain experts can update the gate criteria, confidence weights, and decision thresholds without touching any Python code.

---

## Customize Notification Letters

Edit `backend/app/services/notification.py`. The `generate_approval_letter()`
and `generate_pend_letter()` functions accept parameters and produce structured
text. The `generate_letter_pdf()` function renders a professionally formatted
PDF using `fpdf2`.

---

## Add CPT/HCPCS Codes to the Lookup Table

Edit `_KNOWN_CODES` in `backend/app/services/cpt_validation.py`.

---

## Re-deploy Only the Backend or Frontend Image

The four hosted agents are declared as `azd` services in [azure.yaml](../azure.yaml)
(`host: azure.ai.agent`), so iterating on a single agent works the standard way:

```bash
azd deploy clinical-reviewer-agent
```

The **backend** and **frontend** are intentionally **not** declared as `azd` services —
they are built and rolled by the `postprovision` hook (`az acr build` +
`az containerapp update`) to avoid a chicken-and-egg cycle with Bicep on first
provision (Bicep needs an image reference; the image needs Bicep's ACR to push to).
This means `azd deploy backend` / `azd deploy frontend` are not supported. To
re-deploy just the backend or frontend image after a code change, run:

```bash
azd provision    # re-runs postprovision: rebuilds + rolls backend & frontend images
```

Inner-loop development on the backend or frontend should use `docker-compose up`
(see [DeploymentGuide.md](DeploymentGuide.md#local-docker-compose-mode)) — the
hot-reload loop is far faster than a full `azd provision`.

---

## Use MCP with Foundry Hosted Agents

All MCP tools are wired **in-container** via `MCPStreamableHTTPTool` inside
each agent's `main.py` — see [architecture.md](architecture.md#mcp-integration)
for the rationale. URLs are declared as `MCP_*` env vars in
`agents/<name>/agent.yaml` (Foundry deploy) and `docker-compose.yml` (local).
The same Python code paths run in both modes.

To call a hosted agent from outside the container (e.g. from a notebook), use
the per-agent dedicated endpoint:

```python
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

project = AIProjectClient(
    endpoint=PROJECT_ENDPOINT,
    credential=DefaultAzureCredential(),
    allow_preview=True,
)
# get_openai_client(agent_name=...) returns a client pre-bound to the agent's
# dedicated endpoint — no extra_body or agent_reference needed.
openai_client = project.get_openai_client(agent_name="clinical-reviewer-agent")

response = openai_client.responses.create(input="Validate NPI 1234567893")
print(response.output_text)
```

The model sees in-container tools as `mcp__<tool_name>` (matching the `name=`
argument passed to `MCPStreamableHTTPTool`), so SKILL.md instructions stay
stable across runtime modes.

---

## Future Enhancement: Azure AI Search for Policy RAG

The current system retrieves coverage policies at runtime via the **CMS Coverage MCP server**, which provides Medicare LCDs and NCDs. This works well for Medicare cases but has limitations — the Synthesis agent already flags this with a disclaimer:

> *"Coverage policies reflect Medicare LCDs/NCDs only. If this review is for a commercial or Medicare Advantage plan, payer-specific policies may differ."*

**Azure AI Search** with vector indexing could significantly enhance the system by enabling semantic retrieval over a broader set of policy documents. Below are the opportunities, organized by which agent would benefit.

### Where AI Search Adds Value

| Agent | Index Content | What It Enables |
|-------|--------------|-----------------|
| **Coverage Agent** | Commercial payer PA policies (UHC, Aetna, BCBS, Cigna, etc.) | Payer-specific coverage criteria instead of Medicare-only. E.g., "UHC requires 6 weeks of conservative therapy before approving spinal fusion." |
| **Coverage Agent** | Medicare Advantage plan-specific supplements | Plan-level nuances beyond standard Medicare LCDs/NCDs |
| **Clinical Agent** | Clinical practice guidelines (ACR Appropriateness Criteria, NCCN, AUA, etc.) | Evidence-based clinical reasoning beyond what PubMed MCP returns — structured guidelines rather than raw literature |
| **Compliance Agent** | Organization-specific PA submission requirements | Internal checklists, required documentation templates, payer-specific form requirements |
| **Synthesis Agent** | Historical PA decisions (vectorized) | Precedent-based reasoning — "95% of similar cases with this diagnosis and procedure were approved" |

### How It Would Work

Azure AI Search would be exposed as an **MCP tool** (or direct SDK call) that agents query during their review:

```
Coverage Agent prompt → "Search payer policies for CPT 22630 with UnitedHealthcare"
                      → AI Search vector query → top-k relevant policy chunks
                      → Agent reasons over retrieved policy text
```

Each index would use:
- **Vector embeddings** (Azure OpenAI `text-embedding-3-large`) for semantic search
- **Hybrid search** (vector + keyword) for policy ID lookups
- **Metadata filters** (payer name, effective date, procedure category) for precision

### What You Would Need

| Requirement | Details |
|-------------|---------|
| **Policy documents** | PDFs or structured text from commercial payers. These are typically proprietary and obtained through payer contracts or provider portals. |
| **Azure AI Search resource** | Standard tier or higher for vector search support |
| **Embedding model** | An Azure OpenAI embedding deployment (e.g., `text-embedding-3-large`) in the same region |
| **Ingestion pipeline** | Document chunking, embedding, and indexing — can use Azure AI Search's built-in [integrated vectorization](https://learn.microsoft.com/en-us/azure/search/vector-search-integrated-vectorization) or a custom pipeline |
| **MCP server or tool wrapper** | Expose the search index as a tool the agents can call |

### What It Does NOT Replace

AI Search is a **retrieval** layer — it complements, not replaces, the existing MCP tools:

| Data Source | Keep Using | Why |
|-------------|-----------|-----|
| CMS Coverage MCP | ✅ | Live, authoritative Medicare LCD/NCD data |
| NPI Registry MCP | ✅ | Real-time provider verification |
| ICD-10 MCP | ✅ | Code validation and lookup |
| PubMed MCP | ✅ | Current medical literature |
| Clinical Trials MCP | ✅ | Active trial matching |

AI Search would add a **sixth data source** — payer policy documents — not replace the existing five.

### Implementation Priority

This enhancement is most valuable when:
1. The system needs to handle **commercial payer** cases (not just Medicare)
2. The organization has **access to payer policy documents** to index
3. There is a need for **historical decision** consistency across reviewers

Until policy documents are available for ingestion, the current CMS-only approach is appropriate for the demo scope.
