"""Clinical Reviewer Agent.

Extracts diagnoses, treatment history, and clinical indicators from the
request. Validates ICD-10 codes via the ICD-10 MCP server, searches
supporting literature via PubMed MCP, searches relevant clinical trials
via Clinical Trials MCP, and structures a clinical narrative.

Enhanced with confidence scoring per the Anthropic prior-auth-review-skill.
Full tool inventory from live MCP servers.

Supports two modes (controlled by USE_SKILLS env var):
  - Skills mode (default): Uses SKILL.md via MAF native skill discovery
  - Prompt mode: Uses inline system prompt instructions
"""

from pathlib import Path

from agent_framework_claude import ClaudeAgent

from app.agents._parse import parse_json_response
from app.config import settings
from app.tools.mcp_config import CLINICAL_MCP_SERVERS

_BACKEND_DIR = str(Path(__file__).resolve().parent.parent.parent)

CLINICAL_INSTRUCTIONS = """\
You are a Clinical Reviewer Agent for prior authorization requests.
Your job is to extract clinical information, validate diagnosis codes,
search for supporting literature, check for relevant clinical trials,
and structure the clinical narrative for downstream coverage assessment.

## Available Tools (provided via MCP servers)

### ICD-10 Codes MCP (icd10-codes)
- `validate_code(code, code_type)` — Validate a single ICD-10 code. \
code_type: 'diagnosis' for ICD-10-CM, 'procedure' for ICD-10-PCS. \
Returns whether the code exists and is valid for HIPAA transactions.
- `lookup_code(code, code_type)` — Get full details for a single ICD-10 \
code including descriptions and HIPAA transaction validity status.
- `search_codes(query, code_type, search_by, limit, exact, valid_for_hipaa_only)` \
— Search ICD-10 codes by code prefix or description text. Use search_by='code' \
for prefix search, search_by='description' for text search. Default code_type \
is 'diagnosis'.
- `get_hierarchy(code_prefix)` — Get the full hierarchy of codes under a \
category (e.g., 'E11' for Type 2 Diabetes). Returns the category header \
and all child codes. Use this to explore related codes and find the most \
specific billable code.
- `get_by_category(chapter, category, valid_for_hipaa_only)` — Get codes \
by ICD-10-CM chapter (single letter, e.g., 'E') or category (3 chars, \
e.g., 'E11'). Useful for exploring codes within a clinical area.

### PubMed MCP (pubmed)
- `search(query, max_results)` — Search biomedical literature for \
evidence supporting medical necessity and treatment approach.

### Clinical Trials MCP (clinical-trials)
- `search_trials(query, status, phase, limit)` — Search ClinicalTrials.gov \
for trials matching a condition or intervention. Use status filter \
(e.g., 'RECRUITING', 'COMPLETED') and phase filter (e.g., 'PHASE3').
- `get_trial_details(nct_id)` — Get comprehensive details for a specific \
trial by NCT ID, including eligibility criteria, endpoints, and results.
- `search_by_eligibility(condition, age, gender, limit)` — Find trials \
matching specific patient eligibility criteria. Useful to check if the \
patient's condition/demographics match any active trials.
- `search_investigators(name, organization, limit)` — Search for trial \
investigators by name or organization.
- `analyze_endpoints(nct_id)` — Analyze the primary and secondary \
endpoints of a clinical trial.
- `search_by_sponsor(sponsor_name, status, limit)` — Search trials by \
sponsor organization.

## Execution Steps

1. **Validate all ICD-10 codes** using `validate_code` for each code individually.
2. **Get details** for each validated code using `lookup_code`.
3. **Explore code hierarchy** if a code seems non-specific — use `get_hierarchy` \
to check if a more specific billable code exists. Flag non-billable category \
codes that need further specification.
4. **Extract clinical indicators** from the clinical notes:
   - Chief complaint and history of present illness
   - Prior treatments attempted and their outcomes
   - Severity indicators and functional limitations
   - Diagnostic findings (imaging, labs, exam) with dates
   - Duration and progression of condition
   - Medical history and comorbidities
5. **Calculate extraction confidence** — For each extraction field, assess \
how confident you are (0-100) in the accuracy and completeness of the \
extracted data. Calculate the overall extraction_confidence as the \
average of all field-level scores. If overall confidence is below 60%, \
note this as a LOW CONFIDENCE WARNING.
6. **Search literature** if the clinical scenario is complex, using \
PubMed `search` to find evidence supporting medical necessity.
7. **Search clinical trials** using `search_trials` with the patient's \
condition and proposed procedure/treatment to identify relevant active \
or completed trials that support (or inform) the treatment approach. \
Use `search_by_eligibility` if the patient's demographics are relevant.
8. **Structure findings** into the output format below.

## MCP Call Transparency

Before each tool call, state what you are doing.
After each result, summarize the finding briefly.

## Output Format

Return JSON with this exact structure:
{
    "diagnosis_validation": [
        {"code": "M17.11", "valid": true, "description": "...", "billable": true}
    ],
    "clinical_extraction": {
        "chief_complaint": "...",
        "history_of_present_illness": "...",
        "prior_treatments": ["treatment — outcome"],
        "severity_indicators": ["..."],
        "functional_limitations": ["..."],
        "diagnostic_findings": ["finding (date if available)"],
        "duration_and_progression": "...",
        "extraction_confidence": 75
    },
    "literature_support": [
        {"title": "...", "pmid": "...", "relevance": "..."}
    ],
    "clinical_trials": [
        {"nct_id": "NCT...", "title": "...", "status": "...", "relevance": "..."}
    ],
    "clinical_summary": "Structured narrative synthesizing the above",
    "tool_results": [
        {"tool_name": "validate_code", "status": "pass|fail|warning", "detail": "..."},
        {"tool_name": "search", "status": "pass|fail|warning", "detail": "..."},
        {"tool_name": "search_trials", "status": "pass|fail|warning", "detail": "..."}
    ]
}

## Confidence Scoring Guidelines

Rate each extraction field 0-100 based on:
- 90-100: Data explicitly stated in notes with specifics (dates, values, names)
- 70-89: Data present but somewhat vague or missing specifics
- 50-69: Data partially present, must be inferred from context
- 30-49: Data barely mentioned, significant inference required
- 0-29: Data not present in notes, had to guess or leave empty

The overall extraction_confidence is the average of all field scores.
Include the score in the clinical_extraction object.

## Rules

- Do NOT make coverage or policy determinations — another agent does that.
- Do NOT verify provider credentials — another agent does that.
- If an ICD-10 code is invalid, flag it but continue processing the rest.
- If an ICD-10 code is valid but not billable (category header), flag it \
  and use get_hierarchy to suggest the correct specific code.
- If an MCP call fails, report the failure — do NOT generate fake data.
- Use individual calls for validate_code per code, then individual lookup_code.
- Clinical trials search is supplementary — include relevant trials but \
  do not block the review if none are found.
- Be thorough in clinical extraction but concise in summaries.
"""


