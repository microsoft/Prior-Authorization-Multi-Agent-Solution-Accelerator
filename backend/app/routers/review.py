"""API routes for prior authorization review."""

import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.models.schemas import (
    PriorAuthRequest,
    ReviewResponse,
    ReviewSummary,
    AgentResults,
    AuditTrail,
    ComplianceResult,
    ClinicalResult,
    CoverageResult,
    DocumentationGap,
    AgentCheck,
)
from app.agents.orchestrator import (
    run_multi_agent_review,
    store_review,
    get_review,
    list_reviews,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _build_review_response(request_id: str, result: dict) -> ReviewResponse:
    """Build a ReviewResponse from orchestrator output."""
    # Parse merged tool_results from all agents
    tool_results = []
    for tr in result.get("tool_results", []):
        tool_results.append({
            "tool_name": tr.get("tool_name", "unknown"),
            "status": tr.get("status", "warning"),
            "detail": tr.get("detail", ""),
        })

    # Parse per-agent results.
    # output_format provides schema guidance to agents but doesn't
    # mechanically enforce field names. Lightweight adapters handle
    # common output variations before Pydantic parsing.
    agent_raw = result.get("agent_results", {})

    compliance_raw = agent_raw.get("compliance")
    if isinstance(compliance_raw, dict):
        compliance_raw["checks_performed"] = _generate_compliance_checks(compliance_raw)
        agent_raw["compliance"] = compliance_raw

    clinical_raw = agent_raw.get("clinical")
    if isinstance(clinical_raw, dict):
        clinical_raw = _adapt_clinical_output(clinical_raw)
        clinical_raw["checks_performed"] = _generate_clinical_checks(clinical_raw)
        agent_raw["clinical"] = clinical_raw

    coverage_raw = agent_raw.get("coverage")
    if isinstance(coverage_raw, dict):
        coverage_raw = _adapt_coverage_output(coverage_raw)
        coverage_raw["checks_performed"] = _generate_coverage_checks(coverage_raw)
        agent_raw["coverage"] = coverage_raw

    agent_results = AgentResults(
        compliance=_safe_parse(ComplianceResult, compliance_raw),
        clinical=_safe_parse(ClinicalResult, clinical_raw),
        coverage=_safe_parse(CoverageResult, coverage_raw),
    )

    # Parse audit trail
    audit_raw = result.get("audit_trail")
    audit_trail = _safe_parse(AuditTrail, audit_raw)

    # Parse documentation gaps
    doc_gaps = []
    for g in result.get("documentation_gaps", []):
        parsed = _safe_parse(DocumentationGap, g)
        if parsed:
            doc_gaps.append(parsed)
    # Also pull from coverage agent if not in synthesis
    if not doc_gaps and agent_results.coverage and agent_results.coverage.documentation_gaps:
        doc_gaps = agent_results.coverage.documentation_gaps

    return ReviewResponse(
        request_id=request_id,
        recommendation=result.get("recommendation", "pend_for_review"),
        confidence=result.get("confidence", 0.0),
        confidence_level=result.get("confidence_level", ""),
        summary=result.get("summary", "Review completed."),
        tool_results=tool_results,
        clinical_rationale=result.get("clinical_rationale", ""),
        coverage_criteria_met=result.get("coverage_criteria_met", []),
        coverage_criteria_not_met=result.get("coverage_criteria_not_met", []),
        missing_documentation=result.get("missing_documentation", []),
        documentation_gaps=doc_gaps,
        policy_references=result.get("policy_references", []),
        disclaimer=result.get(
            "disclaimer",
            "AI-assisted draft. Coverage policies reflect Medicare LCDs/NCDs only. "
            "If this review is for a commercial or Medicare Advantage plan, "
            "payer-specific policies may differ. Human clinical review required "
            "before final determination.",
        ),
        agent_results=agent_results,
        audit_trail=audit_trail,
        audit_justification=result.get("audit_justification"),
        audit_justification_pdf=result.get("audit_justification_pdf"),
    )


@router.post("/review", response_model=ReviewResponse)
async def submit_review(request: PriorAuthRequest):
    """Submit a prior authorization request for multi-agent AI-assisted review.

    Three specialized agents (Compliance, Clinical Reviewer, Coverage) run
    in a fan-out/fan-in pattern. An orchestrator synthesizes their outputs
    into a final APPROVE or PEND recommendation using a gate-based decision
    rubric with confidence scoring.

    Returns the structured decision along with per-agent breakdowns, audit
    trail, and an audit justification document.
    """
    request_id = str(uuid.uuid4())

    try:
        result = await run_multi_agent_review(request.model_dump())
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Multi-agent review failed: {str(e)}",
        )

    response = _build_review_response(request_id, result)

    # Persist for later retrieval and decision-making
    store_review(request_id, request.model_dump(), response.model_dump())

    return response


