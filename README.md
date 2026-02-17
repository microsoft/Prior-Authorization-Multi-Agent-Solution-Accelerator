# Prior Authorization Review — Microsoft Agent Framework + Claude

A **multi-agent** AI-assisted prior authorization (PA) review application built
with the **Microsoft Agent Framework**, **Claude Agent SDK**, and **Anthropic
Healthcare MCP Servers**. Three specialized agents — Compliance, Clinical
Reviewer, and Coverage — work in parallel and sequence, coordinated by an
orchestrator that applies a gate-based decision rubric and produces a final
recommendation with confidence scoring and an audit justification document.
The frontend is built with **Next.js** (static export), **shadcn/ui**, and
**Tailwind CSS** with a Microsoft-inspired design system.
Includes a human-in-the-loop **Decision Panel** for accept/override workflow,
**PDF notification letter generation** (approval and pend via `fpdf2`),
**CPT/HCPCS format validation**, **real-time agent progress streaming** (SSE),
**audit justification PDF download** (color-coded, professional format), and a **sample case** for demo use.

Incorporates best practices from the
[Anthropic prior-auth-review-skill](https://github.com/anthropics/healthcare/tree/main/prior-auth-review-skill):
LENIENT mode decision policy, per-criterion MET/NOT_MET/INSUFFICIENT evaluation,
confidence scoring, progressive gate evaluation, and structured audit trails.

> **Disclaimer:** This is an AI-assisted triage tool. All recommendations are
> drafts that require human clinical review before any authorization decision
> is finalized. Coverage policies reflect Medicare LCDs/NCDs only — commercial
> and Medicare Advantage plans may differ.

---

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
│  │  In-memory review store for persistence                 │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  Azure Foundry (Claude model endpoint + API key)             │
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
│  ┌──────────────────┐  ┌──────────────┐                      │
│  │ Clinical Trials  │  │ PubMed       │                      │
│  │ (DeepSense)      │  │ (Anthropic)  │                      │
│  └──────────────────┘  └──────────────┘                      │
└───────────────────────────────────────────────────────────────┘
```

### How it works

1. A clinical reviewer fills in the PA request form in the Next.js frontend,
   or clicks **"Load Sample Case"** to populate a demo case (CT-guided
   lung biopsy: ICD-10 R91.1/J18.9/R05.9, CPT 31628, NPI 1902809042).

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
   - **Compliance Agent** (no tools) — validates documentation completeness
     against a checklist (patient info, NPI format, ICD-10/CPT presence,
     clinical notes quality). Produces a checklist with pass/fail per item
     and specific additional-info requests.
   - **Clinical Reviewer Agent** (ICD-10 + PubMed + Clinical Trials MCP) — validates
     diagnosis codes via `validate_code` and `lookup_code`, explores code hierarchies
     via `get_hierarchy`, extracts clinical indicators with **confidence scoring**
     (0-100 per field), searches supporting literature via PubMed `search`,
     searches relevant clinical trials via `search_trials` and `search_by_eligibility`,
     and structures a clinical narrative.

   **Phase 2 — Sequential** (depends on clinical findings):
   - **Coverage Agent** (NPI + CMS MCP) — receives the Clinical Reviewer's
     output, verifies provider via `npi_validate`/`npi_lookup`, searches
     coverage policies via `search_national_coverage`/`search_local_coverage`/
     `get_coverage_document`/`batch_get_ncds`, identifies applicable MACs via
     `get_contractors`, and maps clinical evidence to each policy criterion using
     **MET/NOT_MET/INSUFFICIENT** status with per-criterion confidence scores.
     Performs a **Diagnosis-Policy Alignment** check (cross-referencing ICD-10
     codes against policy-covered indications) as a required auditable criterion.
     Identifies documentation gaps with critical/non-critical classification.

   **Phase 3 — Synthesis** (gate-based decision rubric):
   - The Orchestrator evaluates three gates in order:
     Gate 1 (Provider) → Gate 2 (Codes) → Gate 3 (Medical Necessity).
     Stops at the first failing gate. Produces a final APPROVE or PEND
     recommendation with confidence score (0-1.0), confidence level
     (HIGH/MEDIUM/LOW), and detailed rationale.

   **Phase 4 — Audit trail and justification**:
   - Computes overall confidence from agent outputs, builds an audit trail
     (data sources, timestamps, metrics), and generates a structured
     8-section **audit justification document** in both Markdown and
     professionally formatted **PDF** (via `fpdf2`, with color-coded sections,
     status tables, and confidence bars).

4. The response is **persisted** in an in-memory review store (keyed by
   `request_id`) for later retrieval via `GET /api/review/{id}` and
   `GET /api/reviews`. The response includes top-level synthesized fields,
   per-agent breakdowns, audit trail, and documentation gaps for full
   transparency.

5. During the review, the frontend displays a **real-time progress tracker**
   with a vertical phase timeline, per-agent status cards (with icons and
   color-coded badges), a progress bar, and an elapsed timer. Each phase
   boundary streams an SSE `progress` event; the final result arrives as
   an SSE `result` event.

6. Once complete, the frontend displays the recommendation with a confidence
   level badge, documentation gaps with critical/non-critical styling, an
   audit trail section, a **tabbed Agent Details** panel showing each agent's
   structured output (compliance checklist, diagnosis validation table with
   billability, criteria assessment grid with confidence bars, etc.), an
   **Audit Justification Download** button (`.pdf` with the full
   8-section audit document — color-coded sections, criterion evaluation
   tables, and confidence bars), and a **Decision Panel** for human reviewer
   action.

7. The **Decision Panel** supports two flows:
   - **Accept** — the human reviewer confirms the AI recommendation
   - **Override** — the reviewer selects a different recommendation
     (approve or pend) and provides a written rationale

   Either action calls `POST /api/decision`, which generates an
   authorization number (`PA-YYYYMMDD-XXXXX`) and a notification letter
   (approval letter with 90-day validity or pend letter with 30-day
   documentation deadline and appeal rights). Both a plain-text preview and
   a professionally formatted **PDF** (generated via `fpdf2`) are included.
   The PDF can be downloaded directly from the Decision Panel.

---

## MCP Integration — No Custom Client Needed

A key architectural finding: the **Microsoft Agent Framework's Claude SDK**
natively supports custom HTTP headers on MCP server connections via the
`McpHttpServerConfig` TypedDict's `headers` field. This eliminated the need
for a custom MCP client entirely.

### The User-Agent requirement

The DeepSense-hosted MCP servers (NPI Registry, ICD-10 Codes, CMS Coverage)
use CloudFront routing that requires `User-Agent: claude-code/1.0`. Without
this header, requests receive a 301 redirect to documentation pages instead
of the MCP backend.

### How headers are injected

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
        "mcp_servers": CLINICAL_MCP_SERVERS,   # {"icd10-codes": ..., "pubmed": ..., "clinical-trials": ...}
        "permission_mode": "bypassPermissions",
    },
)
```

The Claude SDK handles MCP session lifecycle, tool discovery, and invocation
automatically. No wrapper functions or custom client code needed.

### MCP is model-agnostic

MCP servers are protocol endpoints that return structured data — they work
with any LLM client, not just Claude. The MS Agent Framework also provides
`MCPStreamableHTTPTool` which accepts an `httpx.AsyncClient` for custom
headers, enabling MCP access from any model:

```python
import httpx
from agent_framework import MCPStreamableHTTPTool

http_client = httpx.AsyncClient(headers={"User-Agent": "claude-code/1.0"})
mcp_tool = MCPStreamableHTTPTool(name="npi", url=NPI_URL, http_client=http_client)
```

### Approaches tested for MCP header injection

| Approach | Works? | Notes |
|---|---|---|
| `McpHttpServerConfig.headers` in `ClaudeAgentOptions.mcp_servers` | Yes | Cleanest — zero custom code, used in production |
| `MCPStreamableHTTPTool` + `httpx.AsyncClient` | Yes | Model-agnostic, good for non-Claude agents |
| Azure OpenAI Responses API `type: "mcp"` with `headers` | No | Azure proxy doesn't forward `User-Agent` |
| Custom `MCPClient` with `mcp` Python SDK | Yes | Works but unnecessary — replaced by above |

---

## Agent Details

### Compliance Agent

| Property | Value |
|----------|-------|
| **Role** | Documentation completeness validation |
| **Tools** | None (pure reasoning) |
| **Input** | Raw PA request data |
| **Output** | Checklist (8 items), missing items, additional-info requests |

**Checklist items:** Patient Information, Provider NPI, Insurance ID,
Diagnosis Codes, Procedure Codes, Clinical Notes Presence, Clinical Notes Quality,
Insurance Plan Type.

### Clinical Reviewer Agent

| Property | Value |
|----------|-------|
| **Role** | Clinical data extraction, code validation, confidence scoring, clinical trials search |
| **MCP Servers** | `icd10-codes`, `pubmed`, `clinical-trials` |
| **Tools** | `validate_code`, `lookup_code`, `search_codes`, `get_hierarchy`, `get_by_category`, `get_by_body_system`, `search` (PubMed), `search_trials`, `get_trial_details`, `search_by_eligibility`, `search_investigators`, `analyze_endpoints`, `search_by_sponsor` |
| **Input** | Raw PA request data |
| **Output** | Diagnosis validation, clinical extraction (with `extraction_confidence` 0-100), literature support, clinical trials, clinical summary |

**Confidence scoring:** Each extraction field is scored 0-100 based on how
explicitly the data appears in clinical notes. Overall `extraction_confidence`
is the average. Below 60% triggers a low-confidence warning.

### Coverage Agent

| Property | Value |
|----------|-------|
| **Role** | Provider verification, coverage policy assessment, criteria mapping, diagnosis-policy alignment |
| **MCP Servers** | `npi-registry`, `cms-coverage` |
| **Tools** | `npi_validate`, `npi_lookup`, `npi_search`, `search_national_coverage`, `search_local_coverage`, `get_coverage_document`, `get_contractors`, `get_whats_new_report`, `batch_get_ncds`, `sad_exclusion_list` |
| **Input** | Raw PA request + Clinical Reviewer findings |
| **Output** | Provider verification, coverage policies, criteria assessment (MET/NOT_MET/INSUFFICIENT + confidence), documentation gaps (critical/non-critical), coverage limitations |

**Criteria evaluation:** Each policy criterion is assessed as:
- **MET** (confidence >= 70): Clinical evidence clearly supports the requirement
- **NOT_MET** (any confidence): Evidence contradicts the requirement
- **INSUFFICIENT** (confidence < 70): Evidence absent or ambiguous — additional documentation needed

**Diagnosis-Policy Alignment:** A required auditable criterion that cross-references
submitted ICD-10 codes against the coverage policy's listed indications. Emitted as
a dedicated entry in `criteria_assessment` with MET/NOT_MET/INSUFFICIENT status.

### Orchestrator (Synthesis)

| Property | Value |
|----------|-------|
| **Role** | Pre-flight CPT validation, coordinate agents, apply gate-based decision rubric, produce final recommendation |
| **Tools** | CPT format validation (local, pre-agent), no MCP tools (reasoning only for synthesis) |
| **Input** | All three agent reports + CPT validation results |
| **Output** | APPROVE/PEND recommendation, confidence (0-1.0 + HIGH/MEDIUM/LOW), rationale, audit trail, audit justification document |

### Decision Rubric — LENIENT Mode (Default)

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
| Documentation incomplete (Compliance) | PEND — specify missing items |
| Uncertain or conflicting signals | PEND — default safe option |

The system **never recommends DENY** — only APPROVE or PEND FOR REVIEW.

### Confidence Scoring

| Level | Range | Meaning |
|-------|-------|---------|
| **HIGH** | 0.80 - 1.0 | All criteria MET with high confidence, no gaps |
| **MEDIUM** | 0.50 - 0.79 | Most criteria MET but some with moderate evidence |
| **LOW** | 0.0 - 0.49 | Significant gaps, INSUFFICIENT criteria, or agent errors |

Computed from: per-criterion confidence (Coverage Agent), extraction confidence
(Clinical Agent), compliance completeness, and agent error penalties.

### Audit Justification Document

The orchestrator generates a structured audit document (Markdown + PDF) with 8 sections.
The PDF version is professionally formatted with color-coded sections, status-colored
criterion tables (green/red/amber), confidence bars, and branded headers/footers:

1. **Executive Summary** — patient, provider, decision, confidence
2. **Medical Necessity Assessment** — provider info, policies, clinical evidence
3. **Criterion-by-Criterion Evaluation** — each criterion with status, confidence, evidence
4. **Validation Checks** — provider NPI, diagnosis codes, compliance checklist
5. **Decision Rationale** — gate, confidence, supporting facts
6. **Documentation Gaps** — critical and non-critical gaps with requests
7. **Audit Trail** — data sources, timestamps, confidence metrics
8. **Regulatory Compliance** — decision policy and requirements

---

## Anthropic Healthcare MCP Servers

This project consumes **remote MCP servers** from the
[anthropics/healthcare](https://github.com/anthropics/healthcare) marketplace.
These are hosted HTTP endpoints — no local MCP server setup is needed.

| MCP Server | Endpoint | Used By | Key Tools |
|---|---|---|---|
| **NPI Registry** | `mcp.deepsense.ai/npi_registry/mcp` | Coverage Agent | `npi_validate`, `npi_lookup`, `npi_search` |
| **ICD-10 Codes** | `mcp.deepsense.ai/icd10_codes/mcp` | Clinical Agent | `validate_code`, `lookup_code`, `search_codes`, `get_hierarchy`, `get_by_category`, `get_by_body_system` |
| **CMS Coverage** | `mcp.deepsense.ai/cms_coverage/mcp` | Coverage Agent | `search_national_coverage`, `search_local_coverage`, `get_coverage_document`, `get_contractors`, `get_whats_new_report`, `batch_get_ncds`, `sad_exclusion_list` |
| **Clinical Trials** | `mcp.deepsense.ai/clinical_trials/mcp` | Clinical Agent | `search_trials`, `get_trial_details`, `search_by_eligibility`, `search_investigators`, `analyze_endpoints`, `search_by_sponsor` |
| **PubMed** | `pubmed.mcp.claude.com/mcp` | Clinical Agent | `search` |

### How MCP is integrated

```
mcp_config.py     — Server URL + headers config (User-Agent: claude-code/1.0)
    ↓ passed via
ClaudeAgentOptions.mcp_servers   — Each agent gets its relevant MCP servers
    ↓ handled by
Claude Agent SDK  — Auto-discovers tools, manages sessions, invokes tools
```

No custom MCP client or wrapper functions needed. The Claude SDK handles
tool discovery, session lifecycle, and invocation via the MCP protocol.

---

## Project Structure

```
prior-auth-maf/
├── backend/
│   ├── .env                              # Environment config (not committed)
│   ├── requirements.txt                  # Python dependencies
│   ├── run.py                            # Dev server launcher (ProactorEventLoop for Windows --reload)
│   ├── _proactor_startup.py              # PYTHONSTARTUP script for uvicorn reload workers (Windows)
│   ├── test_af_mcp_tool.py              # MCPStreamableHTTPTool test (validates header injection)
│   ├── test_skills_poc.py               # POC test validating skills + MCP coexistence in MAF
│   ├── .claude/
│   │   ├── skills/
│   │   │   ├── compliance-review/SKILL.md    # Compliance validation skill (8-item checklist)
│   │   │   ├── clinical-review/SKILL.md      # Clinical review skill (ICD-10 + PubMed + trials)
│   │   │   ├── coverage-assessment/SKILL.md  # Coverage assessment skill (NPI + CMS policies)
│   │   │   └── synthesis-decision/SKILL.md   # Synthesis & decision skill (gate-based rubric)
│   │   └── references/
│   │       ├── rubric.md                     # Decision policy rubric (shared by synthesis skill)
│   │       └── output-formats.md             # JSON output schemas for all 4 agents
│   └── app/
│       ├── main.py                       # FastAPI app, CORS, router mounts (review + decision)
│       ├── config.py                     # Settings (API keys, MCP endpoints)
│       ├── patches/
│       │   └── __init__.py               # Windows Claude SDK patches (CMD bypass, API creds, model mapping, event loop)
│       ├── agents/
│       │   ├── __init__.py               # Exports run_multi_agent_review + store functions
│       │   ├── _parse.py                 # Shared JSON response parser
│       │   ├── compliance_agent.py       # Compliance Agent (no tools)
│       │   ├── clinical_agent.py         # Clinical Reviewer Agent (icd10-codes, pubmed, clinical-trials MCP)
│       │   ├── coverage_agent.py         # Coverage Agent (npi-registry, cms-coverage MCP) + Diagnosis-Policy Alignment
│       │   ├── orchestrator.py           # Multi-agent coordinator + CPT pre-flight + synthesis + audit + review store
│       │   └── prior_auth_agent.py       # Single-agent mode (all 5 MCP servers)
│       ├── services/
│       │   ├── audit_pdf.py              # Audit justification PDF generation (fpdf2) — 8 color-coded sections
│       │   ├── cpt_validation.py         # CPT/HCPCS format validation + curated lookup table (~30 codes)
│       │   └── notification.py           # Auth number generation + approval/pend letter templates + PDF (fpdf2)
│       ├── tools/
│       │   └── mcp_config.py             # MCP server configs with User-Agent header
│       ├── models/
│       │   └── schemas.py                # Pydantic models (request, response, per-agent, audit, decision, notification)
│       └── routers/
│           ├── review.py                 # POST /api/review + POST /api/review/stream (SSE) + GET endpoints
│           └── decision.py              # POST /api/decision (accept/override + letter generation)
│
├── frontend/
│   ├── package.json                      # Next.js 16 + shadcn/ui + Tailwind CSS
│   ├── next.config.ts                    # Static export (output: 'export')
│   ├── tsconfig.json                     # TypeScript config (path alias @/*)
│   ├── components.json                   # shadcn/ui configuration
│   ├── .env.example                      # Environment variable template
│   ├── app/
│   │   ├── globals.css                   # Tailwind directives + Microsoft theme variables
│   │   ├── layout.tsx                    # Root layout (metadata, font, body)
│   │   └── page.tsx                      # Main page (form + dashboard)
│   ├── components/
│   │   ├── ui/                           # shadcn/ui primitives (badge, button, card, etc.)
│   │   ├── header.tsx                    # App title + subtitle
│   │   ├── confidence-bar.tsx            # Reusable green/amber/red progress bar
│   │   ├── upload-form.tsx               # PA request form + "Load Sample Case" + SSE submit
│   │   ├── progress-tracker.tsx          # Real-time agent progress (phase timeline, agent cards, timer)
│   │   ├── review-dashboard.tsx          # Results: summary, confidence, gaps, audit trail, justification download
│   │   ├── agent-details.tsx             # Tabbed per-agent breakdown (Compliance/Clinical/Coverage)
│   │   └── decision-panel.tsx            # Accept/Override decision + letter preview + PDF download
│   └── lib/
│       ├── api.ts                        # Backend API client (submitReviewStream + submitDecision)
│       ├── types.ts                      # TypeScript types (request, response, agents, audit, decision, progress)
│       ├── sample-case.ts                # Sample case data for demo
│       └── utils.ts                      # shadcn cn() utility
│
├── .gitignore
├── .dockerignore                          # Docker build exclusions
├── docker-compose.yml                     # Two-container local dev (backend + frontend)
├── backend/
│   └── Dockerfile                         # Python + Claude Agent SDK (CLI bundled in wheel)
├── frontend/
│   ├── Dockerfile                         # Multi-stage: Node build → Nginx serve (static export)
│   └── nginx.conf                         # Proxies /api → backend, SPA catch-all, /_next/static cache
└── README.md                             # This file
```

---

## Prerequisites

- **Python 3.11+**
- **Node.js 18+**
- **Azure AI Foundry account** with access to Claude models
- Azure Foundry API key and endpoint

---

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/amitmukh/prior-auth-maf.git
cd prior-auth-maf
```

### 2. Backend setup

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

# Configure environment
cp .env.example .env
```

Edit `.env` and set your Azure Foundry credentials:

```env
AZURE_FOUNDRY_API_KEY=your-azure-foundry-api-key
AZURE_FOUNDRY_ENDPOINT=https://your-endpoint.services.ai.azure.com
CLAUDE_MODEL=claude-sonnet-4-20250514

# Skills-based approach (default: true)
# true  = agents use SKILL.md files via MAF native skill discovery
# false = agents use inline system prompt instructions (prompt-based)
USE_SKILLS=true
```

The MCP server endpoints are pre-configured with defaults from the
[anthropics/healthcare](https://github.com/anthropics/healthcare) marketplace.

### 3. Frontend setup

```bash
cd frontend
npm install

# Configure environment (optional — defaults work for local dev)
cp .env.example .env.local
```

### 4. Run the application

Start both servers (in separate terminals):

**Backend** (runs on port 8000):
```bash
cd backend
uvicorn app.main:app --reload
```

**Frontend** (runs on port 3000, calls backend directly via CORS):
```bash
cd frontend
cp .env.example .env.local   # sets NEXT_PUBLIC_API_BASE=http://localhost:8000/api
npm run dev
```

Open `http://localhost:3000` in your browser.

> **Note:** The frontend calls the backend directly (not through a Next.js
> rewrite proxy) because multi-agent reviews take 3-5 minutes — longer than
> the dev server proxy's default timeout. CORS on the backend is configured
> to allow `http://localhost:3000`.

---

## API Reference

### `POST /api/review`

Submit a prior authorization request for multi-agent review.
Returns the complete result as a single JSON response (no streaming).
Prefer `POST /api/review/stream` for the frontend — this endpoint is
useful for programmatic/API integrations that don't need progress updates.

**Request body:**

```json
{
  "patient_name": "John Smith",
  "patient_dob": "1955-03-15",
  "provider_npi": "1234567890",
  "diagnosis_codes": ["M17.11", "M17.12"],
  "procedure_codes": ["27447"],
  "clinical_notes": "Patient presents with bilateral knee OA...",
  "insurance_id": "ABC123456"
}
```

**Response** (top-level synthesis + per-agent breakdown + audit trail):

```json
{
  "request_id": "uuid",
  "recommendation": "approve",
  "confidence": 0.87,
  "confidence_level": "HIGH",
  "summary": "All three agents report clean findings...",
  "tool_results": [...],
  "clinical_rationale": "Gate 1 PASS: Provider NPI active. Gate 2 PASS: All ICD-10 codes valid...",
  "coverage_criteria_met": ["Criterion — evidence"],
  "coverage_criteria_not_met": [],
  "missing_documentation": [],
  "documentation_gaps": [
    {"what": "Prior imaging results", "critical": false, "request": "Please provide X-ray reports"}
  ],
  "policy_references": ["NCD 150.7 — Joint Replacement"],
  "disclaimer": "AI-assisted draft. Coverage policies reflect Medicare LCDs/NCDs only...",
  "agent_results": {
    "compliance": {
      "checklist": [...],
      "overall_status": "complete",
      "missing_items": []
    },
    "clinical": {
      "diagnosis_validation": [{"code": "M17.11", "valid": true, "billable": true, ...}],
      "clinical_extraction": {
        "chief_complaint": "...",
        "extraction_confidence": 82
      },
      "literature_support": [...]
    },
    "coverage": {
      "provider_verification": {"npi": "...", "status": "active", ...},
      "criteria_assessment": [
        {"criterion": "...", "status": "MET", "confidence": 85, "evidence": [...]}
      ],
      "documentation_gaps": [...]
    }
  },
  "audit_trail": {
    "data_sources": ["CPT/HCPCS Format Validation (Local)", "NPI Registry MCP (NPPES)", "ICD-10 MCP (2026 Code Set)", ...],
    "review_started": "2026-02-13T10:30:00Z",
    "review_completed": "2026-02-13T10:30:45Z",
    "extraction_confidence": 82,
    "assessment_confidence": 78,
    "criteria_met_count": "4/5"
  }
}
```

### `POST /api/review/stream`

Submit a prior authorization request with **real-time SSE progress streaming**.
Same request body as `POST /api/review`. Returns `text/event-stream`.

The frontend uses `fetch` + `ReadableStream` (not `EventSource`, which only
supports GET) to consume this endpoint.

**SSE event types:**

| Event | When | Payload |
|-------|------|---------|
| `progress` | At each phase boundary (9 total) | `{phase, status, progress_pct, message, agents}` |
| `result` | Review complete | Full `ReviewResponse` JSON |
| `error` | Pipeline failure | `{detail: "error message"}` |
| `: keepalive` | Every 2s during long agent runs | SSE comment (ignored by client) |

**Progress event example:**

```json
{
  "phase": "phase_1",
  "status": "running",
  "progress_pct": 10,
  "message": "Running Compliance and Clinical agents in parallel",
  "agents": {
    "compliance": {"status": "running", "detail": "Checking documentation completeness"},
    "clinical": {"status": "running", "detail": "Validating codes and extracting clinical evidence"}
  }
}
```

**Phase IDs:** `preflight` → `phase_1` → `phase_2` → `phase_3` → `phase_4`

**Agent statuses:** `pending` → `running` → `done` | `error`

### `GET /health`

Health check endpoint. Returns `{"status": "ok"}`.

### `GET /api/review/{request_id}`

Retrieve a previously completed review by its request ID.

**Response:** Same `ReviewResponse` structure as `POST /api/review`.

Returns `404` if the request ID is not found in the review store.

### `GET /api/reviews`

List all completed reviews (most recent first).

**Response:**

```json
[
  {
    "request_id": "uuid",
    "patient_name": "John Smith",
    "recommendation": "approve",
    "confidence_level": "HIGH",
    "reviewed_at": "2026-02-13T10:30:45Z",
    "decision_made": false
  }
]
```

### `POST /api/decision`

Submit a human reviewer decision (accept or override) for a completed review.
Generates an authorization number and notification letter.

**Request body (accept):**

```json
{
  "request_id": "uuid",
  "action": "accept",
  "reviewer_name": "Dr. Jane Doe"
}
```

**Request body (override):**

```json
{
  "request_id": "uuid",
  "action": "override",
  "override_recommendation": "approve",
  "override_rationale": "Clinical evidence supports approval despite agent uncertainty...",
  "reviewer_name": "Dr. Jane Doe"
}
```

**Response:**

```json
{
  "request_id": "uuid",
  "authorization_number": "PA-20260213-00001",
  "final_recommendation": "approve",
  "decided_by": "Dr. Jane Doe",
  "decided_at": "2026-02-13T11:05:00Z",
  "was_overridden": false,
  "letter": {
    "authorization_number": "PA-20260213-00001",
    "letter_type": "approval",
    "effective_date": "2026-02-13",
    "expiration_date": "2026-05-14",
    "patient_name": "John Smith",
    "provider_name": "Dr. ...",
    "body_text": "PRIOR AUTHORIZATION — APPROVED ...",
    "appeal_rights": null,
    "documentation_deadline": null,
    "pdf_base64": "JVBERi0xLjQg..."
  }
}
```

**Error responses:**
- `404` — Review not found (request_id does not exist)
- `409` — Decision already recorded for this review
- `422` — Invalid action or missing override fields

---

## Key Dependencies

| Package | Purpose |
|---|---|
| `fastapi` | REST API framework |
| `uvicorn` | ASGI server |
| `agent-framework-claude` | Microsoft Agent Framework with Claude SDK |
| `fpdf2` | PDF generation for notification letters |
| `pydantic` | Request/response validation |
| `react` + `next` | Frontend SPA (Next.js static export) |
| `shadcn/ui` + `tailwindcss` | UI component library + utility-first CSS |

Note: No `mcp` Python SDK or `httpx` dependency needed — the Claude SDK
handles MCP communication internally via `McpHttpServerConfig`.

---

## Extending the Application

### Add a new agent

1. Create a new file in `backend/app/agents/` (e.g. `pharmacy_agent.py`)
2. Create a SKILL.md file in `backend/.claude/skills/<agent-name>/SKILL.md`
   with the agent's instructions, execution steps, output format, quality
   checks, and common mistakes to avoid
3. Define focused system instructions and assign relevant MCP servers via `mcp_config.py`
4. Create the agent with the `USE_SKILLS` toggle pattern (see existing agents)
5. Add the agent call to `orchestrator.py` (parallel or sequential)
6. Add the agent's output schema to `backend/.claude/references/output-formats.md`
7. Add the agent's result model to `schemas.py` and `AgentResults`
8. Add a tab for it in `frontend/components/agent-details.tsx`

### Add a new MCP server

1. Add the MCP server URL to `config.py` settings
2. Add a server config entry in `mcp_config.py` with the `_HEADERS` dict
3. Add it to the appropriate server group (`CLINICAL_MCP_SERVERS`, `COVERAGE_MCP_SERVERS`, etc.)
4. Reference the new tools by their actual MCP tool names in the agent's instructions

### Change the decision rubric

In **skills mode** (`USE_SKILLS=true`, default), edit the decision rubric in
two places:
- `backend/.claude/skills/synthesis-decision/SKILL.md` — the gate-based
  evaluation tables and confidence formula used by the Synthesis Agent
- `backend/.claude/references/rubric.md` — the shared reference file with
  override permissions, strict mode option, and confidence level definitions

In **prompt mode** (`USE_SKILLS=false`), edit `SYNTHESIS_INSTRUCTIONS` in
`orchestrator.py` — the inline gate-based evaluation that maps agent findings
to APPROVE/PEND outcomes. The gates can be reordered, criteria added, or the
policy mode changed from LENIENT to STRICT (which would allow DENY
recommendations).

### Customize notification letters

Edit `backend/app/services/notification.py` to change letter templates.
The `generate_approval_letter()` and `generate_pend_letter()` functions
produce structured text with authorization details, validity periods,
and appeal rights. The `generate_letter_pdf()` function renders
a professionally formatted PDF using `fpdf2` with color-coded titles,
section headings, and an AI-draft disclaimer watermark. Modify the
templates to match your organization's letterhead format, add additional
fields, or change validity periods (default: 90 days for approvals,
30 days for pend documentation deadlines).

### Add CPT/HCPCS codes to the lookup table

Edit `_KNOWN_CODES` in `backend/app/services/cpt_validation.py` to add
procedure codes relevant to your specialty. The curated table provides
informational descriptions in the audit trail — it does not block
unknown codes (format validation is the only hard gate).

### Use MCP with non-Claude models

Use `MCPStreamableHTTPTool` from the Agent Framework with a custom
`httpx.AsyncClient` to inject the `User-Agent` header. This works with
any LLM client (OpenAI, Gemini, etc.) — MCP is model-agnostic.

```python
import httpx
from agent_framework import MCPStreamableHTTPTool

http_client = httpx.AsyncClient(headers={"User-Agent": "claude-code/1.0"})
mcp_tool = MCPStreamableHTTPTool(name="npi", url=NPI_URL, http_client=http_client)

async with mcp_tool:
    result = await mcp_tool.session.call_tool("npi_validate", {"npi": "1234567893"})
```

---

## Technical Notes

### Windows Claude SDK patches (`app/patches/__init__.py`)

On Windows, the Claude Agent SDK encounters three issues when spawning the
Claude Code CLI as a subprocess. The `app/patches/__init__.py` module fixes
all three, applied automatically at server startup in `main.py`. The patches
are idempotent and safe on all platforms (they detect platform/environment
before activating).

**Patch 1 — `.CMD` batch file bypass:**

On Windows, the Claude Code CLI is installed as a `.CMD` batch file wrapper
(e.g., `claude.CMD`). When Python's `subprocess` module runs a `.CMD` file,
it routes through `cmd.exe /c`, which interprets newlines and special
characters (`|`, `&`, `<`, `>`) inside `--system-prompt` arguments as
command separators. This breaks all agent invocations because the system
prompts contain multi-line instructions with pipe characters.

**Fix:** Monkey-patches `SubprocessCLITransport._build_command` to replace
the `.CMD` wrapper with a direct `node.exe cli.js` invocation, bypassing
`cmd.exe` entirely.

**Patch 2 — API credential override + Foundry auth:**

When running inside a Claude Code editor session (e.g., VS Code), the
environment inherits a local-proxy `ANTHROPIC_API_KEY` and
`ANTHROPIC_BASE_URL` that only work for the parent editor process. The SDK
subprocess inherits these invalid credentials, resulting in empty responses
(cost $0, `tokenSource: 'none'`).

Additionally, the Claude Code CLI requires Foundry-specific environment
variables for Azure authentication: `CLAUDE_CODE_USE_FOUNDRY=true`,
`ANTHROPIC_FOUNDRY_API_KEY`, and `ANTHROPIC_FOUNDRY_BASE_URL`. Without
these, the CLI fails at startup with "Failed to start Claude Code:".

**Fix:** Overrides `ANTHROPIC_API_KEY` and `ANTHROPIC_BASE_URL` with the
real Azure Foundry credentials from the `.env` file
(`AZURE_FOUNDRY_API_KEY` / `AZURE_FOUNDRY_ENDPOINT`), and also sets the
Foundry-specific env vars (`CLAUDE_CODE_USE_FOUNDRY=true`,
`ANTHROPIC_FOUNDRY_API_KEY`, `ANTHROPIC_FOUNDRY_BASE_URL`).

**Patch 3 — Model mapping:**

The Claude Agent SDK's `ClaudeAgentSettings` reads the model from the
`CLAUDE_AGENT_MODEL` environment variable (not `CLAUDE_MODEL`). Without
this mapping, the CLI defaults to `claude-sonnet-4-5-20250929`, which may
not be available on Azure Foundry endpoints.

**Fix:** Maps `CLAUDE_MODEL` from `.env` to `CLAUDE_AGENT_MODEL` so the
SDK uses the correct model (e.g., `claude-opus-4-5`).

**Patch 4 — Windows asyncio event loop (ProactorEventLoop):**

On Windows, `asyncio.create_subprocess_exec()` only works with
`ProactorEventLoop`. When uvicorn runs with `--reload`, the worker process
may use `SelectorEventLoop` which raises `NotImplementedError` when the
SDK tries to spawn the Claude Code CLI as a subprocess.

**Fix:** Sets `asyncio.WindowsProactorEventLoopPolicy()` before the event
loop is created, ensuring subprocess support is available.

**When these patches activate:**

| Patch | Activates when | In Linux/Docker? |
|-------|---------------|-----------------|
| CMD bypass | `os.name == "nt"` and `shutil.which("claude")` returns a `.CMD` file | No |
| API credentials + Foundry auth | `AZURE_FOUNDRY_API_KEY` is set in the environment | No (no editor session) |
| Model mapping | `CLAUDE_MODEL` is set in the environment | Yes (harmless) |
| ProactorEventLoop | `os.name == "nt"` and current policy is not already Proactor | No |

On Linux/macOS or in Docker containers (where the CLI is bundled in the
`claude-agent-sdk` wheel as a native binary), only the model mapping
patch activates — the other three are Windows-specific and skip
automatically. **You will not encounter these issues when deploying to
Azure in a container.**

### MCP header injection

The DeepSense-hosted MCP servers require `User-Agent: claude-code/1.0` due
to CloudFront routing rules. Without it, requests get a 301 redirect to
documentation pages. This header is injected via:

- **`McpHttpServerConfig.headers`** — for Claude SDK agents (production path)
- **`httpx.AsyncClient` custom headers** — for `MCPStreamableHTTPTool` (model-agnostic path)

Azure OpenAI's Responses API native MCP support (`type: "mcp"` with `headers`)
does **not** work because Azure's proxy does not forward the `User-Agent` header.

### Anthropic Agent Skills — Comparison

The [Anthropic prior-auth-review-skill](https://github.com/anthropics/healthcare/tree/main/prior-auth-review-skill)
is a Claude Code Skill (SKILL.md prompt file) that uses progressive disclosure
to minimize token consumption.

This project now supports **two modes**, controlled by the `USE_SKILLS`
environment variable:

| Mode | `USE_SKILLS` | How agents are configured |
|------|-------------|--------------------------|
| **Skills-based** (default) | `true` | Each agent uses a SKILL.md file discovered via MAF native skill discovery (`setting_sources` + `allowed_tools: ["Skill"]`) |
| **Prompt-based** (fallback) | `false` | Each agent uses inline system prompt instructions (original approach) |

#### Skills-based approach — how it works

The Microsoft Agent Framework (MAF) supports custom skills natively through
`ClaudeAgent` configuration:

```python
agent = ClaudeAgent(
    instructions="You are a Clinical Reviewer. Use your clinical-review Skill.",
    default_options={
        "cwd": str(backend_dir),
        "setting_sources": ["user", "project"],
        "allowed_tools": ["Skill", "mcp__icd10-codes__validate_code", "mcp__pubmed__search", ...],
        "mcp_servers": {"icd10-codes": ICD10_SERVER, "pubmed": PUBMED_SERVER, "clinical-trials": TRIALS_SERVER},
        "permission_mode": "bypassPermissions",
    },
)
```

Skills are defined as `SKILL.md` files in `.claude/skills/<name>/SKILL.md`
and are automatically discovered by Claude based on their descriptions. Four
skills are defined:

| Skill | Directory | MCP servers | Purpose |
|-------|-----------|-------------|---------|
| Compliance Review | `.claude/skills/compliance-review/` | None | 8-item documentation completeness checklist |
| Clinical Review | `.claude/skills/clinical-review/` | icd10-codes, pubmed, clinical-trials | Code validation, clinical extraction, literature + trials |
| Coverage Assessment | `.claude/skills/coverage-assessment/` | npi-registry, cms-coverage | Provider verification, policy search, criteria mapping |
| Synthesis Decision | `.claude/skills/synthesis-decision/` | None | Gate-based evaluation, weighted confidence, final recommendation |

Shared reference files in `.claude/references/` provide the decision policy
rubric and JSON output schemas that all skills reference.

#### Architectural difference

The Anthropic skill is a **single-agent, multi-turn** design: one Claude agent
holds all MCP tools and progresses through the review using progressive
disclosure (SKILL.md waypoints). This project uses a **multi-agent pipeline**:
four specialized agents with partitioned tools, coordinated by a Python
orchestrator. Each agent has its own SKILL.md with focused instructions.

#### Features: our skills-based approach vs Anthropic skill

| # | Feature | Our skills-based approach | Anthropic skill |
|---|---------|--------------------------|-----------------|
| 1 | Multi-agent parallelism | Compliance + Clinical concurrent via `asyncio.gather` | Single agent, sequential |
| 2 | Per-criterion confidence | Numeric 0-100 per criterion | Binary MET/NOT_MET/INSUFFICIENT |
| 3 | Extraction confidence | 0-100 per clinical extraction field | Not scored |
| 4 | Explicit confidence formula | Weighted: criteria 40%, extraction 30%, compliance 20%, policy 10% | Subjective assessment |
| 5 | Real MCP tool names | `mcp__icd10-codes__validate_code` etc. | Generic `icd10_validate` |
| 6 | PDF audit justification | Color-coded 8-section PDF with tables + confidence bars | Markdown only |
| 7 | Dedicated compliance agent | 8-item checklist as separate skill + agent | Embedded in single review |
| 8 | Diagnosis-Policy Alignment | Explicit auditable criterion in every coverage assessment | Not a distinct step |
| 9 | Code hierarchy exploration | `get_hierarchy` suggests specific billable codes for non-billable categories | Just flags invalid |
| 10 | SSE streaming | 9 real-time progress events | Batch (runs to completion) |
| 11 | Clinical trials + PubMed | Active MCP integration in clinical review skill | Referenced but not used in intake subskill |
| 12 | Frontend UI | Next.js dashboard with tabbed agent details | CLI-only |

#### Features taken from the Anthropic skill

The skills-based approach incorporates elements from the Anthropic skill that
were not in our original prompt-based implementation:

- **Quality checks** — each SKILL.md ends with a verification checklist
- **Common mistakes to avoid** — explicit anti-patterns for each agent
- **Demo mode NPI bypass** — skip NPPES lookup for test NPI + sample member ID
- **Coverage policy limitation notice** — Medicare LCDs/NCDs disclaimer for non-Medicare plans
- **Override permissions** — documented escalation/downgrade rules for human reviewers
- **Recent policy check** — `get_whats_new_report` for recently revised policies
- **Decision audit trail** — gate-by-gate evaluation with confidence component breakdown
- **Appeals guidance** — specific documentation requests for PEND decisions

#### Features equivalent to the Anthropic skill

Both implementations share: ICD-10 validation via MCP, NPI provider
verification via MCP, CMS coverage policy search via MCP, PubMed literature
search via MCP, clinical trials search via MCP, LENIENT mode (never DENY —
only APPROVE or PEND), gate-based evaluation (Provider → Codes → Medical
Necessity), MET/NOT_MET/INSUFFICIENT status per criterion, human-in-the-loop
decision flow (accept/override), notification letter generation (approval and
pend types), and structured audit trails.

#### Three-way comparison

| Aspect | Skills-based (default) | Prompt-based (fallback) | Anthropic skill |
|--------|----------------------|------------------------|-----------------|
| Agent configuration | SKILL.md files via MAF discovery | Inline system instructions | SKILL.md via Claude Code Skills API |
| Token efficiency | Progressive disclosure — only loaded when invoked | Full prompt (~800-900 tokens per agent) | Progressive disclosure per subskill |
| Prompt vetting | Best of both: Anthropic patterns + our enhancements | Written independently | Anthropic's internal clinical review |
| Parallelism | Multi-agent, concurrent | Multi-agent, concurrent | Single agent, sequential |
| Platform | Azure Foundry via MAF | Azure Foundry via MAF | Claude Code with Skills API beta headers |
| Confidence formula | Explicit weighted (4 components) | Per-agent averages | Subjective assessment |
| Toggle | `USE_SKILLS=true` (default) | `USE_SKILLS=false` | N/A |

### Prompt caching

The agent instructions are sent as the system prompt on every API call,
consuming ~800-900 input tokens per agent (~3,100 total per review). Anthropic's
[prompt caching](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching)
can reduce this cost by ~90% for repeated identical system prompts. The Claude
SDK may leverage this automatically.

### Decision & notification flow

The decision flow implements Subskill 2 from the
[Anthropic prior-auth-review-skill](https://github.com/anthropics/healthcare/tree/main/prior-auth-review-skill),
adapted as an API-driven workflow instead of file-based waypoints:

1. Review completes → stored in-memory (keyed by `request_id`)
2. Frontend shows **Accept** / **Override** panel with reviewer name field
3. `POST /api/decision` validates review exists, prevents double-decisions (409)
4. Generates thread-safe authorization number (`PA-YYYYMMDD-XXXXX`)
5. Produces appropriate notification letter (approval or pend) in both
   plain text and PDF (via `fpdf2`, base64-encoded for JSON transport)
6. PDF available for preview and `.pdf` download in the frontend
   (falls back to `.txt` if PDF generation fails)

**Notification letter types:**
- **Approval** — includes authorization number, validity period (90 days),
  procedure/diagnosis summary, standard terms, and disclaimer
- **Pend** — includes missing documentation list (consolidated from
  `missing_documentation` and `documentation_gaps` with criticality labels),
  30-day deadline, and appeal rights

**PDF generation** (`fpdf2`):
- Custom `_LetterPDF` subclass with branded header ("PRIOR AUTHORIZATION —
  UTILIZATION MANAGEMENT") and footer ("AI-ASSISTED DRAFT — REVIEW REQUIRED"
  + page numbers)
- Color-coded titles: green tint for approvals, amber tint for pends
- Structured sections: patient/provider info, approved/requested services,
  authorization period, clinical summary, missing documentation (pend only),
  deadline (pend only), appeal rights, terms and conditions, disclaimer
  watermark bar
- Base64-encoded and included in the `DecisionResponse.letter.pdf_base64`
  field for JSON transport — no separate download endpoint needed
- Frontend decodes base64 → `Uint8Array` → `Blob` → `URL.createObjectURL`
  for browser download

The in-memory store resets on server restart. For production, replace
`_review_store` in `orchestrator.py` with a persistent database.

### CPT/HCPCS validation

Procedure code validation runs as a pre-flight step before any agents execute:

1. **Format validation** (definitive) — regex checks for valid CPT (5-digit
   numeric) or HCPCS Level II (letter + 4 digits) format. Invalid formats
   trigger a Gate 2 PEND.
2. **Curated lookup** (informational) — ~30 common PA-trigger codes with
   descriptions and clinical categories (pulmonary, imaging, oncology,
   orthopedic, cardiology, spine, GI, DME, genetic testing). Unrecognized
   codes with valid format are allowed through.
3. **Results injected** into the synthesis prompt so Gate 2 can evaluate
   both ICD-10 validity (from Clinical Agent) and CPT format (from pre-flight).

### Sample data

The frontend includes a **"Load Sample Case"** button (in `lib/sample-case.ts`)
that populates a CT-guided transbronchial lung biopsy case:

| Field | Value |
|-------|-------|
| Patient | John Smith, DOB 1958-03-15 |
| Provider NPI | 1902809042 |
| ICD-10 codes | R91.1 (solitary pulmonary nodule), J18.9 (pneumonia), R05.9 (cough) |
| CPT code | 31628 (bronchoscopy with transbronchial lung biopsy) |
| Insurance ID | MCR-123456789A |
| Clinical notes | 68-year-old male, 1.8 cm spiculated nodule, 40 pack-year smoking history, PET SUV 4.2, interval growth, FEV1 78% |

This case is designed to exercise all agents and MCP servers with a
realistic prior authorization scenario.

---

## Production Migration Path

The demo uses an in-memory Python dictionary for review storage and returns
generated PDFs inline as base64. This is intentional — it keeps the demo
self-contained with zero infrastructure dependencies. When moving to
production, two services need to be introduced: a relational database for
structured data and blob storage for unstructured documents.

### Current demo architecture (what gets replaced)

| Concern | Demo approach | Limitation |
|---------|--------------|------------|
| Review persistence | `_review_store` dict in `orchestrator.py` | Lost on process restart; single-process only |
| Decision storage | Same in-memory dict (`store_decision()`) | Same as above |
| Generated PDFs | Base64 in JSON response, decoded on frontend | No long-term storage; re-generation required |
| Medical documents | Pasted into a text field as clinical notes | No file upload; no original document retention |
| Audit trail | Embedded in the response JSON | Not independently queryable |

### Why the migration is straightforward

The store layer is already abstracted behind four functions in
`orchestrator.py`:

```python
store_review(request_id, request_data, response)
get_review(request_id)
list_reviews()
store_decision(request_id, decision)
```

No other module touches `_review_store` directly. Replacing the dict with
a database client requires changing only these four functions (and adding
a connection pool at startup). The rest of the codebase — agents, routers,
frontend — remains untouched.

### PostgreSQL — structured data

Use PostgreSQL (or Azure Database for PostgreSQL — Flexible Server) for
reviews, decisions, and audit records.

**Suggested schema:**

```sql
-- Reviews table: stores the full prior auth request and agent response
CREATE TABLE reviews (
    request_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_name  TEXT NOT NULL,
    patient_dob   DATE NOT NULL,
    provider_npi  VARCHAR(10) NOT NULL,
    insurance_id  TEXT,
    diagnosis_codes TEXT[] NOT NULL,        -- ICD-10 codes
    procedure_codes TEXT[] NOT NULL,        -- CPT/HCPCS codes
    clinical_notes TEXT NOT NULL,
    request_data  JSONB NOT NULL,           -- full original request
    response_data JSONB NOT NULL,           -- full agent response
    recommendation VARCHAR(20) NOT NULL,    -- 'approve' | 'pend_for_review'
    confidence    NUMERIC(3,2),             -- 0.00 - 1.00
    confidence_level VARCHAR(6),            -- HIGH | MEDIUM | LOW
    audit_justification TEXT,               -- markdown audit document
    created_at    TIMESTAMPTZ DEFAULT now(),
    updated_at    TIMESTAMPTZ DEFAULT now()
);

-- Decisions table: human reviewer accept/override actions
CREATE TABLE decisions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    review_id       UUID NOT NULL REFERENCES reviews(request_id),
    action          VARCHAR(20) NOT NULL,   -- 'accept' | 'override'
    override_decision VARCHAR(20),          -- 'approve' | 'pend_for_review' (if overridden)
    override_rationale TEXT,                -- required when action = 'override'
    auth_number     VARCHAR(30) NOT NULL,   -- PA-YYYYMMDD-XXXXX
    letter_text     TEXT NOT NULL,           -- plain-text notification letter
    letter_pdf_key  TEXT,                    -- blob storage key for PDF
    decided_by      TEXT,                    -- reviewer identifier (future auth)
    created_at      TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT one_decision_per_review UNIQUE (review_id)
);

-- Audit log: immutable append-only record of every action
CREATE TABLE audit_log (
    id          BIGSERIAL PRIMARY KEY,
    review_id   UUID NOT NULL REFERENCES reviews(request_id),
    event_type  VARCHAR(50) NOT NULL,       -- 'review_created', 'decision_made', etc.
    event_data  JSONB NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- Indexes for common queries
CREATE INDEX idx_reviews_created ON reviews(created_at DESC);
CREATE INDEX idx_reviews_recommendation ON reviews(recommendation);
CREATE INDEX idx_reviews_provider ON reviews(provider_npi);
CREATE INDEX idx_audit_log_review ON audit_log(review_id);
```

**Key points:**

- `request_data` and `response_data` are stored as `JSONB` so the full
  agent output is preserved and queryable (e.g., find all reviews where
  a specific coverage criterion was `NOT_MET`).
- The `one_decision_per_review` constraint enforces the existing 409
  Conflict guard at the database level.
- `audit_log` is append-only — no updates or deletes — for regulatory
  compliance.
- Use `asyncpg` or `SQLAlchemy[asyncio]` + `asyncpg` for async
  compatibility with the existing FastAPI/async agent pipeline.

**Migration steps:**

1. Add `asyncpg` (or `sqlalchemy[asyncio]` + `asyncpg`) to
   `requirements.txt`.
2. Add a `DATABASE_URL` environment variable (or Azure Key Vault
   reference).
3. Create a `backend/app/services/database.py` with connection pool
   setup (`asyncpg.create_pool()`) and the four replacement functions.
4. Update `orchestrator.py` to import from `database.py` instead of
   using the in-memory dict.
5. Run the schema migration (use Alembic if you want versioned
   migrations).
6. Update `decision.py` to store the blob storage key for generated
   PDFs.

### Azure Blob Storage — unstructured documents

Use Azure Blob Storage for two categories of files:

| Category | Examples | When created |
|----------|----------|-------------|
| **Uploaded medical documents** | Scanned records, lab reports, imaging CDs, referral letters | Future feature: file upload in the intake form |
| **Generated notification letters** | Approval/pend PDF letters | Each time a decision is made |

**Container layout:**

```
prior-auth-documents/
├── uploads/              # Original medical documents
│   └── {review_id}/
│       ├── lab-report.pdf
│       └── imaging-cd.zip
├── letters/              # Generated notification PDFs
│   └── {review_id}/
│       └── {auth_number}.pdf
└── audit/                # Archived audit justification docs
    └── {review_id}/
        └── audit-justification.md
```

**Suggested documents table (links blobs to reviews):**

```sql
CREATE TABLE documents (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    review_id   UUID NOT NULL REFERENCES reviews(request_id),
    doc_type    VARCHAR(30) NOT NULL,   -- 'upload', 'letter', 'audit'
    filename    TEXT NOT NULL,
    blob_url    TEXT NOT NULL,           -- full Azure Blob URL or key
    content_type TEXT,                   -- MIME type
    size_bytes  BIGINT,
    uploaded_by TEXT,                    -- uploader identifier (future auth)
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_documents_review ON documents(review_id);
```

**Integration steps:**

1. Add `azure-storage-blob` to `requirements.txt`.
2. Add `AZURE_STORAGE_CONNECTION_STRING` (or use managed identity with
   `DefaultAzureCredential` from `azure-identity`).
3. Create `backend/app/services/blob_storage.py` with `upload_blob()`
   and `get_blob_url()` helpers.
4. In `notification.py`, after generating the PDF bytes, upload to
   `letters/{review_id}/{auth_number}.pdf` and return the blob key.
5. In `decision.py`, store the blob key in `decisions.letter_pdf_key`.
6. Add a `GET /api/documents/{review_id}` endpoint to list/download
   documents for a review.
7. (Future) Add a file upload endpoint to accept medical documents
   during intake, storing them in `uploads/{review_id}/`.

### Additional dependencies

| Package | Purpose |
|---------|---------|
| `asyncpg` | Async PostgreSQL driver |
| `sqlalchemy[asyncio]` | ORM layer (optional, if you prefer ORM over raw SQL) |
| `alembic` | Database schema migrations |
| `azure-storage-blob` | Azure Blob Storage SDK |
| `azure-identity` | Managed identity auth for Azure services |

### Environment variables

```bash
# PostgreSQL
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/priorauth

# Azure Blob Storage (pick one auth method)
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;...
# OR use managed identity (no connection string needed):
AZURE_STORAGE_ACCOUNT_URL=https://<account>.blob.core.windows.net
```

### What NOT to change

- **Agent code** (`compliance_agent.py`, `clinical_agent.py`,
  `coverage_agent.py`, `orchestrator.py` synthesis logic) — agents
  receive and return plain dicts. They are unaware of storage.
- **Frontend** — the API contract (`ReviewResponse`, `DecisionResponse`)
  stays the same. The frontend doesn't know whether the backend uses a
  dict or Postgres. Built with Next.js (static export) + shadcn/ui.
- **MCP server configuration** — completely independent of storage.
- **Notification letter templates** — `generate_approval_letter()` and
  `generate_pend_letter()` produce the same text/PDF regardless of where
  it's stored afterward.

---

## Docker Deployment

### Architecture

The app runs as two containers — a Python backend and an Nginx frontend:

```
┌────────────────────────────────────────────────────────────┐
│  localhost:3000 (frontend - Nginx)                         │
│    ├── /*      → Next.js SPA (static export)                 │
│    └── /api/*  → reverse proxy to backend:8000             │
│                   (300s timeout for agent processing)      │
└──────────────────────┬─────────────────────────────────────┘
                       │
┌──────────────────────▼─────────────────────────────────────┐
│  backend:8000 (FastAPI + uvicorn)                          │
│    ├── /api/review    → multi-agent orchestrator           │
│    ├── /api/decision  → accept/override + PDF letter       │
│    └── /health        → container health check             │
│                                                            │
│  ClaudeAgent (MS Agent Framework)                          │
│    └── claude-agent-sdk                                    │
│         └── bundled Claude Code CLI (in platform wheel)    │
│              ├── Azure Foundry API (via env vars)          │
│              └── MCP Servers (NPI, ICD-10, CMS, PubMed,   │
│                   Clinical Trials)                         │
└────────────────────────────────────────────────────────────┘
```

### How the Claude Agent SDK works

The `claude-agent-sdk` Python package ships **platform-specific wheels** for
Linux x86-64, Linux ARM64, macOS ARM64, and Windows x64. Each wheel bundles
the Claude Code CLI binary inside `_bundled/` — no separate Node.js or CLI
installation is needed.

When `ClaudeAgent.run()` is called, the SDK spawns the bundled CLI as a
subprocess, which handles:

- Anthropic API calls (authenticated via `ANTHROPIC_FOUNDRY_*` env vars)
- MCP server connections and tool routing
- Tool execution loop (tool_use → tool_result → repeat)
- Session and context management

On platforms without a pre-built wheel (e.g., Windows ARM64), the SDK falls
back to a system-installed `claude` CLI via `shutil.which("claude")`.

### Prerequisites

- Docker Desktop (or any OCI container runtime with compose support)
- Azure Foundry API key and endpoint

### Container details

**Backend container** (`backend/Dockerfile`):

| Layer | Details |
|-------|---------|
| Base image | `python:3.12-slim` |
| System packages | `curl` (for health check only) |
| Python dependencies | `pip install -r requirements.txt` |
| Claude Code CLI | Bundled inside `claude-agent-sdk` platform wheel — no Node.js needed |
| Port | 8000 |

**Frontend container** (`frontend/Dockerfile`):

| Layer | Details |
|-------|---------|
| Build stage | `node:20-slim` — `npm ci && npm run build` (Next.js static export to `out/`) |
| Runtime stage | `nginx:alpine` — serves built Next.js app |
| Proxy | `/api/*` → `http://backend:8000` (via `nginx.conf`) |
| Static cache | `/_next/static/` — 1-year immutable cache |
| Port | 80 (mapped to 3000 in docker-compose) |

### Running locally with Docker Compose

```bash
# Build and start both containers
docker compose up --build

# App is available at http://localhost:3000
# Backend health check at http://localhost:8000/health
```

The `docker-compose.yml` reads your `backend/.env` file and maps the Azure
Foundry credentials to the environment variables the Claude Code CLI expects:

| Your `.env` variable | Maps to (container) | Purpose |
|----------------------|---------------------|---------|
| `AZURE_FOUNDRY_API_KEY` | `ANTHROPIC_FOUNDRY_API_KEY` | Azure Foundry auth |
| `AZURE_FOUNDRY_ENDPOINT` | `ANTHROPIC_FOUNDRY_BASE_URL` | Foundry endpoint URL |
| (set automatically) | `CLAUDE_CODE_USE_FOUNDRY=true` | Enables Foundry mode |

### Building without local Docker (Azure Container Registry)

If your machine doesn't support virtualization (required for Docker Desktop),
build directly in Azure:

```bash
# Create a container registry (one-time)
az acr create --name priorauthacr --resource-group <rg> --sku Basic

# Build images in the cloud — no local Docker needed
az acr build --registry priorauthacr \
  --image prior-auth-backend:latest \
  --file backend/Dockerfile ./backend

az acr build --registry priorauthacr \
  --image prior-auth-frontend:latest \
  --file frontend/Dockerfile ./frontend
```

### Deploying to Azure Container Apps

```bash
# Create Container Apps environment (one-time)
az containerapp env create \
  --name prior-auth-env \
  --resource-group <rg> \
  --location <region>

# Deploy backend
az containerapp create \
  --name prior-auth-backend \
  --resource-group <rg> \
  --environment prior-auth-env \
  --image <acr-name>.azurecr.io/prior-auth-backend:latest \
  --target-port 8000 \
  --ingress internal \
  --min-replicas 1 \
  --env-vars \
    CLAUDE_CODE_USE_FOUNDRY=true \
    ANTHROPIC_FOUNDRY_API_KEY=secretref:foundry-key \
    ANTHROPIC_FOUNDRY_BASE_URL=https://<resource>.services.ai.azure.com/anthropic \
    FRONTEND_ORIGIN=https://prior-auth-frontend.<region>.azurecontainerapps.io

# Deploy frontend
az containerapp create \
  --name prior-auth-frontend \
  --resource-group <rg> \
  --environment prior-auth-env \
  --image <acr-name>.azurecr.io/prior-auth-frontend:latest \
  --target-port 80 \
  --ingress external \
  --min-replicas 1
```

> **Note:** Update the frontend `nginx.conf` to proxy `/api` to the backend
> Container App's internal FQDN instead of `http://backend:8000` when
> deploying to Azure Container Apps.

---

## Troubleshooting

### "Failed to start Claude SDK client: Failed to start Claude Code:"

All three agents fail with an empty error message on Windows.

**Cause 1 — CMD bypass:** The Claude Code CLI is installed as a `.CMD`
batch file wrapper. When the SDK spawns it as a subprocess, `cmd.exe`
mangles newlines and special characters in the `--system-prompt` argument.

**Cause 2 — Missing Foundry auth:** The Claude Code CLI requires
Foundry-specific env vars (`CLAUDE_CODE_USE_FOUNDRY=true`,
`ANTHROPIC_FOUNDRY_API_KEY`, `ANTHROPIC_FOUNDRY_BASE_URL`) for Azure
authentication. Setting only `ANTHROPIC_API_KEY` / `ANTHROPIC_BASE_URL`
is not sufficient.

**Cause 3 — Wrong asyncio event loop:** On Windows, uvicorn with
`--reload` may use `SelectorEventLoop` which does not support
`asyncio.create_subprocess_exec()`. The SDK raises `NotImplementedError`
when trying to spawn the Claude Code CLI subprocess.

**Fix:** The `app/patches/__init__.py` module patches all three issues
automatically (Patches 1, 2, and 4). Make sure you are running the
**latest code** — restart the uvicorn server after pulling updates:

```bash
cd backend
uvicorn app.main:app --reload
```

Verify the patches are applied by checking the server log for:
```
[patches] Applying SDK patches...
[patches] Set WindowsProactorEventLoopPolicy (subprocess support)
[patches] Set ANTHROPIC_API_KEY from AZURE_FOUNDRY_API_KEY (len=84)
[patches] Set CLAUDE_CODE_USE_FOUNDRY=true + Foundry credentials
[patches] Applied Windows CLI patch: ...node.EXE ...cli.js (bypassing .CMD wrapper)
[patches] All patches applied.
```

> **Note:** These issues are Windows-only. Container deployments on
> Linux (Azure Container Apps, Docker) are not affected.

### Agents return empty responses (cost $0)

Agents connect successfully but produce no output.

**Cause:** When running inside a Claude Code editor session (VS Code), the
environment contains a local-proxy API key that doesn't work for child
processes.

**Fix:** Ensure `AZURE_FOUNDRY_API_KEY` and `AZURE_FOUNDRY_ENDPOINT` are
set in `backend/.env`. The patches module overrides the inherited proxy
credentials with the real ones and sets Foundry-specific auth env vars.
Check for these log lines:

```
[patches] Set ANTHROPIC_API_KEY from AZURE_FOUNDRY_API_KEY (len=84)
[patches] Set CLAUDE_CODE_USE_FOUNDRY=true + Foundry credentials
```

### "Failed to proxy" / ECONNREFUSED / "Review failed"

The frontend shows an error when submitting a review.

**Cause:** The backend server is not running, or the frontend is not
configured to reach it. The frontend calls the backend directly (not
through a Next.js proxy) because multi-agent reviews take 3-5 minutes.

**Fix:**

1. Ensure the backend is running:
   ```bash
   cd backend
   uvicorn app.main:app --reload
   ```

2. Ensure `frontend/.env.local` has the correct backend URL:
   ```
   NEXT_PUBLIC_API_BASE=http://localhost:8000/api
   ```

3. Restart the frontend dev server after changing `.env.local`:
   ```bash
   cd frontend
   npm run dev
   ```

### Port stuck after killing server (Windows)

After killing a server process, the port remains in LISTENING state with a
zombie PID.

**Cause:** Windows TCP socket lingering — the socket stays in the kernel
even after the process exits.

**Fix:** Wait 2-4 minutes for the socket to clear, or use a different port
(see above). Restarting the terminal or rebooting also clears zombie
sockets.

---

## References

- [Anthropic Healthcare MCP Marketplace](https://github.com/anthropics/healthcare)
- [Prior Auth Review Skill](https://github.com/anthropics/healthcare/tree/main/prior-auth-review-skill)
- [Build AI Agents with Claude Agent SDK and Microsoft Agent Framework](https://devblogs.microsoft.com/semantic-kernel/build-ai-agents-with-claude-agent-sdk-and-microsoft-agent-framework/)
- [Microsoft Agent Framework — Claude Agent](https://learn.microsoft.com/en-us/agent-framework/user-guide/agents/agent-types/anthropic-agent)
- [Azure Foundry Claude Models](https://learn.microsoft.com/en-us/azure/ai-foundry/foundry-models/how-to/use-foundry-models-claude)
- [Claude Prior Auth Review Tutorial](https://claude.com/resources/tutorials/how-to-use-the-prior-auth-review-sample-skill-with-claude-2ggy8)
- [Model Context Protocol (MCP)](https://modelcontextprotocol.io/)
- [Claude Agent SDK](https://platform.claude.com/docs/en/agent-sdk/overview)
- [Anthropic Agent Skills](https://platform.claude.com/docs/en/docs/agents-and-tools/agent-skills/overview)

---

## License

This project is for demonstration purposes. The Anthropic healthcare MCP
servers and skills are subject to Anthropic's terms of service.
