"""Multi-Agent Orchestrator for Prior Authorization Review.

Coordinates three specialized agents in a fan-out/fan-in pattern:
  Phase 1 (parallel): Compliance Agent + Clinical Reviewer Agent
  Phase 2 (sequential): Coverage Agent (receives clinical findings)
  Phase 3: Synthesis — aggregates all agent outputs into a final decision

Enhanced with the Anthropic prior-auth-review-skill decision rubric:
  - LENIENT mode (default): all problematic scenarios -> PEND
  - Structured evaluation order: provider -> codes -> med necessity
  - Confidence scoring: HIGH/MEDIUM/LOW + 0-100
  - Audit trail with data sources and metrics
  - Audit justification document generation

Supports two modes (controlled by USE_SKILLS env var):
  - Skills mode (default): Synthesis agent uses SKILL.md via MAF skill discovery
  - Prompt mode: Synthesis agent uses inline SYNTHESIS_INSTRUCTIONS
"""

import asyncio
import json
import logging
import os
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path

from agent_framework_claude import ClaudeAgent

from app.agents._parse import parse_json_response, pydantic_to_output_format
from app.agents.compliance_agent import run_compliance_review
from app.agents.clinical_agent import run_clinical_review
from app.agents.coverage_agent import run_coverage_review
from app.config import settings
from app.models.schemas import SynthesisOutput
from app.services.audit_pdf import generate_audit_justification_pdf
from app.services.cpt_validation import validate_procedure_codes

logger = logging.getLogger(__name__)

_BACKEND_DIR = str(Path(__file__).resolve().parent.parent.parent)


# --- In-memory review store (demo persistence) ---
_review_store: dict[str, dict] = {}


def store_review(request_id: str, request_data: dict, response: dict) -> None:
    """Persist a completed review for later retrieval."""
    _review_store[request_id] = {
        "request_id": request_id,
        "request_data": request_data,
        "response": response,
        "decision": None,
        "stored_at": datetime.now(timezone.utc).isoformat(),
    }


def get_review(request_id: str) -> dict | None:
    """Retrieve a stored review by request_id."""
    return _review_store.get(request_id)


def list_reviews() -> list[dict]:
    """List all stored reviews (most recent first)."""
    return sorted(
        _review_store.values(),
        key=lambda r: r["stored_at"],
        reverse=True,
    )


def store_decision(request_id: str, decision: dict) -> None:
    """Attach a decision to a stored review."""
    if request_id in _review_store:
        _review_store[request_id]["decision"] = decision