@router.post("/review/stream")
async def submit_review_stream(request: PriorAuthRequest, http_request: Request):
    """Stream prior authorization review progress via Server-Sent Events.

    Emits progress events as the multi-agent pipeline runs, then sends
    the final ReviewResponse as an 'event: result' SSE event.
    """
    request_id = str(uuid.uuid4())
    queue: asyncio.Queue[dict | None] = asyncio.Queue()

    async def on_progress(event: dict) -> None:
        await queue.put(event)

    async def run_review() -> None:
        try:
            result = await run_multi_agent_review(
                request.model_dump(), on_progress=on_progress
            )
            response = _build_review_response(request_id, result)
            store_review(request_id, request.model_dump(), response.model_dump())
            await queue.put({"_type": "result", "data": response.model_dump()})
        except Exception as e:
            await queue.put({"_type": "error", "detail": str(e)})
        finally:
            await queue.put(None)  # Sentinel

    async def event_generator():
        task = asyncio.create_task(run_review())
        try:
            while True:
                # Check if client disconnected
                if await http_request.is_disconnected():
                    task.cancel()
                    break

                try:
                    event = await asyncio.wait_for(queue.get(), timeout=2.0)
                except asyncio.TimeoutError:
                    # Send keepalive comment
                    yield ": keepalive\n\n"
                    continue

                if event is None:
                    break  # Sentinel — pipeline done

                if event.get("_type") == "result":
                    data = json.dumps(event["data"], default=str)
                    yield f"event: result\ndata: {data}\n\n"
                elif event.get("_type") == "error":
                    data = json.dumps({"detail": event["detail"]})
                    yield f"event: error\ndata: {data}\n\n"
                else:
                    data = json.dumps(event, default=str)
                    yield f"event: progress\ndata: {data}\n\n"
        except asyncio.CancelledError:
            task.cancel()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/review/{request_id}", response_model=ReviewResponse)
async def get_review_by_id(request_id: str):
    """Retrieve a previously completed review by its request_id."""
    stored = get_review(request_id)
    if not stored:
        raise HTTPException(status_code=404, detail=f"Review {request_id} not found")
    return ReviewResponse(**stored["response"])


@router.get("/reviews", response_model=list[ReviewSummary])
async def get_all_reviews():
    """List all completed reviews (most recent first)."""
    reviews = list_reviews()
    return [
        ReviewSummary(
            request_id=r["request_id"],
            patient_name=r["request_data"].get("patient_name", ""),
            recommendation=r["response"].get("recommendation", ""),
            confidence_level=r["response"].get("confidence_level", ""),
            reviewed_at=r["stored_at"],
            decision_made=r["decision"] is not None,
        )
        for r in reviews
    ]


def _get_any_field(d: dict, *keys, default=None):
    """Return the first non-empty value from a dict trying multiple field names.

    Agents may use variant names for the same field (e.g., 'hpi' vs
    'history_of_present_illness'). This helper tries each key in order
    and returns the first non-empty match.
    """
    if not isinstance(d, dict):
        return default
    for key in keys:
        val = d.get(key)
        if val is not None and val != "" and val != []:
            return val
    return default


# ---------------------------------------------------------------------------
# Lightweight output adapters
# ---------------------------------------------------------------------------
# The Claude Code SDK's output_format provides schema guidance but does NOT
# mechanically enforce field names like the direct Claude API does. Agents
# may use wrapper objects or variant field names. These adapters extract the
# correct data into the Pydantic-expected fields. They are intentionally
# concise compared to the old 1000+ line sanitizer.
# ---------------------------------------------------------------------------


def _find_list(data: dict, *keys) -> list:
    """Recursively find the first non-empty list under any of the given keys."""
    for key in keys:
        val = data.get(key)
        if isinstance(val, list) and val:
            return val
        if isinstance(val, dict):
            # Search one level deeper
            for sub_val in val.values():
                if isinstance(sub_val, list) and sub_val:
                    return sub_val
    return []


def _unwrap(data: dict, *wrapper_keys) -> dict:
    """Unwrap top-level wrapper objects (e.g., prior_authorization_review)."""
    result = dict(data)
    for key in wrapper_keys:
        if key in result and isinstance(result[key], dict):
            inner = result.pop(key)
            for k, v in inner.items():
                if k not in result:
                    result[k] = v
    return result


