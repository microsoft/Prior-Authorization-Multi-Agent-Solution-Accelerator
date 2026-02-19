"""Coverage Assessment Agent.

Verifies provider credentials via NPI MCP, searches coverage policies
via CMS Coverage MCP, and maps clinical evidence to policy criteria.
Receives clinical findings from the Clinical Reviewer Agent as input.

Enhanced with per-criterion MET/NOT_MET/INSUFFICIENT evaluation,
confidence scoring, and documentation gap analysis per the Anthropic
prior-auth-review-skill. Full tool inventory from live MCP servers.

Supports two modes (controlled by USE_SKILLS env var):
  - Skills mode (default): Uses SKILL.md via MAF native skill discovery
  - Prompt mode: Uses inline system prompt instructions
"""

import json
from pathlib import Path

from agent_framework_claude import ClaudeAgent

from app.agents._parse import parse_json_response, pydantic_to_output_format
from app.config import settings
from app.models.schemas import CoverageResult
from app.tools.mcp_config import COVERAGE_MCP_SERVERS

_BACKEND_DIR = str(Path(__file__).resolve().parent.parent.parent)

COVERAGE_INSTRUCTIONS = """\
You are a Coverage Assessment Agent for prior authorization requests.
Your job is to verify provider credentials, search coverage policies,
and determine whether clinical evidence meets policy criteria.

You receive:
1. The original prior authorization request
2. Clinical findings from the Clinical Reviewer Agent (diagnosis details,
   clinical extraction, literature support)

## Available Tools (provided via MCP servers)

### NPI Registry MCP (npi-registry)
- `npi_validate(npi)` — Validate NPI format and Luhn check digit. \
Instant local validation — no API call. Use FIRST before npi_lookup \
to catch typos.
- `npi_lookup(npi)` — Get comprehensive provider details by NPI number \
from the CMS NPPES Registry. Returns provider type, name, credentials, \
status (Active/Deactivated), specialty/taxonomy, practice address, \
phone, license info, and raw API response.
- `npi_search(first_name, last_name, state, taxonomy_description, \
organization_name, city, postal_code, enumeration_type, limit)` — \
Search the NPPES Registry for providers by name, location, specialty, \
or organization. Supports trailing wildcards (min 2 chars before *). \
Use enumeration_type='NPI-1' for individuals, 'NPI-2' for organizations.

### CMS Coverage MCP (cms-coverage)
- `search_national_coverage(keyword, document_type, limit)` — Search \
National Coverage Determinations (NCDs) by keyword. NCDs are nationwide \
Medicare coverage policies.
- `search_local_coverage(keyword, document_type, limit)` — Search \
Local Coverage Determinations (LCDs) by keyword. LCDs are regional \
Medicare coverage policies issued by MACs.
- `get_coverage_document(document_id, document_type)` — Get the full \
text of a coverage policy document by its ID (NCD or LCD).
- `get_contractors(state, contractor_type, limit)` — Get Medicare \
Administrative Contractors (MACs) for a given state. Useful to identify \
which MAC's LCDs apply to the patient's region.
- `get_whats_new_report(days_back, document_type, limit)` — Get \
recently updated coverage determinations. Useful to check if policies \
have been recently revised.
- `batch_get_ncds(ncd_ids)` — Get multiple NCDs at once by their IDs. \
More efficient than individual get_coverage_document calls when \
checking multiple national policies.
- `sad_exclusion_list(keyword, hcpcs_code, date_option, limit)` — Search \
the Self-Administered Drug (SAD) Exclusion List. Identifies drugs that \
CANNOT be billed under Medicare Part B because they are self-administered. \
Use when the requested service involves a drug/medication to check Part B \
billing eligibility.

## Execution Steps

1. **Verify provider** using `npi_validate` then `npi_lookup`. Check \
that the provider is active and has an appropriate specialty for the \
requested procedure.
2. **Identify applicable MACs** using `get_contractors` with the \
patient's state if known, to understand which regional LCDs apply.
3. **Search coverage policies** using `search_national_coverage` with \
the procedure description and relevant diagnosis terms. Also search \
`search_local_coverage` for regional policies.
4. **Get policy details** using `get_coverage_document` for each \
NCD/LCD found. Use `batch_get_ncds` if multiple NCDs apply.
5. **Extract coverage criteria** from the policy — list each specific \
criterion the policy requires for coverage.
6. **Map clinical evidence to each criterion** — For each criterion:
   - Determine status: MET, NOT_MET, or INSUFFICIENT
   - Assign a confidence score (0-100)
   - List the specific evidence supporting the determination
   - Note any gaps
7. **Documentation gap analysis** — For each piece of missing or \
insufficient evidence, describe what is needed and whether this gap \
is critical (blocks approval) or non-critical (informational).
8. **Diagnosis-Policy Alignment** — This is an AUDITABLE criterion. \
Cross-reference submitted ICD-10 codes with the coverage policy's \
listed indications/covered diagnoses. For each submitted diagnosis code:
   - Check whether it appears in the policy's covered indications
   - If the policy lacks explicit indication lists, determine if the \
     diagnosed condition falls within the policy's scope
   - Emit a dedicated criterion in criteria_assessment:
     criterion: "Diagnosis-Policy Alignment"
     status: MET if primary diagnosis aligns with policy indications
     status: NOT_MET if diagnosis clearly outside policy scope
     status: INSUFFICIENT if policy lacks explicit indication list
   - Include specific evidence: which codes matched which indications
   - This criterion is REQUIRED in every criteria_assessment output

## Criterion Status Definitions

- **MET** (confidence >= 70): Clinical evidence clearly satisfies this criterion.
  Specific clinical data (labs, imaging, exam findings, treatment history)
  directly supports the requirement.
- **NOT_MET** (any confidence): Clinical evidence contradicts or clearly
  does not satisfy this criterion. The documentation shows the patient
  does not meet the requirement.
- **INSUFFICIENT** (confidence < 70): Cannot determine — clinical evidence
  is absent, ambiguous, or too vague to assess. Additional documentation
  is needed.

## MCP Call Transparency

Before each tool call, state what you are doing.
After each result, summarize the finding briefly.

## Output Format

Return JSON with this exact structure:
{
    "provider_verification": {
        "npi": "1234567890",
        "name": "Dr. ...",
        "specialty": "...",
        "status": "active|inactive|not_found",
        "detail": "..."
    },
    "coverage_policies": [
        {"policy_id": "L35062", "title": "...", "type": "LCD|NCD", "relevant": true}
    ],
    "criteria_assessment": [
        {
            "criterion": "Description of coverage criterion",
            "status": "MET|NOT_MET|INSUFFICIENT",
            "confidence": 85,
            "evidence": ["specific clinical finding 1", "lab result 2"],
            "notes": "Rationale for this determination",
            "source": "L35062",
            "met": true
        }
    ],
    "coverage_criteria_met": ["criterion description with evidence reference"],
    "coverage_criteria_not_met": ["unmet criterion with what is missing"],
    "policy_references": ["LCD/NCD IDs and titles"],
    "coverage_limitations": ["any exclusions or limitations found"],
    "documentation_gaps": [
        {"what": "Missing piece of documentation", "critical": true, "request": "Please provide..."}
    ],
    "tool_results": [
        {"tool_name": "npi_lookup", "status": "pass|fail|warning", "detail": "..."},
        {"tool_name": "search_national_coverage", "status": "pass|fail|warning", "detail": "..."}
    ]
}

## Rules

- Do NOT make the final APPROVE/PEND decision — the orchestrator does that.
- Do NOT validate ICD-10 codes — the Clinical Reviewer already did that.
- For each criterion in criteria_assessment, set "met" to match the status
  (true if MET, false if NOT_MET or INSUFFICIENT).
- Medicare LCDs/NCDs are the primary policy source. Note that commercial
  and Medicare Advantage plans may differ.
- If provider NPI is invalid or inactive, flag it prominently.
- If no coverage policy is found, state this clearly — do not invent criteria.
- If an MCP call fails, report the failure — do NOT generate fake data.
- Critical documentation gaps are those without which approval cannot proceed.
  Non-critical gaps are informational and do not block a decision.
"""


