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
              └─── [Foundry Hosted Agents — production (azd up)] ──────────────────
                   POST {AZURE_AI_PROJECT_ENDPOINT}/responses
                   with  agent_reference: {name, type: "agent_framework"}
                         Authorization: Bearer <DefaultAzureCredential>
                   → Foundry Agent Service → registered agent containers
```

Each agent container runs **Microsoft Agent Framework (MAF)** via
`azure.ai.agentserver.agentframework.from_agent_framework`, exposes an HTTP
endpoint, and is registered with **Microsoft Foundry** as a Hosted Agent via
`scripts/register_agents.py`.

---

## MCP Header Injection

The DeepSense-hosted MCP servers require `User-Agent: claude-code/1.0` due
to CloudFront routing rules. This is injected in each agent container via a
single shared `httpx.AsyncClient`:

```python
_MCP_HTTP_CLIENT = httpx.AsyncClient(headers={"User-Agent": "claude-code/1.0"})

icd10_tool = MCPStreamableHTTPTool(
    name="icd10-codes",
    url=os.environ["MCP_ICD10_CODES"],
    http_client=_MCP_HTTP_CLIENT,
)
```

The MCP servers are **self-hosted** — no Foundry Tool MCP registration needed.
The containers connect directly to the MCP server URLs via environment variables.

---

## Agent Skills

Each agent loads its SKILL.md via `FileAgentSkillsProvider`:

```python
skills_provider = FileAgentSkillsProvider(
    skill_paths=str(Path(__file__).parent / "skills")
)
```

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
passes it via MAF's `default_options` parameter:

```python
agent = (
    AzureOpenAIResponsesClient(...)
    .as_agent(
        tools=[...],
        default_options={"response_format": ClinicalResult},
    )
)
```

MAF enforces the schema as a token-level JSON constraint at inference time —
no post-processing or regex extraction needed. The backend dispatcher reads
the text payload from the Foundry Responses API envelope:

```python
# hosted_agents.py
result_text = data["output"][0]["content"][0]["text"]
return json.loads(result_text)
```

The Pydantic models live in each agent container:

| Agent | Schema file | Root model |
|-------|-------------|------------|
| Clinical | `agents/clinical/schemas.py` | `ClinicalResult` |
| Compliance | `agents/compliance/schemas.py` | `ComplianceResult` |
| Coverage | `agents/coverage/schemas.py` | `CoverageResult` |
| Synthesis | `agents/synthesis/schemas.py` | `SynthesisOutput` (includes `synthesis_audit_trail: dict` with `gate_results` and `confidence_components`) |

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

| Process | `OTEL_SERVICE_NAME` | What it instruments |
|---------|---------------------|---------------------|
| FastAPI backend | `prior-auth-backend` | HTTP requests/responses, outgoing httpx calls to agents, logs, exceptions, live metrics |
| Clinical agent | `agent-clinical` | MAF `invoke_agent`, `chat`, `execute_tool` spans, token metrics |
| Coverage agent | `agent-coverage` | Same as above |
| Compliance agent | `agent-compliance` | Same as above |
| Synthesis agent | `agent-synthesis` | Same as above |

Each process calls `configure_azure_monitor()` before any agents start.
Agent containers additionally call `enable_instrumentation()` to activate
MAF's built-in OTel instrumentation. The backend's `observability.py` does
**not** call `enable_instrumentation()` — that function is MAF-specific and
only valid in agent processes.

### Application Map

Because `OTEL_SERVICE_NAME` is set in every process, App Insights
**Application Map** renders a clean 5-node topology:

```
prior-auth-backend
  ├──► agent-compliance
  ├──► agent-clinical
  ├──► agent-coverage
  └──► agent-synthesis
```

Edges are drawn from the backend's auto-instrumented outgoing httpx dependency
spans. W3C trace context headers propagate across process boundaries so App
Insights stitches the end-to-end call graph automatically — no manual
correlation ID wiring is needed.

`OTEL_SERVICE_NAME` is set via `os.environ.setdefault(...)` so an explicit
env var configured in the Container App (e.g., via Bicep or the ACA portal)
always overrides the in-code default.

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

Locally (docker-compose), the variable is intentionally absent — all
observability blocks are no-ops so the app runs without App Insights.

---

## Hosted Agent Dispatch Settings

`hosted_agents.py` automatically selects the dispatch mode based on environment:

- **URL set** (`HOSTED_AGENT_*_URL`): direct HTTP to the container — Docker Compose mode
- **URL empty + `AZURE_AI_PROJECT_ENDPOINT` set**: Foundry `agent_reference` routing — production mode

**Docker Compose mode** — `HOSTED_AGENT_*_URL` vars (defaults already in `docker-compose.yml`):

| Agent | Variable | Default |
|-------|----------|---------| 
| Clinical | `HOSTED_AGENT_CLINICAL_URL` | `http://agent-clinical:8000` |
| Compliance | `HOSTED_AGENT_COMPLIANCE_URL` | `http://agent-compliance:8000` |
| Coverage | `HOSTED_AGENT_COVERAGE_URL` | `http://agent-coverage:8000` |
| Synthesis | `HOSTED_AGENT_SYNTHESIS_URL` | `http://agent-synthesis:8000` |

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

| **Role** | **Principal** | **Scope** | **How Assigned** | **Purpose** |
|----------|---------------|-----------|------------------|-------------|
| Cognitive Services OpenAI User | Backend Container App managed identity | Foundry account | `role-assignments.bicep` (provision) | Orchestrator calls Foundry Responses API with `agent_reference` routing |
| AcrPull | Foundry project managed identity | Container Registry | `role-assignments.bicep` (provision) | Foundry Agent Service pulls agent container images from ACR |
| Azure AI Developer | Deployer (user running `azd up`) | Foundry account | `az role assignment create` (postprovision hook) | `register_agents.py` registers agents via Foundry Agent Service API |

The first two roles are assigned by `infra/modules/role-assignments.bicep` during `azd provision`. The Azure AI Developer role is assigned via `az role assignment create` in the postprovision hook — this is intentionally outside Bicep because the CLI command is natively idempotent (no error if the role was previously granted manually).

> **First-run note:** Azure RBAC propagation can take up to several minutes after a new role assignment. On the very first `azd up` (when the Azure AI Developer role is newly created), the postprovision hook automatically retries `register_agents.py` every 10 seconds (up to 12 attempts) until the permission propagates. On subsequent runs the role already exists and no retries are needed.

---

## Agent Registration

After `azd provision`, `scripts/register_agents.py` (called from the `azure.yaml` postprovision hook)
registers all four agents with Foundry:

1. Calls `azure-ai-projects` SDK `client.agents.create_version()` with the ACR container image
   and resource specs from `agent.yaml`
2. Calls `az cognitiveservices agent start` to start each agent under Foundry management

Resource specs (defined in each `agents/<name>/agent.yaml`):

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