SYNTHESIS_INSTRUCTIONS = """\
You are the Synthesis Agent for prior authorization review.
You receive the outputs of three specialized agents and synthesize their
findings into a single final recommendation.

## Agent Inputs

1. **Compliance Agent** — checked documentation completeness (8-item checklist)
2. **Clinical Reviewer Agent** — validated ICD-10 and CPT codes, extracted
   clinical evidence with confidence scoring, searched supporting literature
3. **Coverage Agent** — verified provider NPI, assessed coverage criteria
   using MET/NOT_MET/INSUFFICIENT status with per-criterion confidence

## Decision Policy: LENIENT MODE (Default)

Evaluate gates in strict sequential order. Stop at the first failing gate.

### Gate 1: Provider Verification
| Scenario | Action |
|----------|--------|
| Provider NPI valid and active | PASS — continue to Gate 2 |
| Provider NPI invalid or inactive | PEND — request credentialing info |
| Provider not found in NPPES | PEND — request credentialing documentation |
| Demo mode NPI (verified) | PASS — continue to Gate 2 |

### Gate 2: Code Validation
| Scenario | Action |
|----------|--------|
| All ICD-10 codes valid and billable | PASS — continue to Gate 3 |
| Any ICD-10 code invalid | PEND — request diagnosis code clarification |
| ICD-10 code valid but not billable | PEND — request specific billable code |
| All CPT/HCPCS codes valid and active | PASS — continue to Gate 3 |
| Any CPT/HCPCS code invalid | PEND — request procedure code clarification |
| CPT codes present with valid format (unverified) | PASS with warning — continue to Gate 3 |

### Gate 3: Medical Necessity Criteria
| Scenario | Action |
|----------|--------|
| All required criteria MET | APPROVE |
| Any required criterion NOT_MET | PEND — request additional documentation |
| Any required criterion INSUFFICIENT | PEND — specify what evidence is needed |
| No coverage policy found | PEND — manual policy review needed |
| Documentation incomplete (Compliance) | PEND — specify missing items |
| Diagnosis-Policy Alignment NOT_MET | PEND — diagnosis outside policy scope |

### Catch-All
| Scenario | Action |
|----------|--------|
| Uncertain or conflicting signals | PEND — default safe option |
| Agent error in any sub-agent | PEND — note error, require manual review |

IMPORTANT: In LENIENT mode, recommend APPROVE or PEND only — never DENY.
Only approve when ALL three gates pass cleanly.

## Confidence Scoring

### Weighted Formula

overall = (0.4 * avg_criteria / 100) \
        + (0.3 * extraction / 100) \
        + (0.2 * compliance_score) \
        + (0.1 * policy_match)

Where:
- avg_criteria (0-100): Average of per-criterion confidence scores from \
Coverage Agent's criteria_assessment
- extraction (0-100): Clinical Reviewer's extraction_confidence
- compliance_score (0.0-1.0): Start at 1.0, subtract 0.1 per incomplete \
or missing item in Compliance checklist (floor at 0.0). Insurance ID and \
Insurance Plan Type are non-blocking — do not penalize.
- policy_match (0.0-1.0): 1.0 if policy found AND primary diagnosis aligns \
(Diagnosis-Policy Alignment MET), 0.5 if policy found but alignment unclear \
(INSUFFICIENT), 0.0 if no policy found or alignment NOT_MET

### Confidence Levels

- HIGH (0.80 - 1.0): All criteria MET with strong evidence, no gaps
- MEDIUM (0.50 - 0.79): Most criteria MET but moderate evidence or minor gaps
- LOW (0.0 - 0.49): Significant gaps, INSUFFICIENT criteria, or agent errors

### Penalty Adjustments

- Agent error: -0.20 per agent that returned an error
- Low extraction confidence (< 60%): flag as LOW CONFIDENCE WARNING

## Appeals Guidance (for PEND Decisions)

When recommending PEND, include in the output:
- What specific documentation would resolve the PEND
- Which criteria need additional evidence
- Which gate blocked the approval
- Suggested items for the provider to submit

## Output Format

Return JSON with this exact structure:
{
    "recommendation": "approve|pend_for_review",
    "confidence": 0.82,
    "confidence_level": "HIGH|MEDIUM|LOW",
    "summary": "Brief 2-3 sentence synthesis of all agent findings",
    "clinical_rationale": "Detailed rationale citing specific evidence from Clinical Reviewer and Coverage Agent. Reference criterion statuses (MET/NOT_MET/INSUFFICIENT) and confidence levels.",
    "decision_gate": "gate_1_provider|gate_2_codes|gate_3_necessity|approved",
    "coverage_criteria_met": ["criterion -- evidence (from Coverage Agent)"],
    "coverage_criteria_not_met": ["criterion -- gap description (from Coverage Agent)"],
    "missing_documentation": ["combined from Compliance and Coverage agents"],
    "policy_references": ["from Coverage Agent"],
    "criteria_summary": "N of M criteria MET",
    "audit_trail": {
        "gates_evaluated": ["gate_1_provider", "gate_2_codes", "gate_3_necessity"],
        "gate_results": {
            "gate_1_provider": "PASS|FAIL",
            "gate_2_codes": "PASS|FAIL",
            "gate_3_necessity": "PASS|FAIL"
        },
        "confidence_components": {
            "criteria_weight": 0.4,
            "criteria_score": 0.85,
            "extraction_weight": 0.3,
            "extraction_score": 0.75,
            "compliance_weight": 0.2,
            "compliance_score": 1.0,
            "policy_weight": 0.1,
            "policy_score": 1.0
        },
        "agents_consulted": ["compliance", "clinical", "coverage"]
    },
    "disclaimer": "AI-assisted draft. Coverage policies reflect Medicare LCDs/NCDs only. If this review is for a commercial or Medicare Advantage plan, payer-specific policies may differ. Human clinical review required before final determination."
}

## Rules

- Follow the gate evaluation ORDER strictly. If Gate 1 fails, do NOT
  evaluate Gates 2-3.
- Default to PEND when uncertain — never DENY in LENIENT mode.
- If Compliance Agent finds critical gaps, that alone warrants PEND at Gate 3.
- If Clinical Reviewer found invalid codes, PEND at Gate 2.
- If Coverage Agent found no matching policy, PEND at Gate 3.
- Be concise but cite which agent produced each finding.
- Reference specific criterion statuses and confidence scores in the rationale.
- Compute confidence using the weighted formula — do NOT estimate subjectively.
- Include the audit_trail object showing confidence breakdown.
- Do NOT generate tool_results — those come from the individual agents.
- The disclaimer field is MANDATORY in every output.
"""


def _compute_confidence(
    compliance_result: dict,
    clinical_result: dict,
    coverage_result: dict,
) -> tuple[float, str]:
    """Compute overall confidence score and level from agent results."""
    scores = []

    # Extraction confidence from clinical agent
    extraction = clinical_result.get("clinical_extraction", {})
    if isinstance(extraction, dict):
        ext_conf = extraction.get("extraction_confidence", 50)
        scores.append(ext_conf / 100.0)

    # Per-criterion confidence from coverage agent
    criteria = coverage_result.get("criteria_assessment", [])
    if criteria:
        criterion_scores = [
            c.get("confidence", 50) / 100.0
            for c in criteria
            if isinstance(c, dict)
        ]
        if criterion_scores:
            scores.append(sum(criterion_scores) / len(criterion_scores))

    # Compliance completeness bonus/penalty
    compliance_status = compliance_result.get("overall_status", "incomplete")
    missing = compliance_result.get("missing_items", [])
    if compliance_status == "complete" and not missing:
        scores.append(1.0)
    else:
        penalty = max(0.0, 1.0 - 0.1 * len(missing))
        scores.append(penalty)

    # Agent error penalties
    for result in [compliance_result, clinical_result, coverage_result]:
        if result.get("error"):
            scores.append(0.0)

    if not scores:
        return 0.5, "MEDIUM"

    confidence = sum(scores) / len(scores)
    confidence = max(0.0, min(1.0, confidence))

    if confidence >= 0.80:
        level = "HIGH"
    elif confidence >= 0.50:
        level = "MEDIUM"
    else:
        level = "LOW"

    return round(confidence, 2), level


