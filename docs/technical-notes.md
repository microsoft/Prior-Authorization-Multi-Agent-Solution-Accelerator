# Technical Notes

## Architecture Overview

The backend is a **pure HTTP dispatcher** (FastAPI). It has no local AI runtime.
All specialist reasoning runs in four independent Foundry Hosted Agent containers.

```
Frontend (Next.js / ACA)
  └── POST /api/review/stream   (SSE)
        └── FastAPI Backend / Orchestrator (ACA)
              │
              ├─── [Docker Compose — local dev] ──────────────────────────────────────
              │    POST http://agent-{name}/responses   (HOSTED_AGENT_*_URL)
              │    → Clinical / Compliance / Coverage / Synthesis Container
              │
              └─── [Foundry Hosted Agents — refreshed preview (azd up)] ──────────
                   AIProjectClient(allow_preview=True)
                       .get_openai_client(agent_name="clinical-reviewer-agent")
                   → POST {project_endpoint}/agents/{name}/endpoint/protocols/openai/v1/responses
                         Authorization: Bearer <DefaultAzureCredential>
                   → Foundry routes to per-agent dedicated container
```

Each agent container runs the **Microsoft Agent Framework** refreshed-preview
stack (`agent-framework-core` + `agent-framework-foundry` +
`agent-framework-foundry-hosting`) and is hosted by
`agent_framework_foundry_hosting.ResponsesHostServer`. Agents are registered
with **Microsoft Foundry** by `azd deploy` itself — each agent has a
`host: azure.ai.agent` entry in the repo-root `azure.yaml` that the
`azd ai agent` extension uses to ACR-build the image, push it, and call
`create_version()` on the project. A `postdeploy` hook
(`scripts/grant_agent_rbac.py`) then grants `Foundry User` to each agent's
per-instance Application identity so it can serve the Responses API.

---

## MCP Tool Connections

