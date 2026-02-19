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

    # Parse per-agent results (best-effort — agent JSON may not match exactly)
    # Sanitize agent data BEFORE generating checks so type coercion and
    # field aliasing are applied. Checks then see normalized field names/types.
    # Checks are generated before Pydantic parsing so they survive even if
    # some detailed fields fail validation.
    agent_raw = result.get("agent_results", {})

    compliance_raw = agent_raw.get("compliance")
    if isinstance(compliance_raw, dict):
        compliance_raw = _sanitize_agent_data(compliance_raw)
        compliance_raw["checks_performed"] = _generate_compliance_checks(compliance_raw)
        agent_raw["compliance"] = compliance_raw

    clinical_raw = agent_raw.get("clinical")
    if isinstance(clinical_raw, dict):
        clinical_raw = _sanitize_agent_data(clinical_raw)
        clinical_raw["checks_performed"] = _generate_clinical_checks(clinical_raw)
        agent_raw["clinical"] = clinical_raw

    coverage_raw = agent_raw.get("coverage")
    if isinstance(coverage_raw, dict):
        coverage_raw = _sanitize_agent_data(coverage_raw)
        coverage_raw["checks_performed"] = _generate_coverage_checks(coverage_raw)
        agent_raw["coverage"] = coverage_raw

    agent_results = AgentResults(
        compliance=_safe_parse(ComplianceResult, compliance_raw, already_sanitized=True),
        clinical=_safe_parse(ClinicalResult, clinical_raw, already_sanitized=True),
        coverage=_safe_parse(CoverageResult, coverage_raw, already_sanitized=True),
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


def _safe_parse(model_class, data, already_sanitized=False):
    """Attempt to parse a dict into a Pydantic model, return None on failure.

    Three-stage approach:
    1. Sanitize (field aliasing + type coercion) then validate whole model
    2. Field-by-field fallback — try each field individually, skip failures
    3. Minimal fallback (preserves agent_name and error fields)

    Sanitization always runs first because models use defaults for all fields,
    so direct validation would succeed with empty values for misnamed fields.

    If already_sanitized=True, skip re-sanitization (data was already processed
    by _sanitize_agent_data before calling this function).
    """
    if not data or not isinstance(data, dict):
        return None

    # Always sanitize first to handle field aliasing and type coercion
    try:
        sanitized = data if already_sanitized else _sanitize_agent_data(data)
        return model_class.model_validate(sanitized)
    except Exception as e:
        logger.warning("Parse %s failed (stage 1): %s", model_class.__name__, e)
        logger.info("Parse %s data keys: %s", model_class.__name__, list(data.keys()))

    # Stage 2: Field-by-field fallback — try each field individually
    # This preserves data that parses correctly even if one field is bad
    try:
        sanitized = data if already_sanitized else _sanitize_agent_data(data)
        model_fields = set(model_class.model_fields.keys())
        good_fields = {}

        for field_name in model_fields:
            if field_name not in sanitized:
                continue
            try:
                # Test if this single field validates by itself
                test_data = {field_name: sanitized[field_name]}
                model_class.model_validate(test_data)
                good_fields[field_name] = sanitized[field_name]
            except Exception:
                logger.info(
                    "Parse %s: field '%s' failed individually, skipping (type=%s)",
                    model_class.__name__, field_name,
                    type(sanitized[field_name]).__name__,
                )

        if good_fields:
            try:
                result = model_class.model_validate(good_fields)
                # Count how many meaningful fields we got vs total available
                provided = len([k for k in model_fields if k in sanitized])
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


def _sanitize_agent_data(data: dict) -> dict:
    """Sanitize agent result dict to handle common type mismatches.

    LLM agents sometimes return:
    - list[str] fields as a single string, or list[dict] instead of list[str]
    - bool fields as "Yes"/"No"/"true"/"false" strings
    - int fields as "85%" strings or 0.85 floats
    - evidence fields as strings instead of lists
    - field names that differ from the expected schema

    This function normalizes these before Pydantic validation.
    """
    if not isinstance(data, dict):
        return data

    result = dict(data)

    # --- Unwrap top-level containers that agents tend to use ---
    # Clinical agent wraps in "clinical_review", coverage in "coverage_assessment".
    # When the parser merges multiple JSON fence blocks, the wrapper key coexists
    # with other keys (e.g., 10 total), so we can't rely on len(result) <= 2.
    # Instead, soft-merge: merge inner dict into top level, only for sub-keys
    # that don't already exist (prevents overwriting direct top-level data).
    _WRAPPER_KEYS = (
        "clinical_review", "clinical_review_report", "coverage_assessment",
        "compliance_review", "coverage_review", "clinical_assessment",
        "prior_authorization_review",
    )
    for wrapper in _WRAPPER_KEYS:
        if wrapper in result and isinstance(result[wrapper], dict):
            inner = result.pop(wrapper)
            for k, v in inner.items():
                if k not in result:
                    result[k] = v
            break

    # --- Field name aliasing (BEFORE list extraction so aliases are in place) ---
    # Clinical agent: "supporting_literature" → "literature_support"
    if "supporting_literature" in result and "literature_support" not in result:
        result["literature_support"] = result.pop("supporting_literature")

    # Clinical agent: "relevant_clinical_trials" → "clinical_trials"
    if "relevant_clinical_trials" in result and "clinical_trials" not in result:
        result["clinical_trials"] = result.pop("relevant_clinical_trials")

    # Clinical agent: "recommendations" (plural) → "recommendation" (singular)
    if "recommendations" in result and "recommendation" not in result:
        result["recommendation"] = result.pop("recommendations")

    # --- Extract nested lists from wrapper dicts ---
    # Agent may return diagnosis_validation as {"validation_results": [...], ...}
    # or {"diagnosis_codes": [...], ...} instead of a plain list
    _LIST_EXTRACT_KEYS = {
        "diagnosis_validation": ("validation_results", "diagnosis_codes", "codes", "results", "details"),
        "literature_support": ("references", "articles", "key_references", "sources", "key_citations", "relevant_articles", "key_findings"),
        "clinical_trials": ("trials", "relevant_trials", "diagnostic_trials",
                            "treatment_trials", "active_trials", "highlighted_trials",
                            "recommended_for_referral", "potentially_eligible_trials",
                            "high_relevance_trials", "relevant_trial_ids",
                            "relevant_recruiting_trials"),
        "coverage_policies": ("policies", "relevant_policies"),
        "criteria_assessment": ("criteria", "assessment_criteria", "results",
                                "criteria_evaluation", "medical_necessity_criteria"),
        "documentation_gaps": ("gaps",),
    }
    for field, extract_keys in _LIST_EXTRACT_KEYS.items():
        if field in result and isinstance(result[field], dict):
            inner_dict = result[field]
            extracted = False
            # Try to find the actual list inside the wrapper dict
            for ek in extract_keys:
                if ek in inner_dict and isinstance(inner_dict[ek], list):
                    result[field] = inner_dict[ek]
                    extracted = True
                    break
            # If no single list key matched, check if the dict has multiple
            # sub-category keys that each hold a list (e.g., criteria_assessment
            # with medical_necessity_criteria, diagnosis_code_criteria, etc.)
            if not extracted:
                sub_lists = [
                    v for v in inner_dict.values()
                    if isinstance(v, list)
                ]
                if sub_lists:
                    combined = []
                    for sl in sub_lists:
                        combined.extend(sl)
                    if combined:
                        result[field] = combined

    # --- Field name remapping for known agent variations ---

    # Clinical agent: "medical_necessity_determination" → extract clinical_summary
    if "medical_necessity_determination" in result and isinstance(result["medical_necessity_determination"], dict):
        mnd = result["medical_necessity_determination"]
        if "clinical_summary" not in result:
            factors = mnd.get("supporting_factors", [])
            if isinstance(factors, list) and factors:
                result["clinical_summary"] = "; ".join(str(f) for f in factors)

    # Clinical agent: "code_validation" → split into "diagnosis_validation"
    if "code_validation" in result and isinstance(result["code_validation"], dict):
        cv = result.pop("code_validation")
        if "diagnosis_validation" not in result:
            # Extract diagnosis codes list from code_validation
            for key in ("diagnosis_codes", "validation_results", "codes", "details"):
                if key in cv and isinstance(cv[key], list):
                    result["diagnosis_validation"] = cv[key]
                    break

    # Clinical agent: "diagnosis_code_validation" → "diagnosis_validation"
    if "diagnosis_code_validation" in result and "diagnosis_validation" not in result:
        dcv = result.pop("diagnosis_code_validation")
        if isinstance(dcv, dict):
            for key in ("details", "validation_results", "diagnosis_codes", "codes", "results"):
                if key in dcv and isinstance(dcv[key], list):
                    result["diagnosis_validation"] = dcv[key]
                    break
        elif isinstance(dcv, list):
            result["diagnosis_validation"] = dcv

    # Clinical agent: "diagnosis_codes" as dict keyed by code → "diagnosis_validation" list
    # e.g., {"R91.1": {"valid": true, "description": "..."}, "J18.9": {...}}
    if "diagnosis_codes" in result and isinstance(result["diagnosis_codes"], dict):
        dc = result["diagnosis_codes"]
        if "diagnosis_validation" not in result or not result.get("diagnosis_validation"):
            # Check if it's a code-keyed dict (keys look like ICD-10 codes)
            if all(isinstance(v, dict) for v in dc.values()):
                result["diagnosis_validation"] = [
                    {"code": code, **data} for code, data in dc.items()
                ]

    # Clinical agent: "diagnosis_validation" as summary dict (not a list)
    # e.g., {"codes_validated": 3, "all_valid": true, "clinical_documentation_match": {...}}
    if "diagnosis_validation" in result and isinstance(result["diagnosis_validation"], dict):
        dv = result["diagnosis_validation"]
        # Check if it's a summary dict, not an extractable list
        has_list_key = any(
            isinstance(dv.get(k), list) for k in
            ("validation_results", "diagnosis_codes", "codes", "results", "details")
        )
        if not has_list_key:
            # It's a summary dict — remove it so the model defaults apply
            del result["diagnosis_validation"]

    # Clinical agent: "risk_assessment" or "medical_necessity" data
    if "medical_necessity" in result and isinstance(result["medical_necessity"], dict):
        mn = result["medical_necessity"]
        if "clinical_summary" not in result:
            rationale = mn.get("rationale", [])
            if isinstance(rationale, list):
                result["clinical_summary"] = "; ".join(str(r) for r in rationale)
            elif isinstance(rationale, str):
                result["clinical_summary"] = rationale

    # Clinical agent: "medical_necessity_assessment" → extract clinical_summary
    if "medical_necessity_assessment" in result and isinstance(result["medical_necessity_assessment"], dict):
        mna = result["medical_necessity_assessment"]
        if "clinical_summary" not in result:
            # Try clinical_justification.primary_indicators for a summary
            cj = mna.get("clinical_justification", {})
            if isinstance(cj, dict):
                indicators = cj.get("primary_indicators", [])
                if isinstance(indicators, list) and indicators:
                    parts = [
                        f"{ind.get('indicator', '')}: {ind.get('evidence', '')}"
                        for ind in indicators if isinstance(ind, dict)
                    ]
                    if parts:
                        result["clinical_summary"] = "; ".join(parts)
            # Fallback: try justification list directly
            if "clinical_summary" not in result:
                justification = mna.get("justification", mna.get("rationale", []))
                if isinstance(justification, list) and justification:
                    result["clinical_summary"] = "; ".join(str(j) for j in justification)
                elif isinstance(justification, str) and justification:
                    result["clinical_summary"] = justification

    # Clinical/Coverage agent: "final_determination" → extract clinical_summary fallback
    if "final_determination" in result and isinstance(result["final_determination"], dict):
        fd = result["final_determination"]
        if "clinical_summary" not in result:
            rationale = fd.get("rationale", fd.get("determination_rationale", []))
            if isinstance(rationale, list) and rationale:
                result["clinical_summary"] = "; ".join(str(r) for r in rationale)
            elif isinstance(rationale, str):
                result["clinical_summary"] = rationale

    # Clinical agent: "recommendation" dict → extract clinical_summary
    if "recommendation" in result and isinstance(result["recommendation"], dict):
        rec = result["recommendation"]
        if "clinical_summary" not in result:
            rationale = rec.get("rationale", rec.get("notes", []))
            if isinstance(rationale, list) and rationale:
                result["clinical_summary"] = "; ".join(str(r) for r in rationale)
            elif isinstance(rationale, str):
                result["clinical_summary"] = rationale

    # Clinical agent: "clinical_review_decision" → extract clinical_summary
    if "clinical_review_decision" in result and isinstance(result["clinical_review_decision"], dict):
        crd = result["clinical_review_decision"]
        if "clinical_summary" not in result:
            rationale = crd.get("rationale", crd.get("summary", ""))
            if isinstance(rationale, str) and rationale:
                result["clinical_summary"] = rationale
            elif isinstance(rationale, list) and rationale:
                result["clinical_summary"] = "; ".join(str(r) for r in rationale)

    # Clinical agent: "malignancy_risk_assessment" → extract clinical_summary
    if "malignancy_risk_assessment" in result and isinstance(result["malignancy_risk_assessment"], dict):
        mra = result["malignancy_risk_assessment"]
        if "clinical_summary" not in result:
            risk_factors = mra.get("risk_factors_present", [])
            prob = mra.get("calculated_malignancy_probability", {})
            rec = mra.get("recommendation", "")
            parts = []
            if isinstance(risk_factors, list):
                parts.extend(str(r) for r in risk_factors[:5])
            elif isinstance(risk_factors, dict):
                parts.extend(f"{k}: {v}" for k, v in list(risk_factors.items())[:5])
            if isinstance(prob, dict):
                parts.append(f"Malignancy probability: {prob.get('qualitative', '')} ({prob.get('estimated_range', '')})")
            if isinstance(rec, str) and rec:
                parts.append(rec)
            if parts:
                result["clinical_summary"] = "; ".join(parts)

    # Coverage agent: "final_assessment" or "overall_assessment" → extract clinical_summary fallback
    for fa_key in ("final_assessment", "overall_assessment"):
        if fa_key in result and isinstance(result[fa_key], dict):
            fa = result[fa_key]
            if "clinical_summary" not in result:
                rationale = fa.get("rationale", fa.get("determination_rationale", ""))
                if isinstance(rationale, list) and rationale:
                    result["clinical_summary"] = "; ".join(str(r) for r in rationale)
                elif isinstance(rationale, str) and rationale:
                    result["clinical_summary"] = rationale
            break

    # Coverage agent: "coverage_policy_analysis" → extract policies
    if "coverage_policy_analysis" in result and isinstance(result["coverage_policy_analysis"], dict):
        cpa = result.pop("coverage_policy_analysis")
        if "coverage_policies" not in result or not result["coverage_policies"]:
            all_policies = []
            # Extract NCD policies
            ncds = cpa.get("national_coverage_determinations", {})
            if isinstance(ncds, dict):
                for ncd_key in ("relevant_ncds", "related_ncds", "related_ncds_reviewed", "ncds", "policies", "applicable_ncds", "applicable_general_ncds"):
                    items = ncds.get(ncd_key, [])
                    if isinstance(items, list) and items:
                        for item in items:
                            if isinstance(item, dict):
                                item.setdefault("type", "NCD")
                                if "ncd_id" in item and "policy_id" not in item:
                                    item["policy_id"] = item["ncd_id"]
                        all_policies.extend(items)
                        break
            # Extract LCD policies
            lcds = cpa.get("local_coverage_determinations", {})
            if isinstance(lcds, dict):
                for lcd_key in ("applicable_lcds", "relevant_policies", "relevant_lcds", "related_lcds", "related_lcds_reviewed", "lcds", "policies"):
                    items = lcds.get(lcd_key, [])
                    if isinstance(items, list) and items:
                        for item in items:
                            if isinstance(item, dict):
                                item.setdefault("type", "LCD")
                                if "lcd_id" in item and "policy_id" not in item:
                                    item["policy_id"] = item["lcd_id"]
                        all_policies.extend(items)
                        break
            if all_policies:
                result["coverage_policies"] = all_policies

    # Coverage agent: "coverage_policies_searched" → extract NCD + LCD lists
    if "coverage_policies_searched" in result and isinstance(result["coverage_policies_searched"], dict):
        cps = result.pop("coverage_policies_searched")
        if "coverage_policies" not in result or not result["coverage_policies"]:
            all_policies = []
            for policy_key in ("national_coverage_determinations", "local_coverage_determinations"):
                items = cps.get(policy_key, [])
                if isinstance(items, list):
                    # Tag each policy with type (NCD or LCD)
                    policy_type = "NCD" if "national" in policy_key else "LCD"
                    for item in items:
                        if isinstance(item, dict) and "type" not in item:
                            item["type"] = policy_type
                    all_policies.extend(items)
            if all_policies:
                result["coverage_policies"] = all_policies

    # Coverage agent: "coverage_policy_search" → extract NCD + LCD lists
    # Agent nests policies under national_coverage_determinations.relevant_ncds
    # and local_coverage_determinations.related_lcds
    if "coverage_policy_search" in result and isinstance(result["coverage_policy_search"], dict):
        cps = result.pop("coverage_policy_search")
        # Agent may nest under "policies_searched" intermediate key
        if "policies_searched" in cps and isinstance(cps["policies_searched"], dict):
            cps = cps["policies_searched"]
        if "coverage_policies" not in result or not result["coverage_policies"]:
            all_policies = []
            # Extract NCDs from various nested structures
            ncd_section = cps.get("national_coverage_determinations", {})
            if isinstance(ncd_section, dict):
                for ncd_key in ("relevant_ncds", "ncds", "policies", "applicable_ncds", "applicable_general_ncds"):
                    items = ncd_section.get(ncd_key, [])
                    if isinstance(items, list) and items:
                        for item in items:
                            if isinstance(item, dict):
                                item.setdefault("type", "NCD")
                                # Normalize field names
                                if "ncd_id" in item and "policy_id" not in item:
                                    item["policy_id"] = item["ncd_id"]
                        all_policies.extend(items)
                        break
            # Extract LCDs
            lcd_section = cps.get("local_coverage_determinations", {})
            if isinstance(lcd_section, dict):
                for lcd_key in ("related_lcds", "related_lcds_reviewed", "relevant_lcds", "lcds", "policies"):
                    items = lcd_section.get(lcd_key, [])
                    if isinstance(items, list) and items:
                        for item in items:
                            if isinstance(item, dict):
                                item.setdefault("type", "LCD")
                                if "lcd_id" in item and "policy_id" not in item:
                                    item["policy_id"] = item["lcd_id"]
                        all_policies.extend(items)
                        break
            if all_policies:
                result["coverage_policies"] = all_policies

    # Coverage agent: "criteria_evaluation" or "criteria_mapping" → "criteria_assessment"
    for criteria_key in ("criteria_evaluation", "criteria_mapping"):
        if criteria_key in result and "criteria_assessment" not in result:
            ce = result.pop(criteria_key)
            if isinstance(ce, dict):
                # Try known list keys first
                for key in ("criteria", "assessment_criteria", "individual_criteria",
                             "medical_necessity_criteria", "criteria_details"):
                    if key in ce and isinstance(ce[key], list):
                        result["criteria_assessment"] = ce[key]
                        break
                else:
                    # Fallback: combine all nested lists
                    sub_lists = [v for v in ce.values() if isinstance(v, list)]
                    if sub_lists:
                        combined = []
                        for sl in sub_lists:
                            combined.extend(sl)
                        if combined:
                            result["criteria_assessment"] = combined
            elif isinstance(ce, list):
                result["criteria_assessment"] = ce
            break

    # Coverage agent: "coverage_criteria_assessment" → "criteria_assessment"
    # Agent wraps criteria in coverage_criteria_assessment.criteria_evaluation
    if "coverage_criteria_assessment" in result and isinstance(result["coverage_criteria_assessment"], dict):
        cca = result.pop("coverage_criteria_assessment")
        if "criteria_assessment" not in result or not result.get("criteria_assessment"):
            for key in ("criteria_evaluation", "criteria", "assessment_criteria", "criteria_details"):
                if key in cca and isinstance(cca[key], list):
                    result["criteria_assessment"] = cca[key]
                    break

    # Coverage agent: "medical_necessity_criteria_assessment" → "criteria_assessment"
    if "medical_necessity_criteria_assessment" in result and isinstance(result["medical_necessity_criteria_assessment"], dict):
        mnca = result.pop("medical_necessity_criteria_assessment")
        if "criteria_assessment" not in result or not result.get("criteria_assessment"):
            for key in ("criteria_details", "criteria_evaluation", "criteria", "assessment_criteria"):
                if key in mnca and isinstance(mnca[key], list):
                    result["criteria_assessment"] = mnca[key]
                    break

    # Coverage agent: "medical_necessity_criteria_mapping" → "criteria_assessment"
    if "medical_necessity_criteria_mapping" in result and isinstance(result["medical_necessity_criteria_mapping"], dict):
        mncm = result.pop("medical_necessity_criteria_mapping")
        if "criteria_assessment" not in result or not result.get("criteria_assessment"):
            for key in ("criteria_evaluation", "criteria", "assessment_criteria",
                         "medical_necessity_criteria", "criteria_details"):
                if key in mncm and isinstance(mncm[key], list):
                    result["criteria_assessment"] = mncm[key]
                    break

    # Coverage agent: "coverage_summary_matrix" → fallback criteria_assessment
    # Agent may include a compact summary matrix with criterion list
    if "coverage_summary_matrix" in result and isinstance(result["coverage_summary_matrix"], dict):
        csm = result["coverage_summary_matrix"]
        if "criteria_assessment" not in result or not result.get("criteria_assessment"):
            criteria_list = csm.get("criterion", csm.get("criteria", []))
            if isinstance(criteria_list, list) and criteria_list:
                result["criteria_assessment"] = criteria_list

    # Coverage agent: "documentation_gap_analysis" → extract gaps into "documentation_gaps"
    if "documentation_gap_analysis" in result and isinstance(result["documentation_gap_analysis"], dict):
        dga = result.pop("documentation_gap_analysis")
        if "documentation_gaps" not in result or not result.get("documentation_gaps"):
            all_gaps = []
            for gap_key in ("critical_gaps", "moderate_gaps", "minor_gaps", "gaps", "gaps_identified"):
                gaps = dga.get(gap_key, [])
                if isinstance(gaps, list):
                    all_gaps.extend(gaps)
            if all_gaps:
                result["documentation_gaps"] = all_gaps

    # Agent may also put documentation_gaps directly as a dict with sub-categories
    if "documentation_gaps" in result and isinstance(result["documentation_gaps"], dict):
        dg = result["documentation_gaps"]
        all_gaps = []
        for gap_key in ("critical_gaps", "moderate_gaps", "minor_gaps", "gaps"):
            gaps = dg.get(gap_key, [])
            if isinstance(gaps, list):
                all_gaps.extend(gaps)
        if all_gaps:
            result["documentation_gaps"] = all_gaps
        else:
            # If no sub-category keys found, the _LIST_EXTRACT_KEYS fallback
            # should have already handled it — clean up the dict
            result["documentation_gaps"] = []

    # Coverage agent: "provider_details" nested inside "provider_verification"
    if "provider_verification" in result and isinstance(result["provider_verification"], dict):
        pv = result["provider_verification"]
        if "provider_details" in pv and isinstance(pv["provider_details"], dict):
            pd = pv["provider_details"]
            if "name" not in pv and "name" in pd:
                pv["name"] = pd["name"]
            if "status" not in pv and "status" in pd:
                pv["status"] = pd["status"]
        if "specialty" in pv and isinstance(pv["specialty"], dict):
            spec = pv["specialty"]
            pv["specialty"] = spec.get("primary_taxonomy_description",
                                       spec.get("description", str(spec)))

    # Fields that should be list[str] — coerce str→[str] and dict→str(dict)
    _STR_LIST_FIELDS = {
        "prior_treatments", "severity_indicators", "functional_limitations",
        "diagnostic_findings", "missing_items", "additional_info_requests",
        "coverage_criteria_met", "coverage_criteria_not_met",
        "policy_references", "coverage_limitations", "evidence",
        "data_sources",
    }
    for key in _STR_LIST_FIELDS:
        if key in result:
            result[key] = _coerce_str_list(result[key])

    # Fields that should be int — coerce "85%" or 0.85 float
    for key in ("extraction_confidence", "confidence", "extraction_confidence",
                "assessment_confidence"):
        if key in result and not isinstance(result[key], int):
            result[key] = _coerce_int(result[key])

    # Fields that should be bool — coerce "Yes"/"true"/etc.
    for key in ("valid", "billable", "critical", "relevant", "met"):
        if key in result and not isinstance(result[key], bool):
            result[key] = _coerce_bool(result[key])

    # DiagnosisValidation: "short_description" / "long_description" → "description"
    if "description" not in result:
        for alias in ("short_description", "long_description"):
            if alias in result and isinstance(result[alias], str):
                result["description"] = result.pop(alias)
                break

    # DiagnosisValidation field aliases: validation_status → valid, valid_for_hipaa/hipaa_compliant → billable
    # exists → valid (agent uses "exists" instead of "valid")
    if "exists" in result and "valid" not in result:
        result["valid"] = _coerce_bool(result.pop("exists"))
    if "validation_status" in result and "valid" not in result:
        result["valid"] = str(result.pop("validation_status")).upper() == "VALID"
    if "valid_for_hipaa" in result and "billable" not in result:
        result["billable"] = _coerce_bool(result.pop("valid_for_hipaa"))
    if "hipaa_compliant" in result and "billable" not in result:
        result["billable"] = _coerce_bool(result.pop("hipaa_compliant"))

    # --- Field aliasing — agents may use different names for the same field ---
    # NOTE: aliasing must be context-aware since _sanitize_agent_data runs
    # recursively on all dicts (tool_results, criteria, gaps, etc.)

    # DocumentationGap: "what" is required but agent may return "description"
    # or "gap", "gap_description", "finding", "issue"
    # IMPORTANT: Only apply this aliasing to dicts that look like documentation
    # gaps — NOT to DiagnosisValidation, CoveragePolicy, LiteratureReference,
    # or other models that legitimately use "description" as a field name.
    if "what" not in result:
        # A documentation gap dict typically has "critical" or "request" fields,
        # and does NOT have fields from other model types (code, valid, billable,
        # policy_id, pmid, nct_id, npi, tool_name, confidence, etc.)
        _NON_GAP_FIELDS = {
            "code", "valid", "billable", "policy_id", "pmid", "nct_id",
            "npi", "tool_name", "confidence", "evidence", "specialty",
            "title", "relevance", "authors", "journal",
        }
        is_gap_like = (
            any(k in result for k in ("critical", "request", "gap_type", "severity"))
            or not any(k in result for k in _NON_GAP_FIELDS)
        )
        if is_gap_like:
            for alias in ("description", "gap", "gap_description", "finding", "issue"):
                if alias in result:
                    result["what"] = result.pop(alias)
                    break

    # ChecklistItem: "item" is expected but agent may use "name" or "check"
    # Only match if status is a checklist-specific value (not pass/fail/MET which are tool/criterion values)
    if "item" not in result:
        checklist_statuses = {"complete", "incomplete", "missing", "present", "absent"}
        status_val = str(result.get("status", "")).lower()
        is_checklist_like = status_val in checklist_statuses and not any(
            k in result for k in ("confidence", "evidence", "met", "notes", "tool_name")
        )
        if is_checklist_like:
            for alias in ("name", "check", "requirement", "label"):
                if alias in result:
                    result["item"] = result.pop(alias)
                    break

    # CriterionAssessment: "criterion" — only remap "name" if dict looks like
    # a criterion (has confidence/evidence/met fields, not a tool result or provider)
    if "criterion" not in result:
        is_provider_like = any(k in result for k in ("npi", "specialty", "provider_name", "credentials", "practice_location", "license_info", "enumeration_date"))
        is_criterion_like = (
            any(k in result for k in ("confidence", "evidence", "met", "notes"))
            and not is_provider_like
        )
        aliases = ["criteria_name", "criterion_name", "criteria", "requirement"]
        if is_criterion_like:
            aliases.insert(0, "name")  # Only use "name" for criterion-like dicts
        for alias in aliases:
            if alias in result:
                result["criterion"] = result.pop(alias)
                break

    # DocumentationGap: "criticality" → "critical" boolean
    if "critical" not in result and "criticality" in result:
        crit_val = str(result.pop("criticality")).upper()
        result["critical"] = crit_val in ("CRITICAL", "HIGH", "SEVERE")

    # CriterionAssessment: "notes" aliases
    if "notes" not in result:
        for alias in ("clinical_support", "rationale", "justification"):
            if alias in result and isinstance(result[alias], str):
                result["notes"] = result.pop(alias)
                break

    # CriterionAssessment: "evidence" — normalize to list[str]
    # The schema expects list[str]. Agent may return dict, str, list[dict], or list[str].
    if "evidence" in result:
        ev = result["evidence"]
        if isinstance(ev, dict):
            findings = ev.get("supporting_findings", [])
            if isinstance(findings, list) and findings:
                result["evidence"] = [str(f) for f in findings]
            else:
                result["evidence"] = [str(ev)]
        elif isinstance(ev, str):
            result["evidence"] = [ev] if ev else []
        elif isinstance(ev, list):
            # Keep as list[str] — convert any non-str items
            result["evidence"] = [
                str(item) if not isinstance(item, str) else item
                for item in ev
            ]

    # CriterionAssessment: normalize non-standard statuses
    if "status" in result and isinstance(result["status"], str):
        status_upper = result["status"].upper()
        if status_upper in ("NOT_APPLICABLE", "N/A"):
            result["status"] = "MET"  # Treat N/A as MET for scoring

    # ToolResult: "tool_name" — only remap "name" if dict looks like a tool
    # result (has detail or status but NOT criterion-specific or provider-specific fields)
    if "tool_name" not in result:
        is_provider_like = any(k in result for k in ("npi", "specialty", "provider_name", "credentials", "practice_location", "license_info", "enumeration_date"))
        is_tool_like = not is_provider_like and (
            "detail" in result or ("status" in result and not any(
                k in result for k in ("confidence", "evidence", "met", "notes")
            ))
        )
        aliases = ["tool"]
        if is_tool_like:
            aliases.insert(0, "name")  # Only use "name" for tool-like dicts
        for alias in aliases:
            if alias in result:
                result["tool_name"] = result.pop(alias)
                break

    # CoveragePolicy: "policy_id" is expected but agent may use "id" or "document_id"
    if "policy_id" not in result:
        for alias in ("id", "document_id", "ncd_id", "lcd_id", "display_id"):
            if alias in result:
                result["policy_id"] = result.pop(alias)
                break

    # LiteratureReference: "pmid" may be absent or returned as "id" or "pubmed_id"
    if "pmid" not in result:
        for alias in ("id", "pubmed_id", "article_id"):
            if alias in result:
                result["pmid"] = str(result.pop(alias))
                break

    # ClinicalTrialReference: "nct_id" may be "id" or "trial_id"
    if "nct_id" not in result:
        for alias in ("id", "trial_id"):
            if alias in result:
                result["nct_id"] = str(result.pop(alias))
                break

    # ClinicalResult: "clinical_summary" may be returned as "summary"
    # (only alias if this looks like a clinical result, not a top-level synthesis)
    if "clinical_summary" not in result and "summary" in result:
        has_clinical_fields = any(
            k in result for k in (
                "diagnosis_validation", "clinical_extraction",
                "literature_support", "clinical_trials",
            )
        )
        if has_clinical_fields:
            result["clinical_summary"] = result.pop("summary")

    # Recursively sanitize known nested dicts
    # Also handle case where agent returns a string instead of a dict
    # For clinical_extraction, map structured agent output to text fields
    if "clinical_extraction" in result and isinstance(result["clinical_extraction"], dict):
        ce = result["clinical_extraction"]
        # Unwrap "extracted_data", "key_findings", or "primary_findings" wrapper if present
        if "extracted_data" in ce and isinstance(ce["extracted_data"], dict):
            ed = ce.pop("extracted_data")
            for k, v in ed.items():
                if k not in ce:
                    ce[k] = v
        if "key_findings" in ce and isinstance(ce["key_findings"], dict):
            kf = ce.pop("key_findings")
            for k, v in kf.items():
                if k not in ce:
                    ce[k] = v
        if "primary_findings" in ce and isinstance(ce["primary_findings"], dict):
            pf = ce.pop("primary_findings")
            for k, v in pf.items():
                if k not in ce:
                    ce[k] = v
        # demographics → chief_complaint (e.g., "68-year-old Male")
        if "demographics" in ce and isinstance(ce["demographics"], dict):
            demo = ce.pop("demographics")
            if not ce.get("chief_complaint"):
                parts = []
                if demo.get("age"):
                    parts.append(f"{demo['age']}-year-old")
                if demo.get("sex"):
                    parts.append(str(demo["sex"]).lower())
                if parts:
                    ce["chief_complaint"] = " ".join(parts)
        # risk_factors → severity_indicators + history_of_present_illness
        if "risk_factors" in ce and isinstance(ce["risk_factors"], dict):
            rf = ce.pop("risk_factors")
            indicators = []
            hpi_parts = []
            for rf_key, rf_val in rf.items():
                if isinstance(rf_val, dict):
                    parts = []
                    for k, v in rf_val.items():
                        if k == "confidence":
                            continue
                        if isinstance(v, (str, int, float, bool)):
                            parts.append(f"{k}: {v}")
                    desc = f"{rf_key}: {', '.join(parts)}" if parts else rf_key
                    indicators.append(desc)
                    hpi_parts.append(desc)
                elif isinstance(rf_val, (str, int, float)):
                    indicators.append(f"{rf_key}: {rf_val}")
            if indicators and not ce.get("severity_indicators"):
                ce["severity_indicators"] = indicators
            if hpi_parts and not ce.get("history_of_present_illness"):
                ce["history_of_present_illness"] = "; ".join(hpi_parts)
        if "patient_characteristics" in ce and isinstance(ce["patient_characteristics"], dict):
            pc = ce.pop("patient_characteristics")
            for k, v in pc.items():
                if k not in ce:
                    ce[k] = v
        # Map agent structured sub-keys to flat text fields the model expects
        # presenting_symptoms → severity_indicators (handle list OR dict)
        if "presenting_symptoms" in ce:
            ps = ce["presenting_symptoms"]
            symptoms_list = []
            if isinstance(ps, list):
                symptoms_list = ps
            elif isinstance(ps, dict):
                # Dict of {symptom_name: {duration: ..., ...}}
                for sname, sdata in ps.items():
                    if isinstance(sdata, dict):
                        desc_parts = [sname]
                        for sk, sv in sdata.items():
                            if isinstance(sv, (str, int, float)):
                                desc_parts.append(f"{sk}: {sv}")
                        symptoms_list.append({"symptom": sname, "detail": ", ".join(desc_parts)})
                    else:
                        symptoms_list.append({"symptom": sname, "detail": str(sdata)})
            if symptoms_list:
                if not ce.get("severity_indicators"):
                    ce["severity_indicators"] = [
                        s.get("symptom", s.get("detail", str(s))) if isinstance(s, dict) else str(s)
                        for s in symptoms_list
                    ]
                if not ce.get("chief_complaint"):
                    first = symptoms_list[0]
                    ce["chief_complaint"] = first.get("symptom", str(first)) if isinstance(first, dict) else str(first)
                if not ce.get("duration_and_progression"):
                    dur_parts = []
                    for s in symptoms_list:
                        if isinstance(s, dict) and s.get("duration"):
                            dur_parts.append(f"{s.get('symptom', '?')}: {s['duration']}")
                        elif isinstance(s, dict) and s.get("detail"):
                            dur_parts.append(s["detail"])
                    if dur_parts:
                        ce["duration_and_progression"] = "; ".join(dur_parts)
        # risk_factors / patient_risk_factors → history_of_present_illness
        for rf_key in ("risk_factors", "patient_risk_factors"):
            if rf_key in ce and isinstance(ce[rf_key], dict):
                rf = ce[rf_key]
                rp = []
                smoking = rf.get("smoking_history")
                if isinstance(smoking, dict) and smoking:
                    rp.append(f"Smoking: {smoking.get('status', 'unknown')}, {smoking.get('pack_years', '?')} pack-years, quit {smoking.get('quit_duration', '?')}")
                elif rf.get("smoking_pack_years"):
                    rp.append(f"Smoking: {rf['smoking_pack_years']} pack-years")
                if rf.get("age_risk"):
                    rp.append(f"Age risk: {rf['age_risk']}")
                elif rf.get("age"):
                    rp.append(f"Age: {rf['age']}")
                if rf.get("hemoptysis"):
                    rp.append("Hemoptysis: present")
                if rp and not ce.get("history_of_present_illness"):
                    ce["history_of_present_illness"] = "; ".join(rp)
                break
        # Extract diagnostic_findings from structured data unconditionally
        # (imaging, PFTs, labs, nodule_characteristics, procedural_safety → diagnostic_findings list)
        # nodule_characteristics → diagnostic_findings + chief_complaint
        if "nodule_characteristics" in ce and isinstance(ce["nodule_characteristics"], dict):
            nc = ce["nodule_characteristics"]
            nc_desc = ", ".join(f"{k}: {v}" for k, v in nc.items()
                               if isinstance(v, (str, int, float)))
            if nc_desc:
                ce.setdefault("diagnostic_findings", [])
                if isinstance(ce["diagnostic_findings"], list):
                    ce["diagnostic_findings"].append(f"Nodule: {nc_desc}")
                if not ce.get("chief_complaint"):
                    ce["chief_complaint"] = f"Pulmonary nodule: {nc.get('size', nc.get('size_cm', nc.get('size_current_cm', nc.get('size_current', ''))))} {nc.get('morphology', '')}, {nc.get('location', '')}".strip(", ")
        # procedural_safety → diagnostic_findings
        if "procedural_safety" in ce and isinstance(ce["procedural_safety"], dict):
            ps_data = ce["procedural_safety"]
            ps_parts = []
            for k, v in ps_data.items():
                if isinstance(v, (str, int, float)):
                    ps_parts.append(f"{k}: {v}")
            if ps_parts:
                ce.setdefault("diagnostic_findings", [])
                if isinstance(ce["diagnostic_findings"], list):
                    ce["diagnostic_findings"].append(f"Safety: {', '.join(ps_parts)}")
        # pet_ct_findings → diagnostic_findings
        if "pet_ct_findings" in ce and isinstance(ce["pet_ct_findings"], dict):
            pet = ce["pet_ct_findings"]
            pet_parts = [f"{k}: {v}" for k, v in pet.items()
                         if isinstance(v, (str, int, float, bool))]
            if pet_parts:
                ce.setdefault("diagnostic_findings", [])
                if isinstance(ce["diagnostic_findings"], list):
                    ce["diagnostic_findings"].append(f"PET/CT: {', '.join(pet_parts)}")
        # vital_signs → diagnostic_findings
        if "vital_signs" in ce and isinstance(ce["vital_signs"], dict):
            vs = ce["vital_signs"]
            vs_parts = [f"{k}: {v}" for k, v in vs.items()
                        if isinstance(v, (str, int, float))]
            if vs_parts:
                ce.setdefault("diagnostic_findings", [])
                if isinstance(ce["diagnostic_findings"], list):
                    ce["diagnostic_findings"].append(f"Vitals: {', '.join(vs_parts)}")
        if "imaging_findings" in ce and isinstance(ce["imaging_findings"], dict):
            img = ce["imaging_findings"]
            # Imaging may have nested dicts (ct_chest: {...}, pet_ct: {...})
            img_parts = []
            for img_key, img_val in img.items():
                if isinstance(img_val, dict):
                    sub_desc = ", ".join(f"{k}: {v}" for k, v in img_val.items()
                                        if isinstance(v, (str, int, float)))
                    if sub_desc:
                        img_parts.append(f"{img_key}: {sub_desc}")
                elif isinstance(img_val, (str, int, float)):
                    img_parts.append(f"{img_key}: {img_val}")
            if img_parts:
                ce.setdefault("diagnostic_findings", [])
                if isinstance(ce["diagnostic_findings"], list):
                    ce["diagnostic_findings"].append("Imaging: " + "; ".join(img_parts))
        for pft_key in ("pulmonary_function", "pulmonary_function_tests"):
            if pft_key in ce and isinstance(ce[pft_key], dict):
                pf = ce[pft_key]
                # May have nested "results" dict
                if "results" in pf and isinstance(pf["results"], dict):
                    pf = pf["results"]
                pf_desc = ", ".join(f"{k}: {v}" for k, v in pf.items()
                                   if isinstance(v, (str, int, float)))
                if pf_desc:
                    ce.setdefault("diagnostic_findings", [])
                    if isinstance(ce["diagnostic_findings"], list):
                        ce["diagnostic_findings"].append(f"PFTs: {pf_desc}")
                break
        if "laboratory_values" in ce and isinstance(ce["laboratory_values"], dict):
            labs = ce["laboratory_values"]
            lab_parts = []
            # Handle nested "results" list of {test, value, unit} dicts
            if "results" in labs and isinstance(labs["results"], list):
                for item in labs["results"]:
                    if isinstance(item, dict) and "test" in item:
                        val = item.get("value", "")
                        unit = item.get("unit", "")
                        lab_parts.append(f"{item['test']}: {val} {unit}".strip())
            else:
                for lab_name, lab_data in labs.items():
                    if isinstance(lab_data, dict) and "value" in lab_data:
                        lab_parts.append(f"{lab_name}: {lab_data['value']}")
                    elif isinstance(lab_data, (str, int, float)):
                        lab_parts.append(f"{lab_name}: {lab_data}")
            if lab_parts:
                ce.setdefault("diagnostic_findings", [])
                if isinstance(ce["diagnostic_findings"], list):
                    ce["diagnostic_findings"].append(f"Labs: {', '.join(lab_parts)}")
        # prior_treatment(s) as dict → prior_treatments list
        for pt_key in ("prior_treatment", "prior_treatments"):
            if pt_key in ce and isinstance(ce[pt_key], dict):
                pt = ce[pt_key]
                treatments = []
                # Handle antibiotic_trial sub-dict
                if "antibiotic_trial" in pt and isinstance(pt["antibiotic_trial"], dict):
                    trial = pt["antibiotic_trial"]
                    desc = f"{trial.get('medication', trial.get('drug', ''))}"
                    if trial.get("duration_days"):
                        desc += f" x {trial['duration_days']} days"
                    if trial.get("response"):
                        desc += f" — {trial['response']}"
                    if desc.strip():
                        treatments.append(desc.strip())
                else:
                    desc = f"{pt.get('antibiotic_trial', pt.get('treatment', ''))}"
                    if pt.get("response"):
                        desc += f" — {pt['response']}"
                    if desc.strip():
                        treatments.append(desc.strip())
                if treatments:
                    ce["prior_treatments"] = treatments
                    if pt_key != "prior_treatments":
                        ce.pop(pt_key, None)
                break
        # Rename singular → plural if still present
        if "prior_treatment" in ce and "prior_treatments" not in ce:
            ce["prior_treatments"] = ce.pop("prior_treatment")
            if isinstance(ce["prior_treatments"], str):
                ce["prior_treatments"] = [ce["prior_treatments"]]
        # medications → prior_treatments fallback
        if "medications" in ce and isinstance(ce["medications"], list):
            if not ce.get("prior_treatments"):
                ce["prior_treatments"] = ce["medications"]
        # comorbidities → functional_limitations
        if "comorbidities" in ce and isinstance(ce["comorbidities"], list):
            if not ce.get("functional_limitations"):
                fl = []
                for c_item in ce["comorbidities"]:
                    if isinstance(c_item, dict):
                        desc = c_item.get("condition", "")
                        if c_item.get("severity"):
                            desc += f" ({c_item['severity']})"
                        if desc:
                            fl.append(desc)
                    elif isinstance(c_item, str):
                        fl.append(c_item)
                if fl:
                    ce["functional_limitations"] = fl
        # physical_exam_findings → severity_indicators fallback
        if "physical_exam_findings" in ce and isinstance(ce["physical_exam_findings"], list):
            if not ce.get("severity_indicators"):
                ce["severity_indicators"] = [str(f) for f in ce["physical_exam_findings"]]
        # patient_demographics → chief_complaint enrichment
        if "patient_demographics" in ce and isinstance(ce["patient_demographics"], dict):
            pd = ce["patient_demographics"]
            demo_parts = []
            if pd.get("age_years"):
                demo_parts.append(f"{pd['age_years']}-year-old")
            if pd.get("sex"):
                demo_parts.append(pd["sex"].lower())
            if demo_parts and not ce.get("chief_complaint"):
                ce["chief_complaint"] = " ".join(demo_parts)
        # imaging_dates → duration_and_progression
        if "imaging_dates" in ce and isinstance(ce["imaging_dates"], dict):
            if not ce.get("duration_and_progression"):
                dates = ce["imaging_dates"]
                date_parts = [f"{k}: {v}" for k, v in dates.items()
                              if isinstance(v, str)]
                if date_parts:
                    ce["duration_and_progression"] = "; ".join(date_parts)
        # If text fields are still empty, synthesize from structured data
        _TEXT_FIELDS = ("chief_complaint", "history_of_present_illness",
                        "duration_and_progression")
        has_text_fields = any(ce.get(f) for f in _TEXT_FIELDS)
        if not has_text_fields:
            # Build text representations from structured data
            parts = []
            if "patient_history" in ce and isinstance(ce["patient_history"], dict):
                ph = ce["patient_history"]
                hist_parts = []
                if ph.get("smoking_status"):
                    hist_parts.append(f"Smoking: {ph['smoking_status']}")
                if ph.get("smoking_pack_years"):
                    hist_parts.append(f"{ph['smoking_pack_years']} pack-years")
                if ph.get("symptoms") and isinstance(ph["symptoms"], list):
                    ce.setdefault("severity_indicators", ph["symptoms"])
                    hist_parts.append(f"Symptoms: {', '.join(str(s) for s in ph['symptoms'])}")
                if hist_parts:
                    ce.setdefault("history_of_present_illness", "; ".join(hist_parts))
        result["clinical_extraction"] = _sanitize_agent_data(ce)
    elif "clinical_extraction" in result and isinstance(result["clinical_extraction"], str):
        del result["clinical_extraction"]

    # Provider verification — sanitize nested dict or discard string
    for nested_key in ("provider_verification",):
        if nested_key in result and isinstance(result[nested_key], dict):
            pv = result[nested_key]
            # Map agent field names to model fields
            if "provider_name" in pv and "name" not in pv:
                pv["name"] = pv.pop("provider_name")
            # Extract name from nested provider_details
            if "provider_details" in pv and isinstance(pv["provider_details"], dict):
                pd = pv["provider_details"]
                if "name" not in pv and "name" in pd:
                    pv["name"] = pd["name"]
                if "status" not in pv and "status" in pd:
                    pv["status"] = pd["status"]
            if "primary_specialty" in pv and isinstance(pv["primary_specialty"], dict):
                spec = pv["primary_specialty"]
                if "description" in spec and "specialty" not in pv:
                    pv["specialty"] = spec["description"]
            elif "primary_specialty" in pv and isinstance(pv["primary_specialty"], str):
                if "specialty" not in pv or not pv.get("specialty"):
                    pv["specialty"] = pv["primary_specialty"]
            # Also handle "primary_taxonomy" (agent uses this name sometimes)
            if "primary_taxonomy" in pv and isinstance(pv["primary_taxonomy"], dict):
                pt = pv["primary_taxonomy"]
                if ("specialty" not in pv or not pv.get("specialty")) and "description" in pt:
                    pv["specialty"] = pt["description"]
            # Extract specialty from specialty_verification
            if "specialty_verification" in pv and isinstance(pv["specialty_verification"], dict):
                sv = pv["specialty_verification"]
                if "specialty" not in pv or not pv.get("specialty"):
                    pv["specialty"] = sv.get("primary_taxonomy_description",
                                             sv.get("description", ""))
            if "enumeration_status" in pv and "status" not in pv:
                pv["status"] = pv.pop("enumeration_status")
            result[nested_key] = _sanitize_agent_data(pv)
        elif nested_key in result and isinstance(result[nested_key], str):
            del result[nested_key]

    # Convert literature_support strings to LiteratureReference-like dicts
    # Agent may return key_findings as list[str] instead of list[dict]
    if "literature_support" in result and isinstance(result["literature_support"], list):
        result["literature_support"] = [
            {"title": item, "relevance": "Supporting evidence"} if isinstance(item, str)
            else item
            for item in result["literature_support"]
        ]

    # Convert clinical_trials NCT ID strings to ClinicalTrialReference-like dicts
    # Agent may return high_relevance_trials as list[str] of NCT IDs
    if "clinical_trials" in result and isinstance(result["clinical_trials"], list):
        result["clinical_trials"] = [
            {"nct_id": item, "title": item, "status": "Recruiting"} if isinstance(item, str)
            else item
            for item in result["clinical_trials"]
        ]

    # Convert documentation_gaps strings or dicts with non-standard keys
    if "documentation_gaps" in result and isinstance(result["documentation_gaps"], list):
        normalized_gaps = []
        for g in result["documentation_gaps"]:
            if isinstance(g, str):
                normalized_gaps.append({"what": g, "critical": False})
            elif isinstance(g, dict):
                # Handle "criticality" field → "critical" boolean
                if "critical" not in g and "criticality" in g:
                    crit_val = str(g.get("criticality", "")).upper()
                    g["critical"] = crit_val in ("CRITICAL", "HIGH", "SEVERE")
                # Handle "description" → "what" aliasing
                if "what" not in g:
                    for alias in ("description", "gap", "gap_description"):
                        if alias in g:
                            g["what"] = g.pop(alias)
                            break
                # Handle "recommendation" → "request" aliasing
                if "request" not in g and "recommendation" in g:
                    g["request"] = g.pop("recommendation")
                normalized_gaps.append(g)
        result["documentation_gaps"] = normalized_gaps

    # Recursively sanitize known list-of-dict fields
    # Also filter out non-dict items (agents sometimes put strings in lists of objects)
    for list_key in ("diagnosis_validation", "criteria_assessment",
                     "documentation_gaps", "coverage_policies",
                     "literature_support", "clinical_trials",
                     "checklist", "tool_results", "checks_performed"):
        if list_key in result and isinstance(result[list_key], list):
            result[list_key] = [
                _sanitize_agent_data(item) if isinstance(item, dict) else item
                for item in result[list_key]
                if isinstance(item, dict)
            ]
        elif list_key in result and isinstance(result[list_key], dict):
            # Agent returned a single dict instead of a list — wrap it
            result[list_key] = [_sanitize_agent_data(result[list_key])]

    return result


def _coerce_str_list(value) -> list:
    """Coerce value to list[str]."""
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [
            str(item) if not isinstance(item, str) else item
            for item in value
        ]
    return []


def _coerce_int(value) -> int:
    """Coerce value to int, handling strings like '85%' and floats."""
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        # Likely 0.0-1.0 scale: convert to 0-100
        if 0.0 < value <= 1.0:
            return round(value * 100)
        return round(value)
    if isinstance(value, str):
        digits = "".join(c for c in value if c.isdigit() or c == ".")
        if digits:
            try:
                return round(float(digits))
            except ValueError:
                pass
    return 0


def _coerce_bool(value) -> bool:
    """Coerce various truthy/falsy values to bool."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "yes", "1", "pass", "met", "active")
    return bool(value)
