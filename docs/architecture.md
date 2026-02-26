# Architecture

## Multi-Agent Architecture

```
┌──────────────────────────────────────────────────────────────┐
│               Next.js Frontend (shadcn/ui)                   │
│  UploadForm → POST /api/review/stream → ProgressTracker      │
│  [Load Sample Case]    (SSE)             ├── Phase timeline  │
│                                          ├── Agent cards     │
│                                          └── Elapsed timer   │
│                                                              │
│  ReviewDashboard (after review completes)                    │
│  ├── Summary + Confidence                                    │
│  ├── Documentation Gaps                                      │
│  ├── Audit Trail                                             │
│  ├── Agent Details (tabbed)                                  │
│  ├── DecisionPanel                                           │
│  │    ├── Accept / Override                                  │
│  │    ├── POST /api/decision                                 │
│  │    └── Letter Preview + PDF Download (.pdf)               │
│  └── Audit Justification Download (.pdf)                      │
└──────────────────────┬───────────────────────────────────────┘
                       │  REST (JSON) + SSE (text/event-stream)
┌──────────────────────▼───────────────────────────────────────┐
│                   FastAPI Backend                             │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │              Orchestrator (orchestrator.py)             │  │
│  │                                                        │  │
│  │  Pre-flight ─ CPT/HCPCS FORMAT VALIDATION              │  │
│  │  (cpt_validation.py — regex + curated lookup table)    │  │
│  │                                                        │  │
│  │  Phase 1 ─ PARALLEL (asyncio.gather)                   │  │
│  │  ┌─────────────────────┐  ┌──────────────────────────┐ │  │
│  │  │  Compliance Agent   │  │  Clinical Reviewer Agent │ │  │
│  │  │  (no tools)         │  │  MCP: icd10-codes,       │ │  │
│  │  │                     │  │       pubmed,            │ │  │
│  │  │  Validates docs,    │  │       clinical-trials    │ │  │
│  │  │  checklists,        │  │                          │ │  │
│  │  │  completeness       │  │  Validates ICD-10 codes, │ │  │
│  │  │                     │  │  extracts clinical data, │ │  │
│  │  │                     │  │  confidence scoring,     │ │  │
│  │  │                     │  │  clinical trials search  │ │  │
│  │  └─────────────────────┘  └────────────┬─────────────┘ │  │
│  │                                        │               │  │
│  │  Phase 2 ─ SEQUENTIAL (needs clinical findings)        │  │
│  │  ┌─────────────────────────────────────┐               │  │
│  │  │  Coverage Agent                     │               │  │
│  │  │  MCP: npi-registry, cms-coverage    │               │  │
│  │  │                                     │               │  │
│  │  │  Verifies provider, searches        │               │  │
│  │  │  coverage policies, maps evidence   │               │  │
│  │  │  to criteria (MET/NOT_MET/          │               │  │
│  │  │  INSUFFICIENT + confidence),        │               │  │
│  │  │  Diagnosis-Policy Alignment check   │               │  │
│  │  └─────────────────────────────────────┘               │  │
│  │                                                        │  │
│  │  Phase 3 ─ SYNTHESIS (gate-based decision rubric)      │  │
│  │  Gate 1: Provider → Gate 2: Codes → Gate 3: Necessity  │  │
│  │  → APPROVE or PEND + confidence level + rationale      │  │
│  │                                                        │  │
│  │  Phase 4 ─ AUDIT TRAIL & JUSTIFICATION                 │  │
│  │  Computes confidence, builds audit trail, generates     │  │
│  │  audit justification document (Markdown + PDF)          │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  Decision & Notification (decision.py + notification.py)│  │
│  │  POST /api/decision — Accept or Override recommendation │  │
│  │  Generates auth number (PA-YYYYMMDD-XXXXX)              │  │
│  │  Produces approval/pend notification letters (text + PDF)  │  │
│  │  Override rationale flows to letters + audit PDF         │  │
│  │  In-memory review store for persistence                 │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  Microsoft AI Foundry (Claude model endpoint + API key)      │
└──────────────────────┬───────────────────────────────────────┘
                       │  Streamable HTTP (MCP protocol)
                       │  Header: User-Agent: claude-code/1.0
┌──────────────────────▼───────────────────────────────────────┐
│           Remote Healthcare MCP Servers                       │
│     (from https://github.com/anthropics/healthcare)           │
│                                                               │
│  ┌────────────────┐  ┌──────────────────┐  ┌──────────────┐  │
│  │ NPI Registry   │  │ ICD-10 Codes     │  │ CMS Coverage │  │
│  │ (DeepSense)    │  │ (DeepSense)      │  │ (DeepSense)  │  │
│  └────────────────┘  └──────────────────┘  └──────────────┘  │
│  ┌──────────────────┐  ┌──────────────────┐                   │
│  │ Clinical Trials  │  │ PubMed           │                   │
│  │ (DeepSense)      │  │ (Anthropic)      │                   │
│  └──────────────────┘  └──────────────────┘                   │
└───────────────────────────────────────────────────────────────┘
```