All five MCP servers are wired **in-container** via
`MCPStreamableHTTPTool`. The refreshed Hosted Agents preview rejects the
legacy `tools: [{type: mcp, ...}]` definition entries, so the older
Foundry-managed MCPTool model is no longer used. See
[architecture.md § "MCP Integration"](architecture.md#mcp-integration) for
the full rationale.

| MCP Server | Wiring | Where defined |
|---|---|---|
| ICD-10 codes | In-container `MCPStreamableHTTPTool` | `agents/clinical/main.py` (URL from `MCP_ICD10_CODES` env var) |
| Clinical Trials | In-container `MCPStreamableHTTPTool` | `agents/clinical/main.py` (URL from `MCP_CLINICAL_TRIALS` env var) |
| NPI Registry | In-container `MCPStreamableHTTPTool` | `agents/coverage/main.py` (URL from `MCP_NPI_REGISTRY` env var) |
| CMS Coverage | In-container `MCPStreamableHTTPTool` | `agents/coverage/main.py` (URL from `MCP_CMS_COVERAGE` env var) |
| PubMed | In-container `MCPStreamableHTTPTool` | `agents/clinical/main.py` (URL from `MCP_PUBMED` env var) |

Four of the five MCPs (ICD-10, Clinical Trials, NPI Registry, CMS Coverage)
live on Anthropic's healthcare gateway at `hcls.mcp.claude.com`; PubMed
has its own subdomain at `pubmed.mcp.claude.com`. All five are stateless
HTTPS endpoints — no session-expiry workarounds are required. Each agent
injects `User-Agent: claude-code/1.0` via a shared `httpx.AsyncClient` as
defensive insurance because the Cloudflare gateway blocks the default
`Python-urllib/*` UA but accepts any other identifier.

In both Foundry deployment (`agent.yaml` `environment_variables`) and
docker-compose local dev (`docker-compose.yml`), the `MCP_*` env vars are
set with the same Anthropic-hosted URLs as defaults, so the in-container
wiring behaves identically across modes.

---

## Agent Skills

Each agent loads its SKILL.md via `SkillsProvider`:

```python
skills_provider = SkillsProvider.from_paths(
    str(Path(__file__).parent / "skills"),
    disable_load_skill_approval=True,
    disable_read_skill_resource_approval=True,
)
```

> `agent-framework-core` 1.2.0 moved file-based construction from
> `SkillsProvider(skill_paths=...)` (initial preview) to the
> `SkillsProvider.from_paths(...)` factory — the old form raises `TypeError`
> at import time and surfaces as HTTP `424 session_not_ready`.
>
> The `disable_*_approval` arguments are required for unattended server-side
> use. `agent-framework-core` registers skill tools with
> `approval_mode="always_require"` by default, so without them the agent emits
> an `mcp_approval_request` and stops instead of returning a result — the
> backend then reports `Agent <name> returned empty output`. `run_skill_script`
> deliberately still requires approval; none of these skills ship a script.

SKILL.md files live alongside the agent:

```
agents/
  clinical/skills/clinical-review/SKILL.md      # ICD-10 validation, clinical extraction (< 60% warning), literature + trials
  coverage/skills/coverage-assessment/SKILL.md  # Provider NPI, specialty-procedure match, CMS policy, criteria mapping
  compliance/skills/compliance-review/SKILL.md  # 10-item checklist (items 9: NCCI, 10: service type are non-blocking)
  synthesis/skills/synthesis-decision/SKILL.md  # Gate rubric, weighted confidence, synthesis_audit_trail output
```

---

## Structured Output

Each agent container declares a local Pydantic model in `schemas.py` and
passes it via the `default_options` parameter on `Agent`:

```python
from agent_framework import Agent
from agent_framework.foundry import FoundryChatClient
from agent_framework_foundry_hosting import ResponsesHostServer

chat_client = FoundryChatClient(project_endpoint=..., model=..., credential=..., allow_preview=True)
agent = Agent(
    client=chat_client,
    name="clinical-reviewer-agent",
    id="clinical-reviewer-agent",  # Must match registered name for Foundry Traces
    tools=[...],
    default_options={"response_format": ClinicalResult, "store": False},
)
ResponsesHostServer(agent).run()
```

The `store: False` option is required because the refreshed preview manages
conversation history at the platform level. The framework enforces the
`response_format` schema as a token-level JSON constraint at inference time —
no post-processing or regex extraction needed. The backend dispatcher reads
the text payload from the OpenAI SDK response:

```python
# hosted_agents.py
output_text = response.output_text
return json.loads(output_text)
```

The Pydantic models live in each agent container:

| Agent | Schema file | Root model |
|-------|-------------|------------|
| Clinical | `agents/clinical/schemas.py` | `ClinicalResult` |
| Compliance | `agents/compliance/schemas.py` | `ComplianceResult` |
| Coverage | `agents/coverage/schemas.py` | `CoverageResult` |
| Synthesis | `agents/synthesis/schemas.py` | `SynthesisOutput` (includes `synthesis_audit_trail: str` — JSON-encoded audit trail with `gate_results` and `confidence_components`; parsed back to `dict` by the orchestrator) |

---

## Orchestration Flow

```
Phase 1 (parallel):   Compliance + Clinical agents
Phase 2 (sequential): Coverage agent (receives clinical findings)
Phase 3:              Synthesis agent (receives all three results)
Phase 4:              Audit trail + PDF generation
```

### Resilience

| Mechanism | Where | What it does |
|-----------|-------|-------------|
| Result validation | `_validate_agent_result()` | Checks expected top-level keys |
| Automatic retry | `_safe_run()` | Retries once if validation fails |
| SSE status warnings | Phase events | Reports status "warning" for incomplete results |
| Tool result normalization | `_normalize_tool_result()` | Maps non-standard status values |

### Decision Gate (LENIENT MODE)

Gate 1: Provider NPI verification → Gate 2: Code validation → Gate 3: Medical necessity

Default to **PEND** at any uncertain gate. Never DENY in LENIENT mode.

---

## Decision and Notification Flow

1. Review completes → stored in-memory (reviewed via `GET /api/reviews`)
2. Frontend shows Accept / Override panel
3. `POST /api/decision` prevents double-decisions (409)
4. Generates thread-safe authorization number (`PA-YYYYMMDD-XXXXX`)
5. Produces notification letter (approval or pend) in text and PDF

**Letter types:**
- **Approval** — auth number, 90-day validity, coverage criteria met, clinical rationale
- **Pend** — confidence level, missing documentation, 30-day deadline, appeal rights

---

## CPT/HCPCS Validation

Pre-flight step before agents execute:

1. **Format validation** — regex for CPT (5-digit) or HCPCS (letter + 4 digits)
2. **Curated lookup** — ~30 common PA-trigger codes
3. **Results injected** into synthesis prompt for Gate 2

---

## Sample Data

The frontend includes a **"Load Sample Case"** button for a CT-guided
transbronchial lung biopsy case:

| Field | Value |
|-------|-------|
| Patient | John Smith, DOB 1958-03-15 |
| Provider NPI | 1720180003 (active pulmonologist) |
| ICD-10 codes | R91.1, J18.9, R05.9 |
| CPT code | 31628 |
| Insurance ID | MCR-123456789A |

---

## Observability

All five processes — the FastAPI backend and all four agent containers — export
OpenTelemetry traces and metrics to **Azure Application Insights** via
`azure-monitor-opentelemetry`. Agent traces are also visible in the Foundry
portal's built-in Traces view when App Insights is linked to the Foundry project.

### Process Roles

| Process | OTel service name | What it instruments |
|---------|-------------------|---------------------|
| FastAPI backend | `prior-auth-backend` (set via `OTEL_SERVICE_NAME`) | HTTP requests/responses, outgoing httpx calls to agents, logs, exceptions, live metrics |
| Clinical agent | `azure.ai.agentserver` (hard-coded by the host) | MAF `invoke_agent`, `chat`, `execute_tool` spans, token metrics. Per-agent identity via `gen_ai.agent.name` (= `FOUNDRY_AGENT_NAME`) |
| Coverage agent | `azure.ai.agentserver` | Same as above |
| Compliance agent | `azure.ai.agentserver` | Same as above |
| Synthesis agent | `azure.ai.agentserver` | Same as above |

Each process configures observability differently based on its role:

- **Backend** (`observability.py`): Calls `configure_azure_monitor()` directly
  before the FastAPI app starts. This is the standard Azure Monitor SDK pattern
  for non-MAF applications.
- **Agent containers**: Do NOT set `OTEL_SERVICE_NAME` (the host derives the
  service name from the platform-injected `FOUNDRY_AGENT_NAME`). When
  `APPLICATIONINSIGHTS_CONNECTION_STRING` is present, each agent's `main.py`
  calls `agent_framework.observability.enable_instrumentation(...)` BEFORE
  constructing the `Agent` and `ResponsesHostServer`. This is the supported
  pattern from the Microsoft Agent Framework observability docs — without it,
  MAF's `gen_ai.*` span emission code paths stay dormant and the App Insights
  pipeline only carries platform-side spans (model calls, MCP tools), missing
  the agent-layer spans (`agent.run`, tool execution lifecycle, handoffs).
  Agent code also bridges the legacy `APPLICATION_INSIGHTS_CONNECTION_STRING`
  (with underscore) to the canonical no-underscore form for docker-compose
  parity — in production the `agent.yaml` `environment_variables` block sets
  `OTEL_CONNECTION_STRING` (the platform reserves the canonical
  `APPLICATIONINSIGHTS_CONNECTION_STRING` name) and `main.py` overwrites the
  malformed platform-injected value with it before the host server starts.

> **Note on host vs MAF instrumentation:** `ResponsesHostServer` itself does
> NOT auto-configure MAF instrumentation in its constructor — confirmed by
> reading the Python source. The platform exports its own spans (model
> invocations, MCP tool calls) regardless, but MAF's agent-layer spans are
> opt-in via `enable_instrumentation()` (or the equivalent env vars
> `ENABLE_INSTRUMENTATION=true` / `ENABLE_SENSITIVE_DATA=true`).

### Agent ID / Name for Trace Correlation

The refreshed Hosted Agents preview gives every agent a dedicated Entra
identity at deploy time (`agent.instance_identity.principal_id`) and the
platform injects `FOUNDRY_AGENT_NAME`, `FOUNDRY_AGENT_VERSION`, and
related dimensions into the container at runtime, so trace correlation
works without any application-side patching. The previous
`_patch_trace_agent_id()` monkey-patch \u2014 used in the initial preview to fix
gaps in `azure-ai-agentserver-agentframework` v1.0.0b17 — has been removed
from each agent's `main.py`.

If you observe missing `gen_ai.agent.id` on a span, verify:

1. The `id=` and `name=` arguments on `Agent(...)` match the registered
   agent name (e.g. `clinical-reviewer-agent`).
2. The container is being reached through its **dedicated** endpoint
   (`{project_endpoint}/agents/{name}/endpoint/...`) rather than a shared
   project endpoint with `agent_reference` (legacy initial-preview pattern).

### Content Recording (Sensitive Data)

By default, `enable_sensitive_data` is **off** in every environment. Each
agent's `main.py` reads the `ENABLE_OTEL_SENSITIVE_DATA` env var and passes it
through to `enable_instrumentation(enable_sensitive_data=...)`. When `false`
(the default), spans contain only metadata: model name, token counts, latency,
status, error type, MCP tool name + duration. Prompts, completions, and
tool-call arguments are NOT attached to spans.

> **⚠️ PHI safety control — leave OFF in any shared, staging, or production
> environment.** When `ENABLE_OTEL_SENSITIVE_DATA=true`, full LLM prompts,
> completions, and tool-call arguments are attached to `gen_ai.*` spans and
> shipped to Application Insights — meaning patient identifiers, ICD-10 codes,
> clinical notes, and policy details would land in App Insights as plaintext.
> The env var is intentionally NOT set in any `agent.yaml` and NOT exposed
> as a Bicep parameter, so it cannot be enabled in Azure without a code change
> + redeploy. For ad-hoc PA content inspection, use the Foundry portal's
> built-in Tracing tab (RBAC-gated to project members) instead.

For local debugging only:

```bash
export ENABLE_OTEL_SENSITIVE_DATA=true
docker compose up
```

### Application Map

The backend sets `OTEL_SERVICE_NAME=prior-auth-backend`; the four agent
containers all share the host-provided service name `azure.ai.agentserver`
but are distinguished by the `gen_ai.agent.name` span attribute (sourced
from `FOUNDRY_AGENT_NAME`). Application Insights renders this topology:

```
prior-auth-backend
  └──► azure.ai.agentserver  (4 nodes when grouped by gen_ai.agent.name:
                                clinical-reviewer-agent,
                                compliance-agent,
                                coverage-assessment-agent,
                                synthesis-agent)
```

Edges are drawn from the backend's auto-instrumented outgoing httpx dependency
spans. W3C trace context headers propagate across process boundaries so App
Insights stitches the end-to-end call graph automatically — no manual
correlation ID wiring is needed.

If you want each agent to appear as a separate Application Map node, group or
filter the dependency view by `gen_ai.agent.name` (KQL: `dependencies | summarize
by tostring(customDimensions['gen_ai.agent.name'])`). The previous per-agent
`OTEL_SERVICE_NAME` override is no longer used — the refreshed host hard-codes
`azure.ai.agentserver` as the service name and that value cannot be changed via
environment variable.

### Trace Hierarchy (backend layer)

```
prior_auth_review (request_id)
  ├── phase_1_parallel
  │     ├── compliance_agent_dispatch
  │     └── clinical_agent_dispatch
  ├── phase_2_coverage
  │     └── coverage_agent_dispatch
  ├── phase_3_synthesis
  │     └── synthesis_agent_dispatch
  └── phase_4_audit
```

### MAF Spans (agent layer — all four containers)

| Span | Emitted by | Key attributes |
|------|-----------|----------------|
| `invoke_agent` | MAF | agent name, status |
| `chat` | MAF | model deployment, turn index |
| `execute_tool` | MAF | tool name, tool result status |

These spans are children of the backend `*_agent_dispatch` dependency spans,
creating an end-to-end trace from HTTP request → backend orchestration → agent
tool calls.

### Custom Backend Span Attributes

| Span | Key attributes |
|------|---------------|
| `prior_auth_review` | `request_id` |
| `phase_1_parallel` | `compliance_status`, `clinical_status` |
| `phase_2_coverage` | `coverage_status` |
| `phase_3_synthesis` | `recommendation`, `confidence` |
| `phase_4_audit` | `confidence`, `confidence_level` |

### Enabling Observability

Set the same connection string in all five containers (Bicep injects this
automatically from the shared `monitoring` module output):

```env
APPLICATION_INSIGHTS_CONNECTION_STRING=InstrumentationKey=<key>;IngestionEndpoint=...
```

**Important: env var naming.** The repo uses two forms of the same connection
string at different layers:

| Surface | Env var name | Reason |
|---------|-------------|--------|
| `azd env`, repo `.env`, `azure.yaml` postprovision, **backend container** (`backend/app/config.py`) | `APPLICATION_INSIGHTS_CONNECTION_STRING` | Repo legacy convention; `azure-monitor-opentelemetry` is invoked explicitly with this value via `configure_azure_monitor(connection_string=...)`. |
| **Agent containers** (Foundry + docker-compose), Azure Monitor SDK, Azure App Service | `APPLICATIONINSIGHTS_CONNECTION_STRING` | Canonical Azure Monitor / App Service name. Read by `azure-monitor-opentelemetry` and by the platform-side telemetry pipeline. |

Each agent's `agent.yaml` declares the canonical name via
`OTEL_CONNECTION_STRING` (a non-reserved alias of
`APPLICATIONINSIGHTS_CONNECTION_STRING`). For local docker-compose where the
root `.env` may still use the legacy underscore name, each agent's `main.py`
bridges it by calling
`os.environ.setdefault("APPLICATIONINSIGHTS_CONNECTION_STRING", ...)` and
then calls `enable_instrumentation()` to activate MAF telemetry. Without the
canonical name, the bridge is a no-op, `enable_instrumentation()` is skipped,
and the Foundry portal shows empty Trace ID / Duration / Tokens.

---

## Hosted Agent Dispatch Settings

`hosted_agents.py` automatically selects the dispatch mode based on environment:

- **URL set** (`HOSTED_AGENT_*_URL`): direct HTTP to the container — Docker Compose mode
- **URL empty + `AZURE_AI_PROJECT_ENDPOINT` set**: per-agent dedicated Foundry endpoint via `AIProjectClient(allow_preview=True).get_openai_client(agent_name=...)` — production mode

**Docker Compose mode** — `HOSTED_AGENT_*_URL` vars (defaults already in `docker-compose.yml`):

| Agent | Variable | Default |
|-------|----------|---------| 
| Clinical | `HOSTED_AGENT_CLINICAL_URL` | `http://agent-clinical:8088` |
| Compliance | `HOSTED_AGENT_COMPLIANCE_URL` | `http://agent-compliance:8088` |
| Coverage | `HOSTED_AGENT_COVERAGE_URL` | `http://agent-coverage:8088` |
| Synthesis | `HOSTED_AGENT_SYNTHESIS_URL` | `http://agent-synthesis:8088` |

Shared: `HOSTED_AGENT_TIMEOUT_SECONDS` (default `180`).

**Foundry Hosted Agents mode** — injected automatically by Bicep via `azd up`:

| Variable | Value |
|----------|-------|
| `AZURE_AI_PROJECT_ENDPOINT` | `https://<account>.services.ai.azure.com/api/projects/<project>` |
| `HOSTED_AGENT_CLINICAL_NAME` | `clinical-reviewer-agent` |
| `HOSTED_AGENT_COMPLIANCE_NAME` | `compliance-agent` |
| `HOSTED_AGENT_COVERAGE_NAME` | `coverage-assessment-agent` |
| `HOSTED_AGENT_SYNTHESIS_NAME` | `synthesis-agent` |

Token acquisition uses `azure.identity.aio.DefaultAzureCredential` — no manual token configuration needed.

The following RBAC roles are automatically assigned during `azd up`:

> **Role naming:** Azure renamed two built-in roles — `Azure AI User` is now
> **`Foundry User`** (`53ca6127-db72-4b80-b1b0-d745d6d5456d`) and
> `Azure AI Project Manager` is now **`Foundry Project Manager`**
> (`eadc314b-1a2d-4efa-be10-5d325db5065e`). Both the Bicep module and the
> postprovision hook reference these roles by **role definition ID**, so the
> deployment works regardless of which display name your tenant shows.

| **Role** | **Principal** | **Scope** | **How Assigned** | **Purpose** |
|----------|---------------|-----------|------------------|-------------|
| Cognitive Services OpenAI User | Backend Container App managed identity | Foundry account | `role-assignments.bicep` (provision) | Orchestrator calls each agent's dedicated Foundry endpoint via `get_openai_client(agent_name=...)` |
| AcrPull | Backend Container App managed identity | Container Registry | `role-assignments.bicep` (provision) | Container Apps pulls the backend image from ACR via system-assigned MI (no admin user / passwords) |
| AcrPull | Frontend Container App managed identity | Container Registry | `role-assignments.bicep` (provision) | Container Apps pulls the frontend image from ACR via system-assigned MI |
| AcrPull | Foundry project managed identity | Container Registry | `role-assignments.bicep` (provision) | Foundry Agent Service pulls agent container images from ACR |
| Cognitive Services OpenAI Contributor | Foundry project managed identity | Foundry account | `role-assignments.bicep` (provision) | Hosted agent containers call gpt-5.4 via the Responses API |
| Foundry User (formerly Azure AI User) | Foundry project managed identity | Foundry account | `role-assignments.bicep` (provision) | Hosted agent containers use Foundry Agent Service data actions |
| Foundry User (formerly Azure AI User) | Deployer (user running `azd up`) | Foundry project | `az role assignment create` (postprovision hook) | The `azd ai agent` extension invokes the Foundry Agent Service API on behalf of the deployer |
| **Foundry Project Manager (formerly Azure AI Project Manager)** | **Deployer (user running `azd up`)** | **Foundry project** | **`az role assignment create` (postprovision hook)** | **Required by the refreshed Hosted Agents preview to call `create_version()` on `HostedAgentDefinition` / `PromptAgentDefinition` — `Foundry User` only covers invoking an existing agent. See the [official permissions reference](https://learn.microsoft.com/azure/foundry/agents/how-to/deploy-hosted-agent#required-permissions).** |
| Foundry User (formerly Azure AI User) | Backend Container App managed identity | Foundry project | `az role assignment create` (postprovision hook) | Backend calls Foundry Hosted Agents at runtime via `DefaultAzureCredential` |
| Foundry User (formerly Azure AI User) | Per-agent Entra identity (`agent.instance_identity.principal_id`) | Foundry account | `scripts/grant_agent_rbac.py` (postdeploy hook) | Each refreshed-preview hosted agent uses its own dedicated Entra identity to call the Responses API; the `azd ai agent` extension provisions the identity but does not grant data-plane RBAC |

The first six roles are assigned by `infra/modules/role-assignments.bicep` during `azd provision`. The remaining roles — including the deployer's **Foundry Project Manager** grant — are assigned via `az role assignment create` in the postprovision hook. This is intentionally outside Bicep because the CLI command is natively idempotent (no error if the role was previously granted manually).

> **First-run note:** Azure RBAC propagation can take up to ~60 seconds after a new role assignment. The `postdeploy` hook (`scripts/grant_agent_rbac.py`) prints a NOTE if it just created any new role assignments — if the very first agent invocation after `azd up` returns `PermissionDenied`, wait one minute and retry. On subsequent deploys the roles already exist and no waiting is needed.

---

## Agent Registration

Agent registration is performed by `azd deploy` itself via the
`azd ai agent` extension. Each agent has an entry under the `services:`
block in `azure.yaml` with `host: azure.ai.agent` and a matching
`agents/<name>/agent.yaml` that declares the agent's canonical metadata
(name, protocols, cpu/memory, environment variables). On `azd deploy` the
extension:

1. ACR-builds the agent image from `agents/<name>/Dockerfile` (no local
   Docker daemon required — same flow as `az acr build`).
2. Pushes the image to the ACR connection on the Foundry project.
3. Calls `client.agents.create_version()` with the new image, requested
   cpu/memory, and the `responses 2.0.0` protocol binding.
4. Provisions the per-agent `instance_identity` and `blueprint` Application
   identities and grants `AcrPull` on the registry.
5. Polls until `status == active` (typically 2–5 minutes per agent).

A `postdeploy` hook (`scripts/grant_agent_rbac.py`) then grants `Foundry
User` on the Foundry account scope to each agent's `instance_identity`
— this is the data-plane role required to serve the Responses API and is
not granted by the extension automatically (the gap that produced the
early preview's persistent `424 session_not_ready` and `PermissionDenied`
errors).

### azd environment variables consumed by the extension

The extension resolves the target project from the **azd environment** (not
from the container environment), and it looks up one exact name:

| Variable | Set by | Purpose |
|----------|--------|---------|
| `FOUNDRY_PROJECT_ENDPOINT` | `infra/main.bicep` output + `azd env set` in the postprovision hook | The only name the `azd ai agent` extension reads when resolving the project for `create_version()`. Missing → `ERROR: FOUNDRY_PROJECT_ENDPOINT is required` at the Publishing step. |
| `AZURE_TENANT_ID` | `azd env set` in the postprovision hook | Lets the extension's own postdeploy hook build Foundry playground links without prompting. |

`AI_FOUNDRY_PROJECT_ENDPOINT` and `AZURE_AI_PROJECT_ENDPOINT` hold the same
value but are consumed by this repo's hooks, the backend container, and the
`agents/*/agent.yaml` files — the extension does not read either alias. The
value is written from two places on purpose: the Bicep output covers normal
provisioning, and the postprovision `azd env set` covers the case where azd
skips provisioning because the infrastructure is unchanged.

### Container runtime constraints

Two constraints are imposed by the hosting runtime rather than by this repo:

- **Agent containers run as root.** Foundry injects `HOME=/home/session` and
  mounts the per-session state volume there as root. `ResponsesHostServer`
  creates `$HOME/.sessions` during `__init__`, so a non-root `USER` gets
  `EACCES` and the process exits before `/readiness` binds — reported to callers
  as HTTP `424 session_not_ready`. Creating and `chown`-ing the directory in the
  image does not help; the runtime mount replaces it. The backend and frontend
  images are unaffected and still drop to a non-root user.
- **Responses protocol 2.0.0 is mandatory.** `agent-framework-foundry-hosting`
  `1.0.0b260730`+ rejects protocol 1.0.0 at request time with
  `RuntimeError: The hosted environment is running on protocol 1.0.0, but the
  agent requires protocol 2.0.0`. Every `agents/*/agent.yaml` declares
  `version: "2.0.0"`.

Resource specs are declared per agent in `agents/<name>/agent.yaml`:

| Agent | CPU | Memory |
|-------|-----|--------|
| `clinical-reviewer-agent` | `1` | `2Gi` |
| `coverage-assessment-agent` | `1` | `2Gi` |
| `compliance-agent` | `0.5` | `1Gi` |
| `synthesis-agent` | `1` | `2Gi` |

---

## Agent IDs (Foundry)

| Agent ID | Module |
|----------|--------|
| `compliance-agent` | `agents/compliance/main.py` |
| `clinical-reviewer-agent` | `agents/clinical/main.py` |
| `coverage-assessment-agent` | `agents/coverage/main.py` |
| `synthesis-agent` | `agents/synthesis/main.py` |