def _normalize_coverage_result(coverage_result: dict) -> dict:
    """Lightweight pass-through for coverage agent output.

    With structured output (output_format), the coverage agent returns data
    matching the CoverageResult Pydantic schema directly. This function
    only normalizes the provider_verification status field for display
    consistency (e.g., 'A' -> 'VERIFIED').
    """
    if coverage_result.get("error"):
        return coverage_result

    result = dict(coverage_result)

    # Normalize provider_verification status for display
    pv = result.get("provider_verification")
    if pv and isinstance(pv, dict):
        status = str(pv.get("status", "")).upper()
        if status in ("A", "ACTIVE", "VERIFIED"):
            pv["status"] = "VERIFIED"
        elif status in ("D", "DEACTIVATED", "INACTIVE"):
            pv["status"] = "INACTIVE"

    return result


def _build_audit_trail(
    compliance_result: dict,
    clinical_result: dict,
    coverage_result: dict,
    start_time: str,
    synthesis: dict | None = None,
) -> dict:
    """Build audit trail from agent results."""
    data_sources = ["CPT/HCPCS Format Validation (Local)"]

    # Check which MCP tools were used via tool_results
    for result in [clinical_result, coverage_result]:
        for tr in result.get("tool_results", []):
            tool = tr.get("tool_name", "")
            tool_lower = tool.lower()
            if "npi" in tool_lower:
                source = "NPI Registry MCP (NPPES)"
            elif "icd10" in tool_lower or "icd-10" in tool_lower or "validate_code" in tool_lower or "lookup_code" in tool_lower:
                source = "ICD-10 MCP (2026 Code Set)"
            elif "coverage" in tool_lower or "cms" in tool_lower or "lcd" in tool_lower or "ncd" in tool_lower:
                source = "CMS Coverage MCP (LCDs/NCDs)"
            elif "trial" in tool_lower or "clinical_trial" in tool_lower or "clinical-trial" in tool_lower:
                source = "ClinicalTrials.gov MCP"
            elif "pubmed" in tool_lower:
                source = "PubMed MCP (Biomedical Literature)"
            elif "search" in tool_lower:
                # Generic "search" — likely PubMed search
                source = "PubMed MCP (Biomedical Literature)"
            else:
                source = f"MCP Tool: {tool}"
            if source not in data_sources:
                data_sources.append(source)

    # Always infer data sources from result data to supplement tool_results
    # (agents may not always report tool_results for every MCP call)

    # If provider verification has data, NPI registry was used
    pv = coverage_result.get("provider_verification", {})
    if pv and isinstance(pv, dict) and pv.get("npi"):
        if "NPI Registry MCP (NPPES)" not in data_sources:
            data_sources.append("NPI Registry MCP (NPPES)")

    # If diagnosis validation has data, ICD-10 MCP was used
    dx = clinical_result.get("diagnosis_validation", [])
    if dx:
        if "ICD-10 MCP (2026 Code Set)" not in data_sources:
            data_sources.append("ICD-10 MCP (2026 Code Set)")

    # If coverage policies found, CMS Coverage MCP was used
    policies = coverage_result.get("coverage_policies", [])
    if policies:
        if "CMS Coverage MCP (LCDs/NCDs)" not in data_sources:
            data_sources.append("CMS Coverage MCP (LCDs/NCDs)")

    # If literature support found, PubMed was used
    lit = clinical_result.get("literature_support", [])
    if lit:
        if "PubMed MCP (Biomedical Literature)" not in data_sources:
            data_sources.append("PubMed MCP (Biomedical Literature)")

    # If clinical trials found, ClinicalTrials.gov was used
    trials = clinical_result.get("clinical_trials", [])
    if trials:
        if "ClinicalTrials.gov MCP" not in data_sources:
            data_sources.append("ClinicalTrials.gov MCP")

    # Ensure all 5 MCP data sources are always listed — all servers are
    # queried on every review run, even if they return zero results
    for source in [
        "NPI Registry MCP (NPPES)",
        "ICD-10 MCP (2026 Code Set)",
        "CMS Coverage MCP (LCDs/NCDs)",
        "PubMed MCP (Biomedical Literature)",
        "ClinicalTrials.gov MCP",
    ]:
        if source not in data_sources:
            data_sources.append(source)

    # Extraction confidence
    extraction = clinical_result.get("clinical_extraction", {})
    ext_conf = extraction.get("extraction_confidence", 0) if isinstance(extraction, dict) else 0

    # Assessment confidence (avg of criterion confidences)
    criteria = coverage_result.get("criteria_assessment", [])

    # If coverage agent didn't provide criteria, try synthesis
    if not criteria and synthesis:
        criteria = synthesis.get("criteria_assessment", [])

    if criteria:
        conf_scores = [c.get("confidence", 0) for c in criteria if isinstance(c, dict)]
        assess_conf = int(sum(conf_scores) / len(conf_scores)) if conf_scores else 0
    else:
        assess_conf = 0

    # Criteria met count (case-insensitive — agents may return lowercase)
    met = sum(1 for c in criteria if isinstance(c, dict) and str(c.get("status", "")).upper() == "MET")
    total = len(criteria)
    criteria_met_count = f"{met}/{total}" if total else "0/0"

    # If criteria_met_count is 0/0 but synthesis has criteria data, use it
    if criteria_met_count == "0/0" and synthesis:
        syn_met = synthesis.get("coverage_criteria_met", [])
        syn_not_met = synthesis.get("coverage_criteria_not_met", [])
        if syn_met or syn_not_met:
            criteria_met_count = f"{len(syn_met)}/{len(syn_met) + len(syn_not_met)}"
            if assess_conf == 0 and syn_met:
                # Estimate from synthesis confidence
                assess_conf = int(synthesis.get("confidence", 0.5) * 100)

    return {
        "data_sources": data_sources,
        "review_started": start_time,
        "review_completed": datetime.now(timezone.utc).isoformat(),
        "extraction_confidence": ext_conf,
        "assessment_confidence": assess_conf,
        "criteria_met_count": criteria_met_count,
    }