## How It Works

![Prior Authorization Review — Application Interface](./images/readme/interface.png)
*The Prior Authorization Review interface showing the PA request form, real-time agent progress tracking, review dashboard with agent details, and the human-in-the-loop decision panel.*

1. A clinical reviewer fills in the PA request form in the Next.js frontend,
   or clicks **"Load Sample Case"** to populate a demo case (CT-guided
   lung biopsy: ICD-10 R91.1/J18.9/R05.9, CPT 31628, NPI 1720180003).

2. The frontend POSTs to `POST /api/review/stream` on the FastAPI backend,
   opening an SSE (Server-Sent Events) connection for real-time progress.

3. The **Orchestrator** runs a pre-flight check and then launches three
   specialized Claude agents:

   **Pre-flight — CPT/HCPCS Format Validation** (`cpt_validation.py`):
   - Validates procedure code format (5-digit CPT or letter+4 HCPCS)
   - Looks up codes against a curated table of ~30 common PA-trigger codes
   - Invalid format codes are flagged before any agent runs
   - Results are injected into the synthesis prompt for Gate 2 evaluation

   **Phase 1 — Parallel execution** (`asyncio.gather`):
   - **Compliance Agent** (no tools, `max_turns=5`) — validates documentation completeness
   - **Clinical Reviewer Agent** (ICD-10 + PubMed + Clinical Trials MCP, `max_turns=15`) — validates diagnosis codes, extracts clinical data with confidence scoring, searches literature

   **Phase 2 — Sequential** (depends on clinical findings):
   - **Coverage Agent** (NPI + CMS MCP, `max_turns=15`) — verifies provider, searches coverage policies, maps evidence to criteria

   **Phase 3 — Synthesis** (gate-based decision rubric):
   - Gate 1 (Provider) → Gate 2 (Codes) → Gate 3 (Medical Necessity)
   - Produces APPROVE or PEND recommendation with confidence score

   **Phase 4 — Audit trail and justification**:
   - Computes overall confidence, builds audit trail, generates audit justification document (Markdown + PDF)

4. Response persisted in review store for later retrieval.

5. Frontend displays real-time progress tracker with phase timeline and agent cards.

6. Review dashboard shows recommendation, agent details (tabbed), and audit justification download.

7. Decision Panel supports Accept or Override flow with notification letter generation.

---

## MCP Integration — No Custom Client Needed

A key architectural finding: the **Microsoft Agent Framework's Claude SDK**
natively supports custom HTTP headers on MCP server connections via the
`McpHttpServerConfig` TypedDict's `headers` field.

### The User-Agent Requirement

The DeepSense-hosted MCP servers use CloudFront routing that requires `User-Agent: claude-code/1.0`.

### How Headers Are Injected

MCP server configs are defined in `mcp_config.py` with the required header:

```python
# backend/app/tools/mcp_config.py

_HEADERS = {"User-Agent": "claude-code/1.0"}

NPI_SERVER = {"type": "http", "url": settings.MCP_NPI_REGISTRY, "headers": _HEADERS}
ICD10_SERVER = {"type": "http", "url": settings.MCP_ICD10_CODES, "headers": _HEADERS}
CMS_SERVER = {"type": "http", "url": settings.MCP_CMS_COVERAGE, "headers": _HEADERS}
PUBMED_SERVER = {"type": "http", "url": settings.MCP_PUBMED, "headers": _HEADERS}
TRIALS_SERVER = {"type": "http", "url": settings.MCP_CLINICAL_TRIALS, "headers": _HEADERS}
```

