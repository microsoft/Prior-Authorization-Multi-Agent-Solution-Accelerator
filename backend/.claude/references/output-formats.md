# Output Format Schemas

This document defines the JSON output schema for each agent in the prior
authorization review pipeline. All agents MUST return valid JSON matching
their respective schema. The orchestrator Python code parses these outputs
to build the final review response and audit trail.

---

## 1. Compliance Agent Output

```json
{
    "checklist": [
        {
            "item": "Patient Information",
            "status": "complete|incomplete|missing",
            "detail": "Name and DOB confirmed present"
        },
        {
            "item": "Provider NPI",
            "status": "complete|incomplete|missing",
            "detail": "10-digit NPI provided: 1234567890"
        },
        {
            "item": "Insurance ID",
            "status": "complete|incomplete|missing",
            "detail": "Insurance ID provided or missing (non-blocking)"
        },
        {
            "item": "Diagnosis Codes",
            "status": "complete|incomplete|missing",
            "detail": "N ICD-10 codes provided with valid format"
        },
        {
            "item": "Procedure Codes",
            "status": "complete|incomplete|missing",
            "detail": "N CPT/HCPCS codes provided"
        },
        {
            "item": "Clinical Notes Presence",
            "status": "complete|incomplete|missing",
            "detail": "Substantive clinical narrative found"
        },
        {
            "item": "Clinical Notes Quality",
            "status": "complete|incomplete|missing",
            "detail": "Notes contain history, findings, and clinical reasoning"
        },
        {
            "item": "Insurance Plan Type",
            "status": "complete|incomplete|missing",
            "detail": "Plan identified as Medicare/Medicaid/Commercial/MA"
        }
    ],
    "overall_status": "complete|incomplete",
    "missing_items": ["list of items with status incomplete or missing"],
    "additional_info_requests": ["specific request for each missing item"]
}
```

**Field rules:**
- `status` must be one of: `complete`, `incomplete`, `missing`
- `overall_status` is `complete` only if ALL items are `complete` (except Insurance ID which is non-blocking)
- `additional_info_requests` must be specific -- say exactly what document or datum is needed
- Insurance Plan Type is informational -- does not block `overall_status`

---

## 2. Clinical Agent Output

```json
{
    "diagnosis_validation": [
        {
            "code": "M17.11",
            "valid": true,
            "description": "Primary osteoarthritis, right knee",
            "billable": true,
            "hierarchy_note": "optional -- note if non-billable code has specific children"
        }
    ],
    "procedure_validation": [
        {
            "code": "27447",
            "valid": true,
            "description": "Total knee replacement",
            "source": "orchestrator_preflight|unverified"
        }
    ],
    "clinical_extraction": {
        "chief_complaint": "Right knee pain with progressive functional limitation",
        "history_of_present_illness": "...",
        "prior_treatments": [
            "Physical therapy x 6 weeks -- partial improvement",
            "NSAIDs x 3 months -- inadequate relief"
        ],
        "severity_indicators": [
            "Pain rated 8/10",
            "Unable to walk > 1 block"
        ],
        "functional_limitations": [
            "Cannot climb stairs",
            "Requires assistive device for ambulation"
        ],
        "diagnostic_findings": [
            "X-ray shows bone-on-bone contact (2024-01-15)",
            "MRI confirms Grade IV cartilage loss (2024-02-01)"
        ],
        "duration_and_progression": "Progressive worsening over 18 months",
        "extraction_confidence": 82
    },
    "literature_support": [
        {
            "title": "Effectiveness of total knee arthroplasty...",
            "pmid": "12345678",
            "relevance": "Supports TKA for Grade IV OA with failed conservative treatment"
        }
    ],
    "clinical_trials": [
        {
            "nct_id": "NCT12345678",
            "title": "Novel approaches to knee OA management",
            "status": "RECRUITING",
            "relevance": "Active trial for similar patient population"
        }
    ],
    "clinical_summary": "Structured narrative synthesizing all findings above",
    "tool_results": [
        {
            "tool_name": "validate_code",
            "status": "pass|fail|warning",
            "detail": "M17.11 valid and billable"
        }
    ]
}
```

**Field rules:**
- `diagnosis_validation` must include one entry per ICD-10 code submitted
- `procedure_validation` includes CPT/HCPCS codes noted by the agent; format validation is done by the orchestrator pre-flight step (`cpt_validation.py`)
- `extraction_confidence` is 0-100 (average of per-field scores)
- `literature_support` and `clinical_trials` may be empty arrays if none found
- `tool_results` tracks every MCP call made

---

## 3. Coverage Agent Output