def _adapt_clinical_output(data: dict) -> dict:
    """Map clinical agent output to ClinicalResult schema fields.

    Handles common agent patterns: wrapper objects, variant field names,
    nested validation arrays, and nested extraction structures.
    """
    r = _unwrap(data, "prior_authorization_review", "clinical_review",
                "clinical_assessment", "clinical_review_report")

    # --- diagnosis_validation ---
    if not r.get("diagnosis_validation"):
        codes = _find_list(r, "diagnosis_code_validation", "icd10_code_validation",
                           "code_validation", "diagnosis_validation")
        if codes:
            r["diagnosis_validation"] = [
                {
                    "code": c.get("code", ""),
                    "valid": c.get("valid", c.get("is_valid", c.get("exists", False))),
                    "description": c.get("description", ""),
                    "billable": c.get("billable", c.get("valid_for_hipaa",
                                 c.get("hipaa_compliant", False))),
                }
                for c in codes if isinstance(c, dict) and c.get("code")
            ]

    # --- clinical_extraction ---
    ce = r.get("clinical_extraction")
    if isinstance(ce, dict) and not ce.get("chief_complaint"):
        # Agent used custom sub-structure; flatten into schema fields
        r["clinical_extraction"] = {
            "chief_complaint": _get_any_field(ce, "chief_complaint", "cc",
                              "presenting_complaint", default=""),
            "history_of_present_illness": _get_any_field(ce,
                              "history_of_present_illness", "hpi", default=""),
            "prior_treatments": _get_any_field(ce, "prior_treatments",
                              "previous_treatments", "treatment_history", default=[]),
            "severity_indicators": _get_any_field(ce, "severity_indicators",
                              "severity", default=[]),
            "functional_limitations": _get_any_field(ce, "functional_limitations",
                              "limitations", default=[]),
            "diagnostic_findings": _get_any_field(ce, "diagnostic_findings",
                              "findings", "test_results", default=[]),
            "duration_and_progression": _get_any_field(ce,
                              "duration_and_progression", "progression", default=""),
            "extraction_confidence": ce.get("extraction_confidence",
                              r.get("extraction_confidence", 0)),
        }

    # Ensure extraction_confidence propagates from top level if needed
    ce = r.get("clinical_extraction")
    if isinstance(ce, dict) and not ce.get("extraction_confidence"):
        ce["extraction_confidence"] = r.get("extraction_confidence", 0)

    # --- literature_support ---
    if not isinstance(r.get("literature_support"), list) or not r["literature_support"]:
        lit = r.get("literature_support", {})
        if isinstance(lit, dict):
            refs = _find_list(lit, "references", "relevant_articles", "key_findings",
                              "supporting_literature", "articles", "pubmed_results")
            r["literature_support"] = [
                {"title": ref.get("title", ""), "pmid": str(ref.get("pmid", ref.get("id", ""))),
                 "relevance": ref.get("relevance", ref.get("key_finding", ref.get("finding", "")))}
                for ref in refs if isinstance(ref, dict)
            ]

    # --- clinical_trials ---
    if not isinstance(r.get("clinical_trials"), list) or not r["clinical_trials"]:
        trials = r.get("clinical_trials", {})
        if isinstance(trials, dict):
            trial_list = _find_list(trials, "relevant_trials", "potentially_relevant_trials",
                                    "trials", "active_trials", "matching_trials")
            r["clinical_trials"] = [
                {"nct_id": t.get("nct_id", t.get("id", "")),
                 "title": t.get("title", ""), "status": t.get("status", ""),
                 "relevance": t.get("relevance", "")}
                for t in trial_list if isinstance(t, dict)
            ]

    # --- clinical_summary ---
    if not r.get("clinical_summary"):
        r["clinical_summary"] = _get_any_field(
            r, "clinical_summary", "summary", "overall_assessment",
            "clinical_recommendation", default="")
        if isinstance(r["clinical_summary"], dict):
            # Extract from recommendation dict
            justification = r["clinical_summary"].get("justification", [])
            if isinstance(justification, list):
                r["clinical_summary"] = " ".join(str(j) for j in justification)
            else:
                r["clinical_summary"] = r["clinical_summary"].get(
                    "summary", r["clinical_summary"].get(
                        "recommendation", str(r["clinical_summary"])))

    return r


def _adapt_coverage_output(data: dict) -> dict:
    """Map coverage agent output to CoverageResult schema fields.

    Handles common agent patterns: wrapper objects, nested policy
    structures, criteria mapping variants, and documentation gaps.
    """
    r = _unwrap(data, "coverage_assessment", "coverage_review")

    # --- provider_verification ---
    pv = r.get("provider_verification")
    if isinstance(pv, dict):
        # Extract from nested provider_details sub-object
        pd = pv.get("provider_details", {})
        if isinstance(pd, dict) and pd:
            if not pv.get("npi") and pd.get("npi"):
                pv["npi"] = str(pd["npi"])
            if not pv.get("name"):
                pv["name"] = _get_any_field(pd, "name", "full_name",
                              "provider_name", default="")
            if not pv.get("status"):
                pv["status"] = pd.get("status", "")

        # Normalize name from other variant fields
        if not pv.get("name"):
            pv["name"] = _get_any_field(pv, "provider_name", "full_name", default="")

        # Normalize specialty — may be in specialty_verification sub-object or a dict
        spec = pv.get("specialty")
        if isinstance(spec, dict):
            pv["specialty"] = spec.get("primary_taxonomy_description",
                              spec.get("description", ""))
        if not pv.get("specialty"):
            sv = pv.get("specialty_verification", {})
            if isinstance(sv, dict) and sv:
                pv["specialty"] = _get_any_field(
                    sv, "primary_taxonomy_description", "description",
                    "taxonomy_description", "specialty", default="")

        # Normalize status
        status = str(pv.get("status", "")).upper()
        if status in ("A", "ACTIVE", "VERIFIED"):
            pv["status"] = "VERIFIED"
        elif status in ("D", "DEACTIVATED", "INACTIVE"):
            pv["status"] = "INACTIVE"

    # --- coverage_policies ---
    if not r.get("coverage_policies"):
        r["coverage_policies"] = _find_list(
            r, "coverage_policies", "coverage_policy_analysis",
            "applicable_policies", "policies")

    # --- criteria_assessment ---
    if not r.get("criteria_assessment"):
        criteria = _find_list(
            r, "criteria_assessment", "medical_necessity_criteria_mapping",
            "criteria_mapping", "coverage_criteria_assessment")
        if criteria:
            r["criteria_assessment"] = [
                {
                    "criterion": c.get("criterion", c.get("name",
                                 c.get("criteria_name", ""))),
                    "status": c.get("status", ""),
                    "confidence": c.get("confidence", 0),
                    "evidence": c.get("evidence", ""),
                    "notes": c.get("notes", ""),
                    "source": c.get("source", ""),
                    "met": c.get("met", c.get("status", "").upper() == "MET"),
                }
                for c in criteria if isinstance(c, dict)
            ]

    # --- documentation_gaps ---
    if not r.get("documentation_gaps"):
        r["documentation_gaps"] = _find_list(
            r, "documentation_gaps", "documentation_gap_analysis",
            "gaps_identified", "gaps")
        # Normalize gap items
        if r["documentation_gaps"]:
            r["documentation_gaps"] = [
                {
                    "what": g.get("what", g.get("description",
                             g.get("gap", g.get("finding", "")))),
                    "why_needed": g.get("why_needed", g.get("impact",
                                  g.get("reason", ""))),
                    "critical": g.get("critical", False),
                }
                for g in r["documentation_gaps"] if isinstance(g, dict)
            ]

    return r


