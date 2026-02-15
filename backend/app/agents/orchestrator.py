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
"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from agent_framework_claude import ClaudeAgent

from app.agents._parse import parse_json_response
from app.agents.compliance_agent import run_compliance_review
from app.agents.clinical_agent import run_clinical_review
from app.agents.coverage_agent import run_coverage_review
from app.services.cpt_validation import validate_procedure_codes

logger = logging.getLogger(__name__)


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
You are the Orchestrator Agent for prior authorization review.
You receive the outputs of three specialized agents:

1. **Compliance Agent** — checked documentation completeness
2. **Clinical Reviewer Agent** — validated ICD-10 codes, extracted clinical
   evidence with confidence scoring, searched supporting literature
3. **Coverage Agent** — verified provider NPI, assessed coverage criteria
   using MET/NOT_MET/INSUFFICIENT status with per-criterion confidence

Your job is to synthesize their findings into a single final recommendation
by following the decision rubric below.

## Decision Policy: LENIENT MODE (Default)

Evaluate in this order. Stop at the first failing gate:

### Gate 1: Provider Verification
| Scenario | Action |
|----------|--------|
| Provider NPI valid and active | PASS — continue to Gate 2 |
| Provider NPI invalid or inactive | PEND — request credentialing info |

### Gate 2: Code Validation
| Scenario | Action |
|----------|--------|
| All ICD-10 codes valid and billable | PASS — continue to Gate 3 |
| Any ICD-10 code invalid | PEND — request diagnosis code clarification |
| All CPT/HCPCS codes valid format | PASS — continue to Gate 3 |
| Any CPT/HCPCS code invalid format | PEND — request procedure code clarification |
| CPT/HCPCS codes present with valid format | PASS (clinical appropriateness deferred to Gate 3) |

### Gate 3: Medical Necessity Criteria
| Scenario | Action |
|----------|--------|
| All required criteria MET | APPROVE |
| Any required criterion NOT_MET | PEND — request additional documentation |
| Any required criterion INSUFFICIENT | PEND — specify what documentation is needed |
| No coverage policy found | PEND — manual policy review needed |
| Documentation incomplete (Compliance) | PEND — specify missing items |

### Catch-All
| Scenario | Action |
|----------|--------|
| Uncertain or conflicting signals | PEND — default safe option |

IMPORTANT: In LENIENT mode, recommend APPROVE or PEND only — never DENY.
Only approve when ALL three gates pass cleanly.

## Confidence Scoring

Compute an overall confidence score (0.0 - 1.0) and level:
- **HIGH** (0.80 - 1.0): All criteria MET with high confidence, no gaps
- **MEDIUM** (0.50 - 0.79): Most criteria MET but some with moderate evidence
- **LOW** (0.0 - 0.49): Significant gaps, INSUFFICIENT criteria, or agent errors

Base the score on:
1. Average of per-criterion confidence scores from Coverage Agent
2. Extraction confidence from Clinical Reviewer
3. Compliance completeness (all items complete = +10%, gaps = -10% each)
4. Penalty for any agent errors (-20% per agent error)

## Output Format

Return JSON with this exact structure:
{
    "recommendation": "approve" | "pend_for_review",
    "confidence": 0.0-1.0,
    "confidence_level": "HIGH|MEDIUM|LOW",
    "summary": "Brief 2-3 sentence synthesis of all agent findings",
    "clinical_rationale": "Detailed rationale citing specific evidence from Clinical Reviewer and Coverage Agent. Reference criterion statuses (MET/NOT_MET/INSUFFICIENT) and confidence levels.",
    "decision_gate": "Gate where decision was made (gate_1_provider|gate_2_codes|gate_3_necessity|approved)",
    "coverage_criteria_met": ["criterion — evidence (from Coverage Agent)"],
    "coverage_criteria_not_met": ["criterion — gap description (from Coverage Agent)"],
    "missing_documentation": ["combined from Compliance and Coverage agents"],
    "policy_references": ["from Coverage Agent"],
    "criteria_summary": "N of M criteria MET",
    "disclaimer": "AI-assisted draft. Coverage policies reflect Medicare LCDs/NCDs only. If this review is for a commercial or Medicare Advantage plan, payer-specific policies may differ. Human clinical review required before final determination."
}