```json
{
    "provider_verification": {
        "npi": "1234567890",
        "name": "Dr. Jane Smith",
        "specialty": "Orthopedic Surgery",
        "status": "active|inactive|not_found",
        "detail": "Provider verified via NPI MCP -- active license in NY"
    },
    "coverage_policies": [
        {
            "policy_id": "L35062",
            "title": "Total Knee Arthroplasty",
            "type": "LCD|NCD",
            "relevant": true
        }
    ],
    "criteria_assessment": [
        {
            "criterion": "Description of the coverage criterion",
            "status": "MET|NOT_MET|INSUFFICIENT",
            "confidence": 85,
            "evidence": [
                "X-ray shows bone-on-bone contact",
                "Failed 3 months of conservative treatment"
            ],
            "notes": "Rationale for this determination",
            "source": "L35062",
            "met": true
        },
        {
            "criterion": "Diagnosis-Policy Alignment",
            "status": "MET|NOT_MET|INSUFFICIENT",
            "confidence": 90,
            "evidence": [
                "M17.11 (Primary OA right knee) matches policy covered indication"
            ],
            "notes": "Primary diagnosis aligns with LCD L35062 covered diagnoses",
            "source": "L35062",
            "met": true
        }
    ],
    "coverage_criteria_met": [
        "Failed conservative treatment -- documented PT and NSAIDs"
    ],
    "coverage_criteria_not_met": [
        "BMI documentation -- patient BMI not found in clinical notes"
    ],
    "policy_references": [
        "L35062 - Total Knee Arthroplasty (LCD)"
    ],
    "coverage_limitations": [
        "Any applicable exclusions or limitations"
    ],
    "documentation_gaps": [
        {
            "what": "Patient BMI",
            "critical": false,
            "request": "Please provide patient's current BMI measurement"
        }
    ],
    "tool_results": [
        {
            "tool_name": "npi_lookup",
            "status": "pass|fail|warning",
            "detail": "Provider verified -- active orthopedic surgeon"
        }
    ]
}
```

**Field rules:**
- `criteria_assessment` MUST include a "Diagnosis-Policy Alignment" entry
- `status` must be one of: `MET`, `NOT_MET`, `INSUFFICIENT`
- `met` is `true` if status is `MET`, `false` otherwise
- `documentation_gaps` classified as `critical` (blocks approval) or non-critical (informational)
- `provider_verification.status` must be one of: `active`, `inactive`, `not_found`

---

## 4. Synthesis Agent Output

```json
{
    "recommendation": "approve|pend_for_review",
    "confidence": 0.82,
    "confidence_level": "HIGH|MEDIUM|LOW",
    "summary": "Brief 2-3 sentence synthesis of all agent findings",
    "clinical_rationale": "Detailed rationale citing evidence from Clinical Reviewer and Coverage Agent. References MET/NOT_MET/INSUFFICIENT statuses and confidence levels.",
    "decision_gate": "gate_1_provider|gate_2_codes|gate_3_necessity|approved",
    "coverage_criteria_met": [
        "Failed conservative treatment -- documented PT and NSAIDs (Coverage Agent, confidence 85%)"
    ],
    "coverage_criteria_not_met": [
        "BMI documentation -- not found in clinical notes (Coverage Agent)"
    ],
    "missing_documentation": [
        "Combined list from Compliance and Coverage agents"
    ],
    "policy_references": [
        "L35062 - Total Knee Arthroplasty (LCD)"
    ],
    "criteria_summary": "5 of 6 criteria MET",
    "audit_trail": {
        "gates_evaluated": ["gate_1_provider", "gate_2_codes", "gate_3_necessity"],
        "gate_results": {
            "gate_1_provider": "PASS",
            "gate_2_codes": "PASS",
            "gate_3_necessity": "PASS"
        },
        "confidence_components": {
            "criteria_weight": 0.4,
            "criteria_score": 0.85,
            "extraction_weight": 0.3,
            "extraction_score": 0.82,
            "compliance_weight": 0.2,
            "compliance_score": 1.0,
            "policy_weight": 0.1,
            "policy_score": 1.0
        },
        "agents_consulted": ["compliance", "clinical", "coverage"]
    },
    "disclaimer": "AI-assisted draft. Coverage policies reflect Medicare LCDs/NCDs only. If this review is for a commercial or Medicare Advantage plan, payer-specific policies may differ. Human clinical review required before final determination."
}
```

**Field rules:**
- `recommendation` must be `approve` or `pend_for_review` (LENIENT mode -- never `deny`)
- `confidence` is 0.0 to 1.0, computed using the weighted formula in rubric.md
- `decision_gate` indicates where the decision was made:
  - `approved` if all gates passed
  - `gate_1_provider`, `gate_2_codes`, or `gate_3_necessity` if PEND at that gate
- `audit_trail` breaks down the confidence computation for transparency
- `disclaimer` is mandatory in every output
- Do NOT include `tool_results` -- those come from sub-agents