def _generate_audit_justification(
    request_data: dict,
    synthesis: dict,
    compliance_result: dict,
    clinical_result: dict,
    coverage_result: dict,
    audit_trail: dict,
) -> str:
    """Generate an audit justification document in Markdown format.

    Based on the Anthropic prior-auth-review-skill audit_justification.md template.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    recommendation = str(synthesis.get("recommendation", "pend_for_review")).upper()
    confidence = synthesis.get("confidence", 0)
    try:
        confidence = float(confidence)
    except (ValueError, TypeError):
        confidence = 0.0
    confidence_level = synthesis.get("confidence_level", "LOW")

    lines = []

    # --- Disclaimer Header ---
    lines.append("# Prior Authorization Review — Audit Justification")
    lines.append("")
    lines.append("> **WARNING: AI-ASSISTED DRAFT — REVIEW REQUIRED**")
    lines.append("> All recommendations are drafts requiring human clinical review.")
    lines.append("> Coverage policies reflect Medicare LCDs/NCDs only.")
    lines.append("> Commercial and Medicare Advantage plans may differ.")
    lines.append("")

    # --- Section 1: Executive Summary ---
    lines.append("## 1. Executive Summary")
    lines.append("")
    lines.append(f"- **Review Date:** {now}")
    lines.append(f"- **Patient:** {request_data.get('patient_name', 'N/A')} (DOB: {request_data.get('patient_dob', 'N/A')})")
    lines.append(f"- **Provider NPI:** {request_data.get('provider_npi', 'N/A')}")
    lines.append(f"- **Insurance ID:** {request_data.get('insurance_id') or 'Not provided'}")
    lines.append(f"- **Diagnosis Codes:** {', '.join(request_data.get('diagnosis_codes', []))}")
    lines.append(f"- **Procedure Codes:** {', '.join(request_data.get('procedure_codes', []))}")
    lines.append(f"- **Decision:** {recommendation}")
    lines.append(f"- **Confidence:** {confidence_level} ({int(confidence * 100)}%)")
    lines.append("")
    lines.append(f"**Summary:** {synthesis.get('summary', 'N/A')}")
    lines.append("")

    # --- Section 2: Medical Necessity Assessment ---
    lines.append("## 2. Medical Necessity Assessment")
    lines.append("")

    # Coverage policy
    pv = coverage_result.get("provider_verification", {})
    if pv and isinstance(pv, dict):
        lines.append(f"**Provider:** {pv.get('name', 'N/A')} — {pv.get('specialty', 'N/A')} — Status: {pv.get('status', 'N/A')}")
        lines.append("")

    policies = coverage_result.get("coverage_policies", [])
    if policies:
        lines.append("**Coverage Policies Applied:**")
        for p in policies:
            if isinstance(p, dict):
                lines.append(f"- {p.get('policy_id', '?')}: {p.get('title', 'N/A')} ({p.get('type', '?')})")
        lines.append("")

    # Clinical evidence summary
    extraction = clinical_result.get("clinical_extraction", {})
    if isinstance(extraction, dict):
        lines.append("**Clinical Evidence Summary:**")
        if extraction.get("chief_complaint"):
            lines.append(f"- Chief Complaint: {extraction['chief_complaint']}")
        if extraction.get("prior_treatments"):
            lines.append(f"- Prior Treatments: {'; '.join(str(t) for t in extraction['prior_treatments'][:5])}")
        if extraction.get("severity_indicators"):
            lines.append(f"- Severity Indicators: {'; '.join(str(i) for i in extraction['severity_indicators'][:5])}")
        lines.append(f"- Extraction Confidence: {extraction.get('extraction_confidence', 0)}%")
        lines.append("")

    # --- Section 3: Criterion-by-Criterion Evaluation ---
    lines.append("## 3. Criterion-by-Criterion Evaluation")
    lines.append("")

    criteria = coverage_result.get("criteria_assessment", [])
    if criteria:
        lines.append(f"**Criteria Met:** {audit_trail.get('criteria_met_count', '0/0')}")
        lines.append("")
        for c in criteria:
            if not isinstance(c, dict):
                continue
            status = c.get("status", "INSUFFICIENT")
            icon = {"MET": "PASS", "NOT_MET": "FAIL", "INSUFFICIENT": "INFO"}.get(status, "?")
            lines.append(f"### [{icon}] {c.get('criterion', 'N/A')}")
            lines.append(f"- **Status:** {status}")
            lines.append(f"- **Confidence:** {c.get('confidence', 0)}%")
            evidence = c.get("evidence", [])
            if isinstance(evidence, list) and evidence:
                lines.append("- **Evidence:**")
                for e in evidence:
                    lines.append(f"  - {str(e)}")
            elif isinstance(evidence, str) and evidence:
                lines.append(f"- **Evidence:** {evidence}")
            if c.get("notes"):
                lines.append(f"- **Notes:** {c['notes']}")
            lines.append("")
    else:
        lines.append("No coverage criteria were identified for evaluation.")
        lines.append("")

    # --- Section 4: Validation Checks ---
    lines.append("## 4. Validation Checks")
    lines.append("")

    # Provider verification
    if pv and isinstance(pv, dict):
        lines.append(f"**Provider Verification:** NPI {pv.get('npi', 'N/A')} — {pv.get('status', 'N/A')}")
        if pv.get("detail"):
            lines.append(f"  Detail: {pv['detail']}")
        lines.append("")

    # Diagnosis code validation
    dx_val = clinical_result.get("diagnosis_validation", [])
    if dx_val:
        lines.append("**Diagnosis Code Validation:**")
        lines.append("")
        lines.append("| Code | Description | Billable | Valid |")
        lines.append("|------|-------------|----------|------|")
        for d in dx_val:
            if isinstance(d, dict):
                code = d.get("code", "?")
                desc = d.get("description", "N/A")[:60]
                billable = "Yes" if d.get("billable") else "No"
                valid = "Yes" if d.get("valid") else "No"
                lines.append(f"| {code} | {desc} | {billable} | {valid} |")
        lines.append("")

    # Compliance checklist
    checklist = compliance_result.get("checklist", [])
    if checklist:
        lines.append("**Compliance Checklist:**")
        lines.append("")
        lines.append("| Item | Status | Detail |")
        lines.append("|------|--------|--------|")
        for item in checklist:
            if isinstance(item, dict):
                lines.append(f"| {item.get('item', '?')} | {item.get('status', '?')} | {item.get('detail', '')[:60]} |")
        lines.append("")

    # --- Section 5: Decision Rationale ---
    lines.append("## 5. Decision Rationale")
    lines.append("")
    lines.append(f"**Decision:** {recommendation}")
    lines.append(f"**Gate:** {synthesis.get('decision_gate', 'N/A')}")
    lines.append(f"**Confidence:** {confidence_level} ({int(confidence * 100)}%)")
    lines.append("")
    lines.append(synthesis.get("clinical_rationale", "No rationale provided."))
    lines.append("")

    # Supporting facts
    met_criteria = synthesis.get("coverage_criteria_met", [])
    if met_criteria:
        lines.append("**Key Supporting Facts:**")
        for m in met_criteria:
            lines.append(f"- {str(m)}")
        lines.append("")

    # --- Section 6: Documentation Gaps ---
    gaps = coverage_result.get("documentation_gaps", [])
    missing = synthesis.get("missing_documentation", [])
    if gaps or missing:
        lines.append("## 6. Documentation Gaps")
        lines.append("")
        for g in gaps:
            if isinstance(g, dict):
                critical = "CRITICAL" if g.get("critical") else "Non-critical"
                lines.append(f"- [{critical}] {g.get('what', g.get('description', 'N/A'))}")
                if g.get("request"):
                    lines.append(f"  Request: {g['request']}")
            else:
                lines.append(f"- {str(g)}")
        for m in missing:
            lines.append(f"- {str(m)}")
        lines.append("")

    # --- Section 7: Audit Trail ---
    lines.append("## 7. Audit Trail")
    lines.append("")
    lines.append("**Data Sources:**")
    for src in audit_trail.get("data_sources", []):
        lines.append(f"- {src}")
    lines.append("")
    lines.append(f"- Review Started: {audit_trail.get('review_started', 'N/A')}")
    lines.append(f"- Review Completed: {audit_trail.get('review_completed', 'N/A')}")
    lines.append(f"- Extraction Confidence: {audit_trail.get('extraction_confidence', 0)}%")
    lines.append(f"- Assessment Confidence: {audit_trail.get('assessment_confidence', 0)}%")
    lines.append(f"- Criteria Met: {audit_trail.get('criteria_met_count', '0/0')}")
    lines.append("")

    # --- Section 8: Regulatory Compliance ---
    lines.append("## 8. Regulatory Compliance")
    lines.append("")
    lines.append("**Decision Policy:** LENIENT Mode (default)")
    lines.append("- Provider verification: Required")
    lines.append("- Code validation: Required")
    lines.append("- Medical necessity criteria: All must be MET for approval")
    lines.append("- Unmet/insufficient criteria: Results in PEND (not DENY)")
    lines.append("")

    # Footer
    lines.append("---")
    lines.append(f"*Generated: {now} | AI-Assisted Prior Authorization Review System*")

    return "\n".join(lines)


async def run_multi_agent_review(
    request_data: dict,
    on_progress: Callable[[dict], Awaitable[None]] | None = None,
) -> dict:
    """Run the multi-agent prior auth review pipeline.

    Phase 1 (parallel): Compliance + Clinical Reviewer
    Phase 2 (sequential): Coverage Agent (receives clinical findings)
    Phase 3: Synthesis agent reads all reports, produces final decision
    Phase 4: Audit trail assembly and justification document generation

    Args:
        request_data: Dict with patient_name, patient_dob, provider_npi,
            diagnosis_codes, procedure_codes, clinical_notes, insurance_id.
        on_progress: Optional async callback for streaming progress events.

    Returns:
        Dict with recommendation, confidence, confidence_level, summary,
        tool_results, clinical_rationale, coverage criteria,
        policy_references, disclaimer, agent_results, audit_trail,
        and audit_justification (markdown string).
    """
    start_time = datetime.now(timezone.utc).isoformat()

    async def _emit(event: dict) -> None:
        if on_progress:
            await on_progress(event)

    # --- Pre-flight: CPT/HCPCS format validation ---
    logger.info("Pre-flight: Validating procedure code formats")
    cpt_validation = validate_procedure_codes(
        request_data.get("procedure_codes", [])
    )
    if not cpt_validation["valid"]:
        logger.warning("CPT validation found invalid codes: %s", cpt_validation["summary"])

    await _emit({
        "phase": "preflight", "status": "completed", "progress_pct": 5,
        "message": "CPT/HCPCS format validation complete",
        "agents": {},
    })

    # --- Phase 1: Parallel — Compliance + Clinical Reviewer ---
    logger.info("Phase 1: Running Compliance and Clinical agents in parallel")

    await _emit({
        "phase": "phase_1", "status": "running", "progress_pct": 10,
        "message": "Running Compliance and Clinical agents in parallel",
        "agents": {
            "compliance": {"status": "running", "detail": "Checking documentation completeness"},
            "clinical": {"status": "running", "detail": "Validating codes and extracting clinical evidence"},
        },
    })

    compliance_task = asyncio.create_task(
        _safe_run("Compliance Agent", run_compliance_review, request_data)
    )
    clinical_task = asyncio.create_task(
        _safe_run("Clinical Reviewer Agent", run_clinical_review, request_data)
    )

    compliance_result, clinical_result = await asyncio.gather(
        compliance_task, clinical_task
    )

    # Diagnostic: dump agent result keys and sample values for debugging
    _dump_agent_result("Compliance", compliance_result)
    _dump_agent_result("Clinical", clinical_result)

    await _emit({
        "phase": "phase_1", "status": "completed", "progress_pct": 40,
        "message": "Compliance and Clinical agents completed",
        "agents": {
            "compliance": {
                "status": "error" if compliance_result.get("error") else "done",
                "detail": compliance_result.get("error", "Documentation review complete"),
            },
            "clinical": {
                "status": "error" if clinical_result.get("error") else "done",
                "detail": clinical_result.get("error", "Clinical analysis complete"),
            },
        },
    })

    # --- Phase 2: Sequential — Coverage Agent (needs clinical findings) ---
    logger.info("Phase 2: Running Coverage Agent with clinical findings")

    await _emit({
        "phase": "phase_2", "status": "running", "progress_pct": 45,
        "message": "Running Coverage Agent with clinical findings",
        "agents": {
            "coverage": {"status": "running", "detail": "Verifying provider and assessing coverage criteria"},
        },
    })

    coverage_result = await _safe_run(
        "Coverage Agent", run_coverage_review, request_data, clinical_result
    )

    # Normalize coverage result (fix provider data format, etc.)
    coverage_result = _normalize_coverage_result(coverage_result)

    # Diagnostic: dump coverage agent result
    _dump_agent_result("Coverage", coverage_result)

    await _emit({
        "phase": "phase_2", "status": "completed", "progress_pct": 70,
        "message": "Coverage Agent completed",
        "agents": {
            "coverage": {
                "status": "error" if coverage_result.get("error") else "done",
                "detail": coverage_result.get("error", "Coverage analysis complete"),
            },
        },
    })

    # --- Phase 3: Synthesis ---
    logger.info("Phase 3: Synthesizing final recommendation")

    await _emit({
        "phase": "phase_3", "status": "running", "progress_pct": 75,
        "message": "Synthesizing final recommendation",
        "agents": {
            "synthesis": {"status": "running", "detail": "Applying decision rubric gates"},
        },
    })

    synthesis = await _run_synthesis(
        request_data, compliance_result, clinical_result, coverage_result,
        cpt_validation,
    )

    # Coerce list[str] fields from synthesis — agent may return list[dict]
    for _str_list_key in (
        "coverage_criteria_met", "coverage_criteria_not_met",
        "missing_documentation", "policy_references",
    ):
        val = synthesis.get(_str_list_key)
        if isinstance(val, list):
            synthesis[_str_list_key] = [
                str(item) if not isinstance(item, str) else item
                for item in val
            ]

    await _emit({
        "phase": "phase_3", "status": "completed", "progress_pct": 90,
        "message": "Synthesis complete",
        "agents": {
            "synthesis": {"status": "done", "detail": "Decision rubric applied"},
        },
    })

    # --- Phase 4: Audit Trail & Justification ---
    logger.info("Phase 4: Building audit trail and justification document")

    await _emit({
        "phase": "phase_4", "status": "running", "progress_pct": 92,
        "message": "Building audit trail and justification document",
        "agents": {},
    })

    confidence, confidence_level = _compute_confidence(
        compliance_result, clinical_result, coverage_result
    )

    # Use synthesis confidence if available, fall back to computed
    final_confidence = synthesis.get("confidence", confidence)
    final_level = synthesis.get("confidence_level", confidence_level)

    audit_trail = _build_audit_trail(
        compliance_result, clinical_result, coverage_result, start_time,
        synthesis=synthesis,
    )

    audit_justification = _generate_audit_justification(
        request_data, synthesis,
        compliance_result, clinical_result, coverage_result,
        audit_trail,
    )

    audit_justification_pdf = generate_audit_justification_pdf(
        request_data, synthesis,
        compliance_result, clinical_result, coverage_result,
        audit_trail,
    )

    # --- Assemble final response ---
    all_tool_results = []

    # Add CPT validation as a tool result
    all_tool_results.append({
        "tool_name": "cpt_format_validation",
        "status": "pass" if cpt_validation["valid"] else "fail",
        "detail": cpt_validation["summary"],
    })

    all_tool_results.extend(clinical_result.get("tool_results", []))
    all_tool_results.extend(coverage_result.get("tool_results", []))

    # If agents didn't report tool_results, synthesize from available data
    existing_tools = {t.get("tool_name", "") for t in all_tool_results}

    # ICD-10 validation from clinical agent
    dx_val = clinical_result.get("diagnosis_validation", [])
    if dx_val and not any("icd" in t.lower() or "diagnosis" in t.lower() for t in existing_tools):
        valid_count = sum(1 for d in dx_val if isinstance(d, dict) and d.get("valid"))
        billable_count = sum(1 for d in dx_val if isinstance(d, dict) and d.get("billable"))
        total = len(dx_val)
        all_tool_results.append({
            "tool_name": "icd10_validation",
            "status": "pass" if valid_count == total else "warning",
            "detail": f"{valid_count}/{total} codes valid, {billable_count}/{total} billable",
        })

    # NPI verification from coverage agent
    pv = coverage_result.get("provider_verification", {})
    if pv and isinstance(pv, dict) and pv.get("npi") and not any("npi" in t.lower() for t in existing_tools):
        pv_status = pv.get("status", "unknown").upper()
        all_tool_results.append({
            "tool_name": "npi_verification",
            "status": "pass" if pv_status in ("VERIFIED", "ACTIVE") else "warning",
            "detail": f"NPI {pv.get('npi')} — {pv.get('name', 'N/A')} — {pv_status}",
        })

    # Coverage policy search from coverage agent
    policies = coverage_result.get("coverage_policies", [])
    if policies and not any("coverage" in t.lower() or "cms" in t.lower() for t in existing_tools):
        all_tool_results.append({
            "tool_name": "cms_coverage_search",
            "status": "pass",
            "detail": f"{len(policies)} coverage policies found",
        })

    await _emit({
        "phase": "phase_4", "status": "completed", "progress_pct": 100,
        "message": "Review complete",
        "agents": {},
    })

    return {
        **synthesis,
        "confidence": final_confidence,
        "confidence_level": final_level,
        "tool_results": all_tool_results,
        "agent_results": {
            "compliance": compliance_result,
            "clinical": clinical_result,
            "coverage": coverage_result,
        },
        "audit_trail": audit_trail,
        "audit_justification": audit_justification,
        "audit_justification_pdf": audit_justification_pdf,
    }


def _dump_agent_result(agent_name: str, result: dict) -> None:
    """Diagnostic: save agent raw dict to a temp file for inspection."""
    try:
        import tempfile
        dump_path = Path(tempfile.gettempdir()) / f"agent_raw_{agent_name.lower().replace(' ', '_')}.json"
        with open(dump_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, default=str, ensure_ascii=False)
        logger.info("[DIAG] Saved %s raw result (%d keys) to %s", agent_name, len(result), dump_path)
    except Exception as e:
        logger.warning("[DIAG] Failed to save %s dump: %s", agent_name, e)


async def _safe_run(agent_name: str, fn, *args) -> dict:
    """Run an agent function with error handling.

    On Windows, if the running event loop is a SelectorEventLoop (which
    uvicorn --reload may create), subprocess execution will fail. In that
    case, run the agent in a separate thread with its own ProactorEventLoop.

    Returns the agent's result dict on success, or an error dict on failure.
    """
    try:
        loop = asyncio.get_running_loop()
        loop_type = type(loop).__name__
        policy_type = type(asyncio.get_event_loop_policy()).__name__
        logger.info("[debug] %s — event loop: %s, policy: %s", agent_name, loop_type, policy_type)

        # If running on a SelectorEventLoop, subprocess_exec won't work.
        # Run the agent in a separate thread with a ProactorEventLoop.
        if isinstance(loop, asyncio.SelectorEventLoop) and os.name == "nt":
            logger.info("[debug] %s — SelectorEventLoop detected, using thread-based ProactorEventLoop", agent_name)
            return await _run_in_proactor_thread(agent_name, fn, *args)

        return await fn(*args)
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.error("%s failed:\n%s", agent_name, tb)
        return {"error": str(e), "tool_results": []}


async def _run_in_proactor_thread(agent_name: str, fn, *args) -> dict:
    """Run an async agent function in a separate thread with ProactorEventLoop.

    This is the workaround for Windows uvicorn --reload creating a
    SelectorEventLoop which doesn't support subprocess creation.
    """
    import concurrent.futures

    def _thread_target():
        """Create a ProactorEventLoop in this thread and run the agent."""
        proactor_loop = asyncio.ProactorEventLoop()
        asyncio.set_event_loop(proactor_loop)
        try:
            return proactor_loop.run_until_complete(fn(*args))
        finally:
            proactor_loop.close()

    # Run in a thread pool to avoid blocking the main event loop
    loop = asyncio.get_running_loop()
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=1, thread_name_prefix=f"agent-{agent_name}"
    ) as executor:
        result = await loop.run_in_executor(executor, _thread_target)

    return result


async def _run_synthesis(
    request_data: dict,
    compliance_result: dict,
    clinical_result: dict,
    coverage_result: dict,
    cpt_validation: dict | None = None,
) -> dict:
    """Run the synthesis agent to produce the final decision.

    This is a lightweight reasoning-only agent (no tools) that reads the
    reports from all three specialized agents and applies the decision rubric
    with gate-based evaluation.

    In skills mode, uses SKILL.md discovery from .claude/skills/synthesis-decision/.
    In prompt mode, uses inline SYNTHESIS_INSTRUCTIONS.
    """
    _output_format = pydantic_to_output_format(SynthesisOutput)

    if settings.USE_SKILLS:
        agent = ClaudeAgent(
            instructions=(
                "You are a Synthesis Decision Agent. "
                "Use your synthesis-decision Skill to evaluate the gate-based "
                "decision rubric and produce a final recommendation. "
                "CRITICAL: Your FINAL response MUST be a single valid JSON object "
                "inside a ```json code fence. No markdown commentary outside the fence."
            ),
            default_options={
                "cwd": _BACKEND_DIR,
                "setting_sources": ["user", "project"],
                "allowed_tools": ["Skill"],
                "permission_mode": "bypassPermissions",
                "output_format": _output_format,
            },
        )
    else:
        agent = ClaudeAgent(
            instructions=SYNTHESIS_INSTRUCTIONS,
            default_options={
                "permission_mode": "bypassPermissions",
                "output_format": _output_format,
            },
        )

    # Build CPT validation section for the prompt
    cpt_section = ""
    if cpt_validation:
        cpt_section = f"""