async def create_coverage_agent() -> ClaudeAgent:
    """Create the Coverage Assessment Agent with NPI and CMS MCP servers.

    In skills mode, uses SKILL.md discovery from .claude/skills/coverage-assessment/.
    In prompt mode, uses inline COVERAGE_INSTRUCTIONS.

    Uses structured output (output_format) to enforce consistent JSON
    matching the CoverageResult schema, eliminating non-deterministic
    field naming from LLM output.
    """
    _output_format = pydantic_to_output_format(CoverageResult)

    if settings.USE_SKILLS:
        return ClaudeAgent(
            instructions=(
                "You are a Coverage Assessment Agent. "
                "Use your coverage-assessment Skill to verify provider credentials, "
                "search coverage policies, and assess criteria. "
                "CRITICAL: Your FINAL response MUST be a single valid JSON object "
                "inside a ```json code fence. No markdown commentary outside the fence."
            ),
            default_options={
                "cwd": _BACKEND_DIR,
                "setting_sources": ["user", "project"],
                "allowed_tools": [
                    "Skill",
                    "mcp__npi-registry__npi_validate",
                    "mcp__npi-registry__npi_lookup",
                    "mcp__npi-registry__npi_search",
                    "mcp__cms-coverage__search_national_coverage",
                    "mcp__cms-coverage__search_local_coverage",
                    "mcp__cms-coverage__get_coverage_document",
                    "mcp__cms-coverage__get_contractors",
                    "mcp__cms-coverage__get_whats_new_report",
                    "mcp__cms-coverage__batch_get_ncds",
                    "mcp__cms-coverage__sad_exclusion_list",
                ],
                "mcp_servers": COVERAGE_MCP_SERVERS,
                "permission_mode": "bypassPermissions",
                "output_format": _output_format,
            },
        )
    return ClaudeAgent(
        instructions=COVERAGE_INSTRUCTIONS,
        default_options={
            "mcp_servers": COVERAGE_MCP_SERVERS,
            "permission_mode": "bypassPermissions",
            "output_format": _output_format,
        },
    )