These configs are passed to `ClaudeAgent` via `default_options.mcp_servers`:

```python
# backend/app/agents/clinical_agent.py

agent = ClaudeAgent(
    instructions=CLINICAL_INSTRUCTIONS,
    default_options={
        "mcp_servers": CLINICAL_MCP_SERVERS,
        "permission_mode": "bypassPermissions",
    },
)
```

### MCP Is Model-Agnostic

MCP servers work with any LLM client, not just Claude. The MS Agent Framework provides
`MCPStreamableHTTPTool` for custom headers:

```python
import httpx
from agent_framework import MCPStreamableHTTPTool

http_client = httpx.AsyncClient(headers={"User-Agent": "claude-code/1.0"})
mcp_tool = MCPStreamableHTTPTool(name="npi", url=NPI_URL, http_client=http_client)
```

### Approaches Tested for MCP Header Injection

| Approach | Works? | Notes |
|---|---|---|
| `McpHttpServerConfig.headers` in `ClaudeAgentOptions.mcp_servers` | Yes | Cleanest — zero custom code, used in production |
| `MCPStreamableHTTPTool` + `httpx.AsyncClient` | Yes | Model-agnostic, good for non-Claude agents |
| Azure OpenAI Responses API `type: "mcp"` with `headers` | No | Azure proxy doesn't forward `User-Agent` |
| Custom `MCPClient` with `mcp` Python SDK | Yes | Works but unnecessary — replaced by above |

---

## Agent Details

Each agent's execution is fully transparent in the frontend with Checks Summary tables.

### Compliance Agent

| Property | Value |
|----------|-------|
| **Role** | Documentation completeness validation |
| **Tools** | None (pure reasoning) |
| **`max_turns`** | 5 |
| **Input** | Raw PA request data |
| **Output** | Checklist (8 items), missing items, additional-info requests |

**SKILL.md rules (always shown in Checks Summary):**

| # | Rule | What it checks |
|---|------|----------------|
| 1 | Patient Information | Name and DOB present and non-empty |
| 2 | Provider NPI | NPI present and exactly 10 digits |
| 3 | Insurance ID (non-blocking) | Insurance ID provided (informational only) |
| 4 | Diagnosis Codes | At least one ICD-10 code with valid format |
| 5 | Procedure Codes | At least one CPT/HCPCS code provided |
| 6 | Clinical Notes Presence | Substantive clinical narrative (not just codes) |
| 7 | Clinical Notes Quality | Meaningful detail; boilerplate/copy-paste detection |
| 8 | Insurance Plan Type (non-blocking) | Medicare/Medicaid/Commercial/MA identification |

### Clinical Reviewer Agent

| Property | Value |
|----------|-------|
| **Role** | Clinical data extraction, code validation, confidence scoring, clinical trials search |
| **MCP Servers** | `icd10-codes`, `pubmed`, `clinical-trials` |
| **Tools** | `validate_code`, `lookup_code`, `search_codes`, `get_hierarchy`, `get_by_category`, `get_by_body_system`, `search` (PubMed), `search_trials`, `get_trial_details`, `search_by_eligibility`, `search_investigators`, `analyze_endpoints`, `search_by_sponsor` |
| **`max_turns`** | 15 |

**SKILL.md rules:**

| # | Rule | MCP tools used | Sub-items |
|---|------|---------------|-----------|
| 1 | ICD-10 Diagnosis Code Validation | `validate_code`, `lookup_code`, `get_hierarchy` | Per-code sub-items |
| 2 | CPT/HCPCS Procedure Code Notation | (orchestrator pre-flight) | Pre-flight results |
| 3 | Clinical Data Extraction | None (reasoning) | 8 sub-items |
| 4 | Extraction Confidence Calculation | None (reasoning) | Low-confidence warning if < 60% |
| 5 | PubMed Literature Search | `search` (PubMed MCP) | Supplementary, non-blocking |
| 6 | Clinical Trials Search | `search_trials`, `search_by_eligibility` | Supplementary, non-blocking |
| 7 | Clinical Summary Generation | None (reasoning) | Final structured narrative |

