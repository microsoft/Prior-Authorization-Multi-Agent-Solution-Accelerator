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
    # Generate checks_performed from RAW data before Pydantic parsing
    # so the checks survive even if detailed field parsing fails
    agent_raw = result.get("agent_results", {})

    compliance_raw = agent_raw.get("compliance")
    if isinstance(compliance_raw, dict):
        compliance_raw["checks_performed"] = _generate_compliance_checks(compliance_raw)

    clinical_raw = agent_raw.get("clinical")
    if isinstance(clinical_raw, dict):
        clinical_raw["checks_performed"] = _generate_clinical_checks(clinical_raw)

    coverage_raw = agent_raw.get("coverage")
    if isinstance(coverage_raw, dict):
        coverage_raw["checks_performed"] = _generate_coverage_checks(coverage_raw)

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
    item = _find_item("patient")
    r, d = _item_result(item)
    checks.append({"rule": "Patient Information", "result": r, "detail": d or "Name and DOB check"})

    # SKILL.md Rule 2: Provider NPI
    item = _find_item("provider", "npi")
    r, d = _item_result(item)
    checks.append({"rule": "Provider NPI", "result": r, "detail": d or "NPI format check (10 digits)"})

    # SKILL.md Rule 3: Insurance ID (non-blocking)
    item = _find_item("insurance id", "insurance_id", "member id")
    r, d = _item_result(item)
    if r == "fail":
        r = "info"  # Non-blocking per SKILL.md
    checks.append({"rule": "Insurance ID (non-blocking)", "result": r, "detail": d or "Insurance ID presence"})

    # SKILL.md Rule 4: Diagnosis Codes
    item = _find_item("diagnosis", "icd")
    r, d = _item_result(item)
    checks.append({"rule": "Diagnosis Codes", "result": r, "detail": d or "ICD-10 code format check"})

    # SKILL.md Rule 5: Procedure Codes
    item = _find_item("procedure", "cpt", "hcpcs")
    r, d = _item_result(item)
    checks.append({"rule": "Procedure Codes", "result": r, "detail": d or "CPT/HCPCS code presence"})

    # SKILL.md Rule 6: Clinical Notes Presence
    item = _find_item("notes presence", "clinical notes pres", "notes pres")
    if item is None:
        # Fall back to generic "clinical notes" match
        item = _find_item("clinical note")
    r, d = _item_result(item)
    checks.append({"rule": "Clinical Notes Presence", "result": r, "detail": d or "Substantive clinical narrative check"})

    # SKILL.md Rule 7: Clinical Notes Quality
    item = _find_item("notes quality", "quality")
    r, d = _item_result(item)
    checks.append({"rule": "Clinical Notes Quality", "result": r, "detail": d or "Notes detail, boilerplate/copy-paste check"})

    # SKILL.md Rule 8: Insurance Plan Type (non-blocking)
    item = _find_item("plan type", "insurance type", "insurance plan")
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
            "Chief Complaint": extraction.get("chief_complaint", ""),
            "History of Present Illness": extraction.get("history_of_present_illness", ""),
            "Prior Treatments": extraction.get("prior_treatments", []),
            "Severity Indicators": extraction.get("severity_indicators", []),
            "Functional Limitations": extraction.get("functional_limitations", []),
            "Diagnostic Findings": extraction.get("diagnostic_findings", []),
            "Duration and Progression": extraction.get("duration_and_progression", ""),
            "Medical History / Comorbidities": extraction.get("medical_history", extraction.get("comorbidities", "")),
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
    if isinstance(criteria, list):
        for c in criteria:
            if not isinstance(c, dict):
                continue
            crit_name = str(c.get("criterion", c.get("name", ""))).lower()
            if "alignment" in crit_name or "diagnosis-policy" in crit_name or "diagnosis policy" in crit_name:
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

    Three-stage approach:
    1. Sanitize (field aliasing + type coercion) then validate whole model
    2. Field-by-field fallback — try each field individually, skip failures
    3. Minimal fallback (preserves agent_name and error fields)

    Sanitization always runs first because models use defaults for all fields,
    so direct validation would succeed with empty values for misnamed fields.
    """
    if not data or not isinstance(data, dict):
        return None

    # Always sanitize first to handle field aliasing and type coercion
    try:
        sanitized = _sanitize_agent_data(data)
        return model_class.model_validate(sanitized)
    except Exception as e:
        logger.warning("Parse %s failed (stage 1): %s", model_class.__name__, e)
        logger.info("Parse %s data keys: %s", model_class.__name__, list(data.keys()))

    # Stage 2: Field-by-field fallback — try each field individually
    # This preserves data that parses correctly even if one field is bad
    try:
        sanitized = _sanitize_agent_data(data)
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

    # --- Field aliasing — agents may use different names for the same field ---
    # NOTE: aliasing must be context-aware since _sanitize_agent_data runs
    # recursively on all dicts (tool_results, criteria, gaps, etc.)

    # DocumentationGap: "what" is required but agent may return "description"
    # or "gap", "gap_description", "finding", "issue"
    if "what" not in result:
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
    # a criterion (has confidence/evidence/met fields, not a tool result)
    if "criterion" not in result:
        is_criterion_like = any(k in result for k in ("confidence", "evidence", "met", "notes"))
        aliases = ["criteria_name", "criteria", "requirement"]
        if is_criterion_like:
            aliases.insert(0, "name")  # Only use "name" for criterion-like dicts
        for alias in aliases:
            if alias in result:
                result["criterion"] = result.pop(alias)
                break

    # ToolResult: "tool_name" — only remap "name" if dict looks like a tool
    # result (has detail or status but NOT criterion-specific or provider-specific fields)
    if "tool_name" not in result:
        is_provider_like = any(k in result for k in ("npi", "specialty", "provider_name"))
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
        for alias in ("id", "document_id", "ncd_id", "lcd_id"):
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
    for nested_key in ("clinical_extraction", "provider_verification"):
        if nested_key in result and isinstance(result[nested_key], dict):
            result[nested_key] = _sanitize_agent_data(result[nested_key])
        elif nested_key in result and isinstance(result[nested_key], str):
            # Agent returned a string summary instead of structured dict — discard
            # so the model uses its default (None)
            del result[nested_key]

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