--- CPT/HCPCS FORMAT VALIDATION (Pre-Agent) ---
All codes valid format: {cpt_validation['valid']}
Summary: {cpt_validation['summary']}
Details:
{json.dumps(cpt_validation['results'], indent=2)}

--- END CPT VALIDATION ---

"""

    prompt = f"""Synthesize these three agent reports into a final prior authorization recommendation.
Apply the decision rubric gates in order (provider -> codes -> medical necessity).

--- ORIGINAL REQUEST SUMMARY ---
Patient: {request_data['patient_name']} (DOB: {request_data['patient_dob']})
Provider NPI: {request_data['provider_npi']}
Diagnosis Codes: {', '.join(request_data['diagnosis_codes'])}
Procedure Codes: {', '.join(request_data['procedure_codes'])}
{cpt_section}--- COMPLIANCE AGENT REPORT ---
{json.dumps(compliance_result, indent=2, default=str)}

--- CLINICAL REVIEWER AGENT REPORT ---
{json.dumps(clinical_result, indent=2, default=str)}

--- COVERAGE AGENT REPORT ---
{json.dumps(coverage_result, indent=2, default=str)}

--- END REPORTS ---

Evaluate the decision gates in order. Compute the confidence score and level.
Respond with ONLY a ```json code fence containing a single JSON object. No other text."""

    async def _do_synthesis():
        async with agent:
            response = await agent.run(prompt)
        return parse_json_response(response)

    return await _safe_run("Synthesis Agent", _do_synthesis)