### Coverage Agent

| Property | Value |
|----------|-------|
| **Role** | Provider verification, coverage policy assessment, criteria mapping, diagnosis-policy alignment |
| **MCP Servers** | `npi-registry`, `cms-coverage` |
| **Tools** | `npi_validate`, `npi_lookup`, `npi_search`, `search_national_coverage`, `search_local_coverage`, `get_coverage_document`, `get_contractors`, `get_whats_new_report`, `batch_get_ncds`, `sad_exclusion_list` |
| **`max_turns`** | 15 |

**SKILL.md rules:**

| # | Rule | MCP tools used | Sub-items |
|---|------|---------------|-----------|
| 1 | Provider NPI Verification | `npi_validate`, `npi_lookup` | Format check + NPPES lookup |
| 2 | MAC Identification | `get_contractors` | State-based MAC lookup |
| 3 | Coverage Policy Search | `search_national_coverage`, `search_local_coverage` | NCD and LCD searches |
| 4 | Policy Detail Retrieval | `get_coverage_document`, `batch_get_ncds` | Full policy text |
| 5 | Clinical Evidence to Criteria Mapping | None (reasoning) | Per-criterion MET/NOT_MET/INSUFFICIENT |
| 6 | Diagnosis-Policy Alignment (AUDITABLE) | None (reasoning) | ICD-10 vs. policy indications |
| 7 | Documentation Gap Analysis | None (reasoning) | Critical vs. non-critical |

**Criteria evaluation:**
- **MET** (confidence >= 70): Clinical evidence clearly supports the requirement
- **NOT_MET** (any confidence): Evidence contradicts the requirement
- **INSUFFICIENT** (confidence < 70): Evidence absent or ambiguous

### Orchestrator (Synthesis)

| Property | Value |
|----------|-------|
| **Role** | Pre-flight CPT validation, coordinate agents, apply gate-based decision rubric |
| **Tools** | CPT format validation (local), no MCP tools |
| **`max_turns`** | 5 (synthesis agent) |
| **Input** | All three agent reports + CPT validation results |
| **Output** | APPROVE/PEND recommendation, confidence (0-1.0 + HIGH/MEDIUM/LOW), rationale, audit trail |

---

## Decision Rubric — LENIENT Mode (Default)

Evaluated in gate order. Stops at first failing gate:

**Gate 1 — Provider Verification:**

| Scenario | Action |
|----------|--------|
| Provider NPI valid and active | PASS — continue to Gate 2 |
| Provider NPI invalid or inactive | PEND — request credentialing info |

**Gate 2 — Code Validation:**

| Scenario | Action |
|----------|--------|
| All ICD-10 codes valid and billable | PASS — continue to Gate 3 |
| Any ICD-10 code invalid | PEND — request diagnosis code clarification |
| All CPT/HCPCS codes valid format | PASS — continue to Gate 3 |
| Any CPT/HCPCS code invalid format | PEND — request procedure code clarification |

**Gate 3 — Medical Necessity:**

| Scenario | Action |
|----------|--------|
| All required criteria MET | APPROVE |
| Any criterion NOT_MET | PEND — request additional documentation |
| Any criterion INSUFFICIENT | PEND — specify what documentation is needed |
| No coverage policy found | PEND — manual policy review needed |
| Documentation incomplete | PEND — specify missing items |
| Uncertain or conflicting signals | PEND — default safe option |

The system **never recommends DENY** — only APPROVE or PEND FOR REVIEW.

---

## Confidence Scoring

| Level | Range | Meaning |
|-------|-------|---------|
| **HIGH** | 0.80 - 1.0 | All criteria MET with high confidence, no gaps |
| **MEDIUM** | 0.50 - 0.79 | Most criteria MET but some with moderate evidence |
| **LOW** | 0.0 - 0.49 | Significant gaps, INSUFFICIENT criteria, or agent errors |

Computed from: per-criterion confidence (Coverage Agent), extraction confidence
(Clinical Agent), compliance completeness, and agent error penalties.

---

## Audit Justification Document