def _generate_compliance_checks(raw: dict) -> list[dict]:
    """Generate checks summary from raw compliance agent data.

    Always enumerates ALL 8 rules from the Compliance SKILL.md,
    filling in status from raw agent data when available.
    """
    # Build a lookup from agent checklist items by normalized name
    checklist = raw.get("checklist", [])
    item_lookup: dict[str, dict] = {}
    for item in checklist:
        if not isinstance(item, dict):
            continue
        item_name = str(item.get("item", item.get("name", item.get("check", "")))).lower().strip()
        item_lookup[item_name] = item

    def _find_item(*keywords: str) -> dict | None:
        """Find a checklist item matching any of the given keywords."""
        for key, item in item_lookup.items():
            for kw in keywords:
                if kw in key:
                    return item
        return None

    def _item_result(item: dict | None) -> tuple[str, str]:
        """Return (result, detail) for a checklist item."""
        if item is None:
            return "warning", "Not evaluated by agent"
        status = str(item.get("status", "incomplete")).lower()
        detail = item.get("detail", "")
        if status in ("complete", "present"):
            return "pass", detail
        elif status in ("missing", "absent"):
            return "fail", detail
        else:
            return "warning", detail or f"Status: {status}"

    checks = []

    # Overall status — always first
    overall = raw.get("overall_status", "incomplete")
    checks.append({
        "rule": "Overall Documentation Review",
        "result": "pass" if overall == "complete" else "warning",
        "detail": f"Status: {overall}",
    })

    # SKILL.md Rule 1: Patient Information
    item = _find_item("patient", "demographics", "personal info")
    r, d = _item_result(item)
    checks.append({"rule": "Patient Information", "result": r, "detail": d or "Name and DOB check"})

    # SKILL.md Rule 2: Provider NPI
    item = _find_item("provider", "npi", "referring", "ordering")
    r, d = _item_result(item)
    checks.append({"rule": "Provider NPI", "result": r, "detail": d or "NPI format check (10 digits)"})

    # SKILL.md Rule 3: Insurance ID (non-blocking)
    item = _find_item("insurance id", "insurance_id", "member id", "member_id", "payer")
    r, d = _item_result(item)
    if r == "fail":
        r = "info"  # Non-blocking per SKILL.md
    checks.append({"rule": "Insurance ID (non-blocking)", "result": r, "detail": d or "Insurance ID presence"})

    # SKILL.md Rule 4: Diagnosis Codes
    item = _find_item("diagnosis", "icd", "dx code")
    r, d = _item_result(item)
    checks.append({"rule": "Diagnosis Codes", "result": r, "detail": d or "ICD-10 code format check"})

    # SKILL.md Rule 5: Procedure Codes
    item = _find_item("procedure", "cpt", "hcpcs", "proc code")
    r, d = _item_result(item)
    checks.append({"rule": "Procedure Codes", "result": r, "detail": d or "CPT/HCPCS code presence"})

    # SKILL.md Rule 6: Clinical Notes Presence
    item = _find_item("notes presence", "clinical notes pres", "notes pres", "documentation pres")
    if item is None:
        # Fall back to generic "clinical notes" or "documentation" match
        item = _find_item("clinical note", "documentation", "narrative")
    r, d = _item_result(item)
    checks.append({"rule": "Clinical Notes Presence", "result": r, "detail": d or "Substantive clinical narrative check"})

    # SKILL.md Rule 7: Clinical Notes Quality
    item = _find_item("notes quality", "quality", "clinical quality", "documentation quality")
    r, d = _item_result(item)
    checks.append({"rule": "Clinical Notes Quality", "result": r, "detail": d or "Notes detail, boilerplate/copy-paste check"})

    # SKILL.md Rule 8: Insurance Plan Type (non-blocking)
    item = _find_item("plan type", "insurance type", "insurance plan", "coverage type", "payer type")
    r, d = _item_result(item)
    if r == "fail":
        r = "info"  # Non-blocking per SKILL.md
    checks.append({"rule": "Insurance Plan Type (non-blocking)", "result": r, "detail": d or "Medicare/Medicaid/Commercial/MA identification"})

    return checks


