"""Compliance Validation Agent.

Validates documentation completeness against required checklists.
Identifies missing documents and generates specific additional-info requests.
Uses no tools — pure reasoning over the request data.
"""

from agent_framework_claude import ClaudeAgent

from app.agents._parse import parse_json_response

COMPLIANCE_INSTRUCTIONS = """\
You are a Compliance Validation Agent for prior authorization requests.
Your sole job is to check whether the submitted request contains all
required documentation and information. You do NOT assess clinical merit.

## Your Checklist

Verify the presence and validity of each item:

1. **Patient Information**: Name and date of birth present and non-empty
2. **Provider NPI**: NPI number present and is 10 digits
3. **Insurance ID**: Insurance ID provided (flag if missing — not blocking)
4. **Diagnosis Codes**: At least one ICD-10 code provided, format appears
   valid (letter + digits + optional decimal)
5. **Procedure Codes**: At least one CPT/HCPCS code provided
6. **Clinical Notes Presence**: Substantive clinical narrative provided
7. **Clinical Notes Quality**: Notes contain meaningful clinical detail
   (history, symptoms, exam findings, or test results) — not just a code
   list or single sentence

## Output Format

Return JSON with this exact structure:
{
    "checklist": [
        {"item": "Patient Information", "status": "complete|incomplete|missing", "detail": "..."},
        {"item": "Provider NPI", "status": "complete|incomplete|missing", "detail": "..."},
        {"item": "Insurance ID", "status": "complete|incomplete|missing", "detail": "..."},
        {"item": "Diagnosis Codes", "status": "complete|incomplete|missing", "detail": "..."},
        {"item": "Procedure Codes", "status": "complete|incomplete|missing", "detail": "..."},
        {"item": "Clinical Notes Presence", "status": "complete|incomplete|missing", "detail": "..."},
        {"item": "Clinical Notes Quality", "status": "complete|incomplete|missing", "detail": "..."}
    ],
    "overall_status": "complete|incomplete",
    "missing_items": ["list of items that are missing or incomplete"],
    "additional_info_requests": ["specific requests for what is needed"]
}

## Rules

- You have NO tools. Analyze the request data provided in the prompt.
- Be specific in additional_info_requests — say exactly what document or
  datum is missing.
- If clinical notes are present but thin (< 2 sentences), mark Clinical
  Notes Quality as "incomplete".
- Do NOT assess medical necessity or clinical merit — another agent does that.
- Do NOT verify whether codes are valid in databases — another agent does that.
"""


async def create_compliance_agent() -> ClaudeAgent:
    """Create the Compliance Validation Agent (no tools)."""
    return ClaudeAgent(
        instructions=COMPLIANCE_INSTRUCTIONS,
        default_options={
            "permission_mode": "bypassPermissions",
        },
    )


async def run_compliance_review(request_data: dict) -> dict:
    """Run compliance validation on a prior auth request.

    Args:
        request_data: Dict with patient_name, patient_dob, provider_npi,
            diagnosis_codes, procedure_codes, clinical_notes, insurance_id.

    Returns:
        Dict with checklist, overall_status, missing_items,
        additional_info_requests.
    """
    agent = await create_compliance_agent()

    prompt = f"""Validate the documentation completeness of this prior authorization request.

--- PRIOR AUTHORIZATION REQUEST ---

Patient Name: {request_data['patient_name']}
Patient DOB: {request_data['patient_dob']}
Provider NPI: {request_data['provider_npi']}
Insurance ID: {request_data.get('insurance_id') or 'Not provided'}

Diagnosis Codes (ICD-10):
{chr(10).join(f'  - {code}' for code in request_data['diagnosis_codes'])}

Procedure Codes (CPT):
{chr(10).join(f'  - {code}' for code in request_data['procedure_codes'])}

Clinical Notes:
{request_data['clinical_notes']}

--- END REQUEST ---

Check each item on your checklist and return your structured JSON assessment."""

    async with agent:
        response = await agent.run(prompt)

    return parse_json_response(response)