## Rules

- Follow the gate evaluation ORDER strictly. If Gate 1 fails, do not evaluate Gates 2-3.
- Default to PEND when uncertain.
- If Compliance Agent finds critical gaps, that alone warrants PEND at Gate 3.
- If Clinical Reviewer found invalid codes, PEND at Gate 2.
- If Coverage Agent found no matching policy, PEND at Gate 3.
- Be concise but cite which agent produced each finding.
- Reference specific criterion statuses and confidence scores in the rationale.
- Do NOT generate tool_results — those come from the individual agents.
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


def _build_audit_trail(
    compliance_result: dict,
    clinical_result: dict,
    coverage_result: dict,
    start_time: str,
) -> dict:
    """Build audit trail from agent results."""
    data_sources = ["CPT/HCPCS Format Validation (Local)"]

    # Check which MCP tools were used
    for result in [clinical_result, coverage_result]:
        for tr in result.get("tool_results", []):
            tool = tr.get("tool_name", "")
            if "npi" in tool.lower():
                source = "NPI Registry MCP (NPPES)"
            elif "icd10" in tool.lower() or "validate_code" in tool.lower() or "lookup_code" in tool.lower():
                source = "ICD-10 MCP (2026 Code Set)"
            elif "coverage" in tool.lower() or "cms" in tool.lower():
                source = "CMS Coverage MCP (LCDs/NCDs)"
            elif "search" in tool.lower() or "pubmed" in tool.lower():
                source = "PubMed MCP (Biomedical Literature)"
            else:
                source = f"MCP Tool: {tool}"
            if source not in data_sources:
                data_sources.append(source)

    # Extraction confidence
    extraction = clinical_result.get("clinical_extraction", {})
    ext_conf = extraction.get("extraction_confidence", 0) if isinstance(extraction, dict) else 0

    # Assessment confidence (avg of criterion confidences)
    criteria = coverage_result.get("criteria_assessment", [])
    if criteria:
        conf_scores = [c.get("confidence", 0) for c in criteria if isinstance(c, dict)]
        assess_conf = int(sum(conf_scores) / len(conf_scores)) if conf_scores else 0
    else:
        assess_conf = 0

    # Criteria met count
    met = sum(1 for c in criteria if isinstance(c, dict) and c.get("status") == "MET")
    total = len(criteria)
    criteria_met_count = f"{met}/{total}" if total else "0/0"

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
    recommendation = synthesis.get("recommendation", "pend_for_review").upper()
    confidence = synthesis.get("confidence", 0)
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
            lines.append(f"- Prior Treatments: {'; '.join(extraction['prior_treatments'][:5])}")
        if extraction.get("severity_indicators"):
            lines.append(f"- Severity Indicators: {'; '.join(extraction['severity_indicators'][:5])}")
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
                    lines.append(f"  - {e}")
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
            lines.append(f"- {m}")
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
                lines.append(f"- [{critical}] {g.get('what', 'N/A')}")
                if g.get("request"):
                    lines.append(f"  Request: {g['request']}")
        for m in missing:
            lines.append(f"- {m}")
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
        compliance_result, clinical_result, coverage_result, start_time
    )

    audit_justification = _generate_audit_justification(
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
    }


async def _safe_run(agent_name: str, fn, *args) -> dict:
    """Run an agent function with error handling.

    Returns the agent's result dict on success, or an error dict on failure.
    """
    try:
        return await fn(*args)
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print(f"\n{'='*60}")
        print(f"[ERROR] {agent_name} failed:")
        print(tb)
        print(f"{'='*60}\n")
        logger.error("%s failed: %s", agent_name, e)
        return {"error": str(e), "tool_results": []}


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
    """
    agent = ClaudeAgent(
        instructions=SYNTHESIS_INSTRUCTIONS,
        default_options={
            "permission_mode": "bypassPermissions",
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
Produce your structured JSON recommendation."""

    async with agent:
        response = await agent.run(prompt)

    return parse_json_response(response)