def _generate_clinical_checks(raw: dict) -> list[dict]:
    """Generate checks summary from raw clinical agent data.

    Always enumerates ALL 7 rules from the Clinical Review SKILL.md,
    filling in status from raw agent data when available.
    """
    checks = []

    # ── SKILL.md Step 1: ICD-10 Diagnosis Code Validation ──
    dx = raw.get("diagnosis_validation", [])
    if isinstance(dx, list) and dx:
        valid_count = sum(
            1 for d in dx if isinstance(d, dict) and d.get("valid")
        )
        billable_count = sum(
            1 for d in dx if isinstance(d, dict) and d.get("billable")
        )
        total = len([d for d in dx if isinstance(d, dict)])
        checks.append({
            "rule": "Step 1: ICD-10 Diagnosis Code Validation",
            "result": "pass" if valid_count == total else "warning",
            "detail": f"{valid_count}/{total} valid, {billable_count}/{total} billable",
        })
        for d in dx:
            if not isinstance(d, dict):
                continue
            code = d.get("code", "?")
            valid = d.get("valid", False)
            billable = d.get("billable", False)
            desc = d.get("description", "")
            if valid and billable:
                r = "pass"
                det = desc
            elif valid:
                r = "warning"
                det = f"{desc} (valid but not billable — hierarchy lookup needed)"
            else:
                r = "fail"
                det = f"{desc} (invalid)"
            checks.append({"rule": f"  validate_code + lookup_code: {code}", "result": r, "detail": det})
    else:
        checks.append({
            "rule": "Step 1: ICD-10 Diagnosis Code Validation",
            "result": "warning",
            "detail": "No validation data returned (validate_code, lookup_code, get_hierarchy)",
        })

    # ── SKILL.md Step 2: CPT/HCPCS Procedure Code Notation ──
    proc_val = raw.get("procedure_validation", [])
    if isinstance(proc_val, list) and proc_val:
        passed = sum(1 for p in proc_val if isinstance(p, dict) and str(p.get("status", "")).lower() in ("pass", "valid", "verified"))
        total = len([p for p in proc_val if isinstance(p, dict)])
        checks.append({
            "rule": "Step 2: CPT/HCPCS Procedure Code Notation",
            "result": "pass" if passed == total else "warning",
            "detail": f"{passed}/{total} procedure codes noted/verified",
        })
    else:
        # Check if pre-flight CPT validation was passed through
        checks.append({
            "rule": "Step 2: CPT/HCPCS Procedure Code Notation",
            "result": "info",
            "detail": "Procedure codes noted (validation via orchestrator pre-flight)",
        })

    # ── SKILL.md Step 3: Clinical Data Extraction (8 fields) ──
    extraction = raw.get("clinical_extraction", {})
    if isinstance(extraction, dict) and extraction:
        field_checks = {
            "Chief Complaint": _get_any_field(extraction, "chief_complaint", "cc", "presenting_complaint", "reason_for_visit", default=""),
            "History of Present Illness": _get_any_field(extraction, "history_of_present_illness", "hpi", "present_illness", "history", default=""),
            "Prior Treatments": _get_any_field(extraction, "prior_treatments", "previous_treatments", "prior_therapy", "treatment_history", "treatments", default=[]),
            "Severity Indicators": _get_any_field(extraction, "severity_indicators", "severity", "severity_markers", "severity_factors", default=[]),
            "Functional Limitations": _get_any_field(extraction, "functional_limitations", "functional_status", "limitations", "functional_impact", default=[]),
            "Diagnostic Findings": _get_any_field(extraction, "diagnostic_findings", "diagnostics", "findings", "diagnostic_results", "test_results", "lab_results", default=[]),
            "Duration and Progression": _get_any_field(extraction, "duration_and_progression", "duration", "progression", "timeline", "disease_progression", "course", default=""),
            "Medical History / Comorbidities": _get_any_field(extraction, "medical_history", "comorbidities", "past_medical_history", "pmh", "relevant_medical_history", "relevant_history", "medical_history_comorbidities", default=""),
        }
        extracted_count = sum(1 for v in field_checks.values() if v)
        checks.append({
            "rule": "Step 3: Clinical Data Extraction",
            "result": "pass" if extracted_count >= 5 else ("warning" if extracted_count >= 3 else "fail"),
            "detail": f"{extracted_count}/8 clinical fields extracted",
        })
        for field_name, field_value in field_checks.items():
            has_data = bool(field_value)
            if isinstance(field_value, list):
                detail = f"{len(field_value)} items found" if field_value else "Not found in clinical notes"
            elif isinstance(field_value, str):
                detail = field_value[:80] + "..." if len(field_value) > 80 else field_value if field_value else "Not found in clinical notes"
            else:
                detail = "Not found in clinical notes"
            checks.append({
                "rule": f"  Extract: {field_name}",
                "result": "pass" if has_data else "info",
                "detail": detail,
            })
    else:
        checks.append({
            "rule": "Step 3: Clinical Data Extraction",
            "result": "warning",
            "detail": "No structured extraction data returned",
        })
        for field_name in [
            "Chief Complaint", "History of Present Illness", "Prior Treatments",
            "Severity Indicators", "Functional Limitations", "Diagnostic Findings",
            "Duration and Progression", "Medical History / Comorbidities",
        ]:
            checks.append({
                "rule": f"  Extract: {field_name}",
                "result": "warning",
                "detail": "Not evaluated — no extraction data",
            })

    # ── SKILL.md Step 4: Extraction Confidence Calculation ──
    if isinstance(extraction, dict) and extraction:
        conf = extraction.get("extraction_confidence", 0)
        if isinstance(conf, float) and 0 < conf <= 1:
            conf = round(conf * 100)
        low_conf_warning = " — LOW CONFIDENCE WARNING" if conf < 60 else ""
        checks.append({
            "rule": "Step 4: Extraction Confidence Calculation",
            "result": "pass" if conf >= 60 else "warning",
            "detail": f"Overall extraction confidence: {conf}%{low_conf_warning}",
        })
    else:
        checks.append({
            "rule": "Step 4: Extraction Confidence Calculation",
            "result": "warning",
            "detail": "Cannot calculate — no extraction data",
        })

    # ── SKILL.md Step 5: PubMed Literature Search ──
    lit = raw.get("literature_support", [])
    if isinstance(lit, list) and lit:
        checks.append({
            "rule": "Step 5: PubMed Literature Search",
            "result": "pass",
            "detail": f"{len(lit)} supporting references found",
        })
    else:
        checks.append({
            "rule": "Step 5: PubMed Literature Search",
            "result": "info",
            "detail": "No literature references returned (supplementary — non-blocking)",
        })

    # ── SKILL.md Step 6: Clinical Trials Search ──
    trials = raw.get("clinical_trials", [])
    if isinstance(trials, list) and trials:
        checks.append({
            "rule": "Step 6: Clinical Trials Search",
            "result": "pass",
            "detail": f"{len(trials)} relevant trials found",
        })
    else:
        checks.append({
            "rule": "Step 6: Clinical Trials Search",
            "result": "info",
            "detail": "No clinical trials returned (supplementary — non-blocking)",
        })

    # ── SKILL.md Step 7: Structure Findings (Clinical Summary + Tool Audit) ──
    summary = raw.get("clinical_summary", raw.get("summary", ""))
    checks.append({
        "rule": "Step 7: Clinical Summary Generation",
        "result": "pass" if summary else "warning",
        "detail": "Summary generated" if summary else "No summary produced",
    })

    # Tool Results audit trail
    tools = raw.get("tool_results", [])
    if isinstance(tools, list) and tools:
        pass_count = sum(1 for t in tools if isinstance(t, dict) and t.get("status") == "pass")
        checks.append({
            "rule": "MCP Tool Executions",
            "result": "pass" if pass_count == len(tools) else "warning",
            "detail": f"{pass_count}/{len(tools)} tools passed",
        })

    return checks