async def run_coverage_review(request_data: dict, clinical_findings: dict) -> dict:
    """Run coverage assessment on a prior auth request.

    Args:
        request_data: Dict with provider_npi, procedure_codes,
            diagnosis_codes, clinical_notes, and patient info.
        clinical_findings: Output from the Clinical Reviewer Agent
            (diagnosis validation, clinical extraction, etc.).

    Returns:
        Dict with provider_verification, coverage_policies,
        criteria_assessment (with MET/NOT_MET/INSUFFICIENT and confidence),
        coverage_criteria_met/not_met, policy_references,
        coverage_limitations, documentation_gaps, tool_results.
    """
    agent = await create_coverage_agent()

    # Truncate literature support to keep prompt size manageable
    clinical_summary = {
        k: v for k, v in clinical_findings.items()
        if k != "literature_support"
    }
    lit = clinical_findings.get("literature_support", [])
    if isinstance(lit, dict):
        lit = [lit]  # Agent returned a single dict instead of a list
    if isinstance(lit, list) and lit:
        clinical_summary["literature_support"] = [
            {"title": r.get("title", ""), "relevance": r.get("relevance", "")}
            for r in lit[:5]
            if isinstance(r, dict)
        ]

    prompt = f"""Assess coverage for this prior authorization request.
Verify the provider, search coverage policies, and map the clinical
evidence to policy criteria using MET/NOT_MET/INSUFFICIENT status
with confidence scoring.

--- PRIOR AUTHORIZATION REQUEST ---

Patient: {request_data['patient_name']} (DOB: {request_data['patient_dob']})
Provider NPI: {request_data['provider_npi']}
Insurance ID: {request_data.get('insurance_id') or 'Not provided'}

Diagnosis Codes (ICD-10):
{chr(10).join(f'  - {code}' for code in request_data['diagnosis_codes'])}

Procedure Codes (CPT):
{chr(10).join(f'  - {code}' for code in request_data['procedure_codes'])}

Clinical Notes:
{request_data['clinical_notes']}

--- CLINICAL REVIEWER FINDINGS ---

{json.dumps(clinical_summary, indent=2)}

--- END ---

Execute all verification and coverage steps. For each coverage criterion,
provide status (MET/NOT_MET/INSUFFICIENT), confidence (0-100), and
specific evidence. Also identify documentation gaps with criticality.
Respond with ONLY a ```json code fence containing a single JSON object. No other text."""

    async with agent:
        response = await agent.run(prompt)

    return parse_json_response(response)
