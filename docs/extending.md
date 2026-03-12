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

**`agents/new-agent/main.py`** — MAF agent wiring:

```python
import os
from pathlib import Path

import httpx
from agent_framework import FileAgentSkillsProvider, MCPStreamableHTTPTool
from agent_framework.azure import AzureOpenAIResponsesClient
from azure.ai.agentserver.agentframework import from_agent_framework
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

from schemas import NewAgentResult

load_dotenv(override=True)  # override=True required for Foundry-deployed env vars

# DeepSense CloudFront routes on User-Agent — omit this client if no MCP
_MCP_HTTP_CLIENT = httpx.AsyncClient(headers={"User-Agent": "claude-code/1.0"})


def main() -> None:
    new_tool = MCPStreamableHTTPTool(
        name="new-server",
        description="Brief description shown to the model",
        url=os.environ["MCP_NEW_SERVER"],
        http_client=_MCP_HTTP_CLIENT,
        load_prompts=False,
    )  # omit if no MCP

    skills_provider = FileAgentSkillsProvider(
        skill_paths=str(Path(__file__).parent / "skills")
    )

    agent = AzureOpenAIResponsesClient(
        project_endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"],
        deployment_name=os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"],
        credential=DefaultAzureCredential(),
    ).as_agent(
        name="new-agent",
        instructions="You are a ... agent for prior authorization requests.",
        tools=[new_tool],                             # omit if no MCP
        context_providers=[skills_provider],
        default_options={"response_format": NewAgentResult},
    )

    from_agent_framework(agent).run()


if __name__ == "__main__":
    main()
```

Key conventions:
- `schemas.py` declares the Pydantic output model; MAF enforces it at inference time (no JSON parsing needed)
- Import `AzureOpenAIResponsesClient` from `agent_framework.azure`, **not** from `azure.ai.agentserver`
- Constructor takes `project_endpoint` + `deployment_name` + `credential=DefaultAzureCredential()` — no API keys
- `name`, `instructions`, `tools`, `context_providers`, and `default_options` all go on `.as_agent()`, not the constructor
- `FileAgentSkillsProvider` is passed via `context_providers=[skills_provider]` in `.as_agent()`
- `MCPStreamableHTTPTool` with a shared `httpx.AsyncClient` injects the `User-Agent` header automatically; `load_prompts=False` prevents the agent server from trying to fetch MCP prompt lists on startup
- `load_dotenv(override=True)` is required — `override=True` ensures Foundry-injected env vars take precedence
- `from_agent_framework(agent).run()` exposes the agent as a `POST /responses` HTTP endpoint
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

**Step 3 — MCP wiring** (`agents/new-agent/main.py`):

If the agent uses MCP servers, add the `MCPStreamableHTTPTool` in `main.py` (already shown in Step 1) and expose the URL via an environment variable:

```yaml
# docker-compose.yml (local)
new-agent:
  environment:
    MCP_NEW_SERVER: https://mcp.example.com/new-server/mcp
```

For production (Azure), add the env var to the agent's `env:` block in `agents/new-agent/agent.yaml` —
agents are deployed via Foundry Hosted Agents, so MCP URLs belong in the agent descriptor rather than `infra/main.bicep`:

```yaml
# agents/new-agent/agent.yaml — inside the env: block
  - name: MCP_NEW_SERVER
    value: https://mcp.example.com/new-server/mcp
```

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
| `agents/new-agent/main.py` | New file: MAF agent, MCP wiring, `from_agent_framework` |
| `agents/new-agent/schemas.py` | New file: Pydantic output model |
| `agents/new-agent/skills/new-agent/SKILL.md` | New file: skill instructions |
| `agents/new-agent/Dockerfile` | New file: container image |
| `agents/new-agent/requirements.txt` | New file: `agent-framework-core>=1.0.0rc2,<=1.0.0rc3`, `azure-ai-agentserver-core>=1.0.0b16`, `azure-ai-agentserver-agentframework>=1.0.0b16`, `azure-identity`, `httpx`, `python-dotenv` (note: `azure-ai-projects` is resolved transitively) |
| `docker-compose.yml` | Add new agent service + env vars |
| `agents/new-agent/agent.yaml` | New file: Foundry Hosted Agent descriptor (name, runtime, resources, env vars) |
| `scripts/register_agents.py` | Add new agent to the registration list |
| `azure.yaml` | Add `az acr build` call for the new agent image in the postprovision hook |
| `backend/app/config.py` | Add `HOSTED_AGENT_NEW_NAME` setting (Foundry agent name) and optionally `NEW_AGENT_URL` (docker-compose URL) |
| `backend/app/services/hosted_agents.py` | Add dispatch call for new agent |
| `backend/app/agents/orchestrator.py` | Import, phase registration, synthesis prompt, SSE events |
| `frontend/lib/types.ts` | Add agent ID to types |
| `frontend/components/progress-tracker.tsx` | Render new agent status |
| `backend/app/services/audit_pdf.py` | Render new agent data in PDF (optional) |

---

## Add a New MCP Server

MCP is wired **per agent container** — there is no central MCP registry in the backend.
Four files need changes:

**Step 1 — Add `MCPStreamableHTTPTool`** (`agents/<target-agent>/main.py`):

```python
cpt_tool = MCPStreamableHTTPTool(
    name="cpt-validator",
    description="Validate CPT/HCPCS procedure codes and look up RVU values",
    url=os.environ["MCP_CPT_VALIDATOR"],
    http_client=_MCP_HTTP_CLIENT,          # reuse the shared client
    load_prompts=False,
)

agent = AzureOpenAIResponsesClient(
    project_endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"],
    deployment_name=os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"],
    credential=DefaultAzureCredential(),
).as_agent(
    name="clinical-reviewer-agent",
    instructions="...",
    tools=[..., cpt_tool],             # add to existing tools list
    context_providers=[skills_provider],
    default_options={"response_format": ClinicalResult},
)
```

**Step 2 — Environment variable** (`docker-compose.yml` and Azure container env):

```yaml
clinical-agent:
  environment:
    MCP_CPT_VALIDATOR: https://mcp.example.com/cpt-validator/mcp
```

**Step 3 — SKILL.md** (`agents/<target-agent>/skills/<skill-name>/SKILL.md`):

```markdown
#### CPT Validator MCP (cpt-validator)
- `mcp__cpt-validator__validate_cpt(code)` — Check if CPT code is valid
- `mcp__cpt-validator__lookup_cpt(code)` — Get description and RVU value
```

**Step 4 — Orchestrator** (only if adding a new agent role).

**Architecture summary:**

```
agents/<agent>/main.py               → MCPStreamableHTTPTool instantiation
docker-compose.yml                   → MCP URL env var (local)
infra/main.bicep                     → MCP URL env var (production, agent env: block)
agents/<agent>/skills/*/SKILL.md     → Usage instructions for the agent
backend/app/agents/orchestrator.py   → Pipeline phases (only if adding a new agent role)
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

## Use MCP with Azure OpenAI Models

Use `MCPStreamableHTTPTool` from the Agent Framework:

```python
import httpx
from agent_framework import MCPStreamableHTTPTool

http_client = httpx.AsyncClient(headers={"User-Agent": "claude-code/1.0"})
mcp_tool = MCPStreamableHTTPTool(
    name="npi",
    description="Validate NPI numbers",
    url=NPI_URL,
    http_client=http_client,
    load_prompts=False,
)

async with mcp_tool:
    result = await mcp_tool.session.call_tool("npi_validate", {"npi": "1234567893"})
```

In the current architecture this MCP wiring lives directly in the agent container's `main.py`; the backend only orchestrates HTTP calls to the `/responses` endpoints.

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