def _generate_coverage_checks(raw: dict) -> list[dict]:
    """Generate checks summary from raw coverage agent data.

    Always enumerates ALL 7 rules from the Coverage Assessment SKILL.md,
    filling in status from raw agent data when available.
    """
    checks = []

    # ── SKILL.md Step 1: Provider NPI Verification ──
    pv = raw.get("provider_verification", {})
    if isinstance(pv, dict) and pv.get("npi"):
        status = str(pv.get("status", "")).upper()
        name = pv.get("name", pv.get("provider_name", "N/A"))
        specialty = pv.get("specialty", "N/A")
        if status in ("VERIFIED", "ACTIVE", "A"):
            r = "pass"
        elif status in ("INACTIVE", "DEACTIVATED", "D", "NOT_FOUND"):
            r = "fail"
        else:
            r = "warning"
        checks.append({
            "rule": "Step 1: Provider NPI Verification",
            "result": r,
            "detail": f"NPI {pv['npi']} — {name} — {specialty} — {status}",
        })
        # Sub-checks: validate + lookup
        checks.append({
            "rule": "  npi_validate (format + Luhn)",
            "result": r,
            "detail": f"NPI {pv['npi']} format check",
        })
        checks.append({
            "rule": "  npi_lookup (NPPES registry)",
            "result": r,
            "detail": f"{name} — {specialty} — Status: {status}",
        })
    else:
        checks.append({
            "rule": "Step 1: Provider NPI Verification",
            "result": "warning",
            "detail": "No provider verification data returned (npi_validate, npi_lookup)",
        })
        checks.append({
            "rule": "  npi_validate (format + Luhn)",
            "result": "warning",
            "detail": "Not evaluated",
        })
        checks.append({
            "rule": "  npi_lookup (NPPES registry)",
            "result": "warning",
            "detail": "Not evaluated",
        })

    # ── SKILL.md Step 2: MAC Identification ──
    # Coverage agent may store contractors data in different locations
    contractors = raw.get("contractors", raw.get("mac_identification", None))
    if contractors:
        checks.append({
            "rule": "Step 2: MAC Identification",
            "result": "pass",
            "detail": f"Medicare Administrative Contractors identified" if not isinstance(contractors, list) else f"{len(contractors)} MACs identified",
        })
    else:
        # Check for MAC mentions in provider verification detail or coverage notes
        pv_detail = str(pv.get("detail", "")) if isinstance(pv, dict) else ""
        raw_notes = str(raw.get("notes", ""))
        has_mac_ref = any(
            term in (pv_detail + raw_notes).lower()
            for term in ["mac", "medicare administrative contractor", "jurisdiction"]
        )
        if has_mac_ref:
            checks.append({
                "rule": "Step 2: MAC Identification",
                "result": "pass",
                "detail": "MAC jurisdiction referenced in provider/coverage data",
            })
        else:
            checks.append({
                "rule": "Step 2: MAC Identification",
                "result": "info",
                "detail": "MAC identification via get_contractors (state-based lookup)",
            })

    # ── SKILL.md Step 3: Coverage Policy Search (NCD + LCD) ──
    policies = raw.get("coverage_policies", [])
    if isinstance(policies, list) and policies:
        relevant = sum(
            1 for p in policies
            if isinstance(p, dict) and p.get("relevant", True)
        )
        ncds = sum(1 for p in policies if isinstance(p, dict) and str(p.get("type", "")).upper() == "NCD")
        lcds = sum(1 for p in policies if isinstance(p, dict) and str(p.get("type", "")).upper() == "LCD")
        checks.append({
            "rule": "Step 3: Coverage Policy Search",
            "result": "pass",
            "detail": f"{len(policies)} policies found ({ncds} NCD, {lcds} LCD), {relevant} relevant",
        })
        # Sub-checks for national and local
        checks.append({
            "rule": "  search_national_coverage (NCDs)",
            "result": "pass" if ncds > 0 else "info",
            "detail": f"{ncds} national coverage determinations found" if ncds > 0 else "No NCDs found",
        })
        checks.append({
            "rule": "  search_local_coverage (LCDs)",
            "result": "pass" if lcds > 0 else "info",
            "detail": f"{lcds} local coverage determinations found" if lcds > 0 else "No LCDs found",
        })
        # Individual policies as sub-items
        for p in policies:
            if not isinstance(p, dict):
                continue
            pid = p.get("policy_id", p.get("id", p.get("document_id", "?")))
            ptype = p.get("type", "?")
            title = p.get("title", "")
            checks.append({
                "rule": f"  {ptype}: {pid}",
                "result": "pass" if p.get("relevant", True) else "info",
                "detail": title,
            })
    else:
        checks.append({
            "rule": "Step 3: Coverage Policy Search",
            "result": "warning",
            "detail": "No coverage policies found (search_national_coverage, search_local_coverage)",
        })
        checks.append({
            "rule": "  search_national_coverage (NCDs)",
            "result": "warning",
            "detail": "No national policies returned",
        })
        checks.append({
            "rule": "  search_local_coverage (LCDs)",
            "result": "warning",
            "detail": "No local policies returned",
        })

    # ── SKILL.md Step 4: Policy Detail Retrieval ──
    # Infer from policies — if we have policies with titles/criteria, details were retrieved
    has_policy_details = any(
        isinstance(p, dict) and (p.get("title") or p.get("criteria"))
        for p in policies
    ) if isinstance(policies, list) else False
    checks.append({
        "rule": "Step 4: Policy Detail Retrieval",
        "result": "pass" if has_policy_details else ("info" if policies else "warning"),
        "detail": "Policy details retrieved (get_coverage_document, batch_get_ncds)" if has_policy_details else "No detailed policy content retrieved",
    })

    # ── SKILL.md Step 5: Clinical Evidence to Criteria Mapping ──
    criteria = raw.get("criteria_assessment", [])
    if isinstance(criteria, list) and criteria:
        met = sum(
            1 for c in criteria
            if isinstance(c, dict) and str(c.get("status", "")).upper() == "MET"
        )
        not_met = sum(
            1 for c in criteria
            if isinstance(c, dict) and str(c.get("status", "")).upper() == "NOT_MET"
        )
        insufficient = sum(
            1 for c in criteria
            if isinstance(c, dict) and str(c.get("status", "")).upper() == "INSUFFICIENT"
        )
        total = len([c for c in criteria if isinstance(c, dict)])
        if met == total:
            r = "pass"
        elif met > 0:
            r = "warning"
        else:
            r = "fail"
        checks.append({
            "rule": "Step 5: Clinical Evidence to Criteria Mapping",
            "result": r,
            "detail": f"{met}/{total} MET, {not_met} NOT_MET, {insufficient} INSUFFICIENT",
        })
        for c in criteria:
            if not isinstance(c, dict):
                continue
            crit_name = c.get("criterion", c.get("name", c.get("criteria", "?")))
            crit_status = str(c.get("status", "INSUFFICIENT")).upper()
            conf = c.get("confidence", 0)
            if crit_status == "MET":
                cr = "pass"
            elif crit_status == "NOT_MET":
                cr = "fail"
            else:
                cr = "warning"
            checks.append({
                "rule": f"  {crit_name}",
                "result": cr,
                "detail": f"{crit_status} (confidence: {conf}%)",
            })
    else:
        checks.append({
            "rule": "Step 5: Clinical Evidence to Criteria Mapping",
            "result": "warning",
            "detail": "No criteria assessment data returned",
        })

    # ── SKILL.md Step 6: Diagnosis-Policy Alignment (REQUIRED AUDITABLE) ──
    # Look for a specific "Diagnosis-Policy Alignment" criterion in criteria_assessment
    alignment_found = False
    _ALIGNMENT_KEYWORDS = [
        "alignment", "diagnosis-policy", "diagnosis policy",
        "diagnosis match", "diagnostic match", "indication match",
        "covered indication", "diagnostic indication",
        "icd-10 match", "icd-10 policy", "icd-10 coverage",
        "icd10 match", "icd10 policy", "icd10 coverage",
        "diagnostic appropriateness", "diagnosis appropriateness",
        "code-to-policy", "diagnosis coverage", "appropriate diagnosis",
        "appropriate indication", "medical indication",
    ]
    if isinstance(criteria, list):
        for c in criteria:
            if not isinstance(c, dict):
                continue
            crit_name = str(c.get("criterion", c.get("name", ""))).lower()
            if any(kw in crit_name for kw in _ALIGNMENT_KEYWORDS):
                alignment_found = True
                crit_status = str(c.get("status", "INSUFFICIENT")).upper()
                conf = c.get("confidence", 0)
                if crit_status == "MET":
                    ar = "pass"
                elif crit_status == "NOT_MET":
                    ar = "fail"
                else:
                    ar = "warning"
                checks.append({
                    "rule": "Step 6: Diagnosis-Policy Alignment (AUDITABLE)",
                    "result": ar,
                    "detail": f"{crit_status} — ICD-10 codes vs. covered indications (confidence: {conf}%)",
                })
                break
    if not alignment_found:
        checks.append({
            "rule": "Step 6: Diagnosis-Policy Alignment (AUDITABLE)",
            "result": "warning",
            "detail": "Required auditable criterion — not explicitly evaluated by agent",
        })

    # ── SKILL.md Step 7: Documentation Gap Analysis ──
    gaps = raw.get("documentation_gaps", [])
    if isinstance(gaps, list) and gaps:
        critical_count = sum(
            1 for g in gaps if isinstance(g, dict) and g.get("critical")
        )
        non_critical = len(gaps) - critical_count
        checks.append({
            "rule": "Step 7: Documentation Gap Analysis",
            "result": "fail" if critical_count > 0 else "warning",
            "detail": f"{len(gaps)} gaps identified ({critical_count} critical, {non_critical} non-critical)",
        })
    else:
        checks.append({
            "rule": "Step 7: Documentation Gap Analysis",
            "result": "pass",
            "detail": "No documentation gaps identified",
        })

    # Tool Results audit trail
    tools = raw.get("tool_results", [])
    if isinstance(tools, list) and tools:
        pass_count = sum(1 for t in tools if isinstance(t, dict) and t.get("status") == "pass")
        checks.append({
            "rule": "MCP Tool Executions",
            "result": "pass" if pass_count == len(tools) else "warning",
            "detail": f"{pass_count}/{len(tools)} tools passed",
        })

    return checks