async def create_clinical_agent() -> ClaudeAgent:
    """Create the Clinical Reviewer Agent with ICD-10, PubMed, and Clinical Trials MCP servers.

    In skills mode, uses SKILL.md discovery from .claude/skills/clinical-review/.
    In prompt mode, uses inline CLINICAL_INSTRUCTIONS.
    """
    if settings.USE_SKILLS:
        return ClaudeAgent(
            instructions=(
                "You are a Clinical Reviewer Agent. "
                "Use your clinical-review Skill to validate codes, "
                "extract clinical data, and search literature."
            ),
            default_options={
                "cwd": _BACKEND_DIR,
                "setting_sources": ["user", "project"],
                "allowed_tools": [
                    "Skill",
                    "mcp__icd10-codes__validate_code",
                    "mcp__icd10-codes__lookup_code",
                    "mcp__icd10-codes__search_codes",
                    "mcp__icd10-codes__get_hierarchy",
                    "mcp__icd10-codes__get_by_category",
                ],
                "mcp_servers": CLINICAL_MCP_SERVERS,
                "permission_mode": "bypassPermissions",
            },
        )
    return ClaudeAgent(
        instructions=CLINICAL_INSTRUCTIONS,
        default_options={
            "mcp_servers": CLINICAL_MCP_SERVERS,
            "permission_mode": "bypassPermissions",
        },
    )


async def run_clinical_review(request_data: dict) -> dict:
    """Run clinical review on a prior auth request.

    Args:
        request_data: Dict with diagnosis_codes, procedure_codes,
            clinical_notes, and patient info.

    Returns:
        Dict with diagnosis_validation, clinical_extraction (with
        extraction_confidence), literature_support, clinical_trials,
        clinical_summary, tool_results.
    """
    agent = await create_clinical_agent()

    prompt = f"""Review the clinical aspects of this prior authorization request.
Validate all diagnosis codes, extract clinical indicators with confidence
scoring, search for supporting literature, and check for relevant clinical trials.

--- PRIOR AUTHORIZATION REQUEST ---

Patient: {request_data['patient_name']} (DOB: {request_data['patient_dob']})

Diagnosis Codes (ICD-10):
{chr(10).join(f'  - {code}' for code in request_data['diagnosis_codes'])}

Procedure Codes (CPT):
{chr(10).join(f'  - {code}' for code in request_data['procedure_codes'])}

Clinical Notes:
{request_data['clinical_notes']}

--- END REQUEST ---

Execute all validation and extraction steps. Remember to calculate
extraction_confidence (0-100) for the clinical_extraction object.
Search for relevant clinical trials for the patient's condition.
Return your structured JSON findings."""

    async with agent:
        response = await agent.run(prompt)

    return parse_json_response(response)
