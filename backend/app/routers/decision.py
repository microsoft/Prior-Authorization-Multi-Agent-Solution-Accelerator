"""Decision and notification endpoint for prior authorization review."""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from app.models.schemas import DecisionRequest, DecisionResponse, NotificationLetter
from app.agents.orchestrator import get_review, store_decision
from app.services.notification import (
    generate_authorization_number,
    generate_approval_letter,
    generate_pend_letter,
    generate_letter_pdf,
)

router = APIRouter()


@router.post("/decision", response_model=DecisionResponse)
async def submit_decision(request: DecisionRequest):
    """Accept or override the AI recommendation and generate a notification letter.

    Requires that the review has already been completed (request_id must exist
    in the review store). Generates a notification letter (approval or pend)
    and persists the decision record.
    """
    stored = get_review(request.request_id)
    if not stored:
        raise HTTPException(
            status_code=404,
            detail=f"Review {request.request_id} not found",
        )

    if stored.get("decision"):
        raise HTTPException(
            status_code=409,
            detail="Decision already recorded for this review",
        )

    review_response = stored["response"]
    request_data = stored["request_data"]

    # Determine final recommendation
    if request.action == "accept":
        final_recommendation = review_response["recommendation"]
    elif request.action == "override":
        if not request.override_recommendation:
            raise HTTPException(
                status_code=422,
                detail="override_recommendation required when action is 'override'",
            )
        if request.override_recommendation not in ("approve", "pend_for_review"):
            raise HTTPException(
                status_code=422,
                detail="override_recommendation must be 'approve' or 'pend_for_review'",
            )
        final_recommendation = request.override_recommendation
    else:
        raise HTTPException(
            status_code=422,
            detail="action must be 'accept' or 'override'",
        )

    # Generate authorization number
    auth_number = generate_authorization_number()

    # Extract provider name from coverage agent results
    provider_name = "Provider"
    agent_results = review_response.get("agent_results", {})
    if agent_results:
        coverage = agent_results.get("coverage") or {}
        pv = coverage.get("provider_verification") or {}
        if isinstance(pv, dict) and pv.get("name"):
            provider_name = pv["name"]

    # Common kwargs for letter generation
    common_kwargs = {
        "authorization_number": auth_number,
        "patient_name": request_data.get("patient_name", ""),
        "patient_dob": request_data.get("patient_dob", ""),
        "provider_name": provider_name,
        "provider_npi": request_data.get("provider_npi", ""),
        "procedure_codes": request_data.get("procedure_codes", []),
        "diagnosis_codes": request_data.get("diagnosis_codes", []),
        "summary": review_response.get("summary", ""),
    }

    # Generate notification letter
    if final_recommendation == "approve":
        letter_dict = generate_approval_letter(**common_kwargs)
    else:
        letter_dict = generate_pend_letter(
            **common_kwargs,
            missing_documentation=review_response.get("missing_documentation", []),
            documentation_gaps=[
                g if isinstance(g, dict) else {}
                for g in review_response.get("documentation_gaps", [])
            ],
        )

    # Enrich letter_dict with fields needed for PDF rendering
    letter_dict["patient_dob"] = request_data.get("patient_dob", "")
    letter_dict["provider_npi"] = request_data.get("provider_npi", "")
    letter_dict["procedure_codes"] = request_data.get("procedure_codes", [])
    letter_dict["diagnosis_codes"] = request_data.get("diagnosis_codes", [])
    letter_dict["summary"] = review_response.get("summary", "")
    if final_recommendation != "approve":
        letter_dict["missing_documentation"] = review_response.get("missing_documentation", [])
        letter_dict["documentation_gaps"] = [
            g if isinstance(g, dict) else {}
            for g in review_response.get("documentation_gaps", [])
        ]

    # Generate PDF
    letter_dict["pdf_base64"] = generate_letter_pdf(letter_dict)

    decided_at = datetime.now(timezone.utc).isoformat()

    # Build and persist decision record
    decision_record = {
        "request_id": request.request_id,
        "authorization_number": auth_number,
        "final_recommendation": final_recommendation,
        "decided_by": request.reviewer_name,
        "decided_at": decided_at,
        "was_overridden": request.action == "override",
        "override_rationale": request.override_rationale,
        "letter": letter_dict,
    }

    store_decision(request.request_id, decision_record)

    return DecisionResponse(
        request_id=request.request_id,
        authorization_number=auth_number,
        final_recommendation=final_recommendation,
        decided_by=request.reviewer_name,
        decided_at=decided_at,
        was_overridden=request.action == "override",
        letter=NotificationLetter(**letter_dict),
    )