def _safe_parse(model_class, data):
    """Attempt to parse a dict into a Pydantic model, return None on failure.

    With structured output (output_format), agent data already matches the
    Pydantic schema. This function simply validates and returns the model,
    with field-by-field and minimal fallbacks for robustness.
    """
    if not data or not isinstance(data, dict):
        return None

    # Stage 1: Direct validation — should always work with structured output
    try:
        return model_class.model_validate(data)
    except Exception as e:
        logger.warning("Parse %s failed (stage 1): %s", model_class.__name__, e)
        logger.info("Parse %s data keys: %s", model_class.__name__, list(data.keys()))

    # Stage 2: Field-by-field fallback — try each field individually
    try:
        model_fields = set(model_class.model_fields.keys())
        good_fields = {}

        for field_name in model_fields:
            if field_name not in data:
                continue
            try:
                test_data = {field_name: data[field_name]}
                model_class.model_validate(test_data)
                good_fields[field_name] = data[field_name]
            except Exception:
                logger.info(
                    "Parse %s: field '%s' failed individually, skipping (type=%s)",
                    model_class.__name__, field_name,
                    type(data[field_name]).__name__,
                )

        if good_fields:
            try:
                result = model_class.model_validate(good_fields)
                provided = len([k for k in model_fields if k in data])
                kept = len(good_fields)
                if provided > 0 and kept < provided:
                    logger.info(
                        "Parse %s: field-by-field kept %d/%d fields",
                        model_class.__name__, kept, provided,
                    )
                return result
            except Exception as e2:
                logger.warning("Parse %s field-by-field reassembly failed: %s", model_class.__name__, e2)
    except Exception as e:
        logger.warning("Parse %s field-by-field fallback failed: %s", model_class.__name__, e)

    # Stage 3: Minimal fallback with error info
    try:
        minimal = {}
        if "agent_name" in data:
            minimal["agent_name"] = str(data["agent_name"])
        if "error" in data:
            minimal["error"] = str(data["error"])
        else:
            minimal["error"] = "Agent data could not be parsed into expected format"
        return model_class.model_validate(minimal)
    except Exception:
        return None