The orchestrator generates a structured audit document (Markdown + PDF) with 8 sections:

1. **Executive Summary** — patient, provider, decision, confidence
2. **Medical Necessity Assessment** — provider info, coverage policies, clinical evidence, Literature Support, Clinical Trials
3. **Criterion-by-Criterion Evaluation** — each criterion with status, confidence, evidence
4. **Validation Checks** — provider NPI, diagnosis codes, compliance checklist
5. **Decision Rationale** — decision gates with color-coded PASS/FAIL labels, confidence, supporting facts
6. **Documentation Gaps** — structured gaps, critical/non-critical labels
7. **Audit Trail** — data sources, timestamps, confidence metrics
8. **Regulatory Compliance** — decision policy and requirements

---

## Anthropic Healthcare MCP Servers

This project consumes **remote MCP servers** from the
[anthropics/healthcare](https://github.com/anthropics/healthcare) marketplace.

| MCP Server | Endpoint | Used By | Key Tools |
|---|---|---|---|
| **NPI Registry** | `mcp.deepsense.ai/npi_registry/mcp` | Coverage Agent | `npi_validate`, `npi_lookup`, `npi_search` |
| **ICD-10 Codes** | `mcp.deepsense.ai/icd10_codes/mcp` | Clinical Agent | `validate_code`, `lookup_code`, `search_codes`, `get_hierarchy`, `get_by_category`, `get_by_body_system` |
| **CMS Coverage** | `mcp.deepsense.ai/cms_coverage/mcp` | Coverage Agent | `search_national_coverage`, `search_local_coverage`, `get_coverage_document`, `get_contractors`, `get_whats_new_report`, `batch_get_ncds`, `sad_exclusion_list` |
| **Clinical Trials** | `mcp.deepsense.ai/clinical_trials/mcp` | Clinical Agent | `search_trials`, `get_trial_details`, `search_by_eligibility`, `search_investigators`, `analyze_endpoints`, `search_by_sponsor` |
| **PubMed** | `pubmed.mcp.claude.com/mcp` | Clinical Agent | `search` |

### How MCP Is Integrated

```
mcp_config.py     — Server URL + headers config (User-Agent: claude-code/1.0)
    ↓ passed via
ClaudeAgentOptions.mcp_servers   — Each agent gets its relevant MCP servers
    ↓ handled by
Claude Agent SDK  — Auto-discovers tools, manages sessions, invokes tools
```

---

## Skills-Based Architecture

The application supports two modes, controlled by the `USE_SKILLS` environment variable:

| Mode | `USE_SKILLS` | How agents are configured |
|------|-------------|--------------------------|
| **Skills-based** (default) | `true` | SKILL.md files via MAF native skill discovery |
| **Prompt-based** (fallback) | `false` | Inline system prompt instructions |

### Skills Overview

| Skill | Directory | MCP Servers | Purpose |
|-------|-----------|-------------|---------|
| Compliance Review | `.claude/skills/compliance-review/` | None | 8-item documentation completeness checklist |
| Clinical Review | `.claude/skills/clinical-review/` | icd10-codes, pubmed, clinical-trials | Code validation, clinical extraction, literature + trials |
| Coverage Assessment | `.claude/skills/coverage-assessment/` | npi-registry, cms-coverage | Provider verification, policy search, criteria mapping |
| Synthesis Decision | `.claude/skills/synthesis-decision/` | None | Gate-based evaluation, weighted confidence, final recommendation |

### Three-Way Comparison

| Aspect | Skills-based (default) | Prompt-based (fallback) | Anthropic skill |
|--------|----------------------|------------------------|-----------------|
| Agent configuration | SKILL.md files via MAF discovery | Inline system instructions | SKILL.md via Claude Code Skills API |
| Token efficiency | Progressive disclosure | Full prompt (~1,200-1,500 tokens per agent) | Progressive disclosure per subskill |
| Parallelism | Multi-agent, concurrent | Multi-agent, concurrent | Single agent, sequential |
| Platform | Microsoft AI Foundry via MAF | Microsoft AI Foundry via MAF | Claude Code with Skills API |
| Confidence formula | Explicit weighted (4 components) | Explicit weighted (4 components) | Subjective assessment |
