"""API routes for prior authorization review."""

import uuid

from fastapi import APIRouter, HTTPException

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
)
from app.agents.orchestrator import (
    run_multi_agent_review,
    store_review,
    get_review,
    list_reviews,
)

router = APIRouter()


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

    # Parse merged tool_results from all agents
    tool_results = []
    for tr in result.get("tool_results", []):
        tool_results.append({
            "tool_name": tr.get("tool_name", "unknown"),
            "status": tr.get("status", "warning"),
            "detail": tr.get("detail", ""),
        })

    # Parse per-agent results (best-effort — agent JSON may not match exactly)
    agent_raw = result.get("agent_results", {})
    agent_results = AgentResults(
        compliance=_safe_parse(ComplianceResult, agent_raw.get("compliance")),
        clinical=_safe_parse(ClinicalResult, agent_raw.get("clinical")),
        coverage=_safe_parse(CoverageResult, agent_raw.get("coverage")),
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

    response = ReviewResponse(
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
    )

    # Persist for later retrieval and decision-making
    store_review(request_id, request.model_dump(), response.model_dump())

    return response


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


def _safe_parse(model_class, data):
    """Attempt to parse a dict into a Pydantic model, return None on failure."""
    if not data or isinstance(data, str):
        return None
    try:
        return model_class(**data) if isinstance(data, dict) else None
    except Exception:
        return None
