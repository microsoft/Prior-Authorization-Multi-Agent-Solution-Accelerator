from pydantic import BaseModel


class PriorAuthRequest(BaseModel):
    patient_name: str
    patient_dob: str
    provider_npi: str
    diagnosis_codes: list[str]  # ICD-10 codes
    procedure_codes: list[str]  # CPT codes
    clinical_notes: str
    insurance_id: str | None = None


class ToolResult(BaseModel):
    tool_name: str = ""
    status: str = "warning"  # "pass", "fail", "warning"
    detail: str = ""


# --- Per-agent result models ---


class AgentCheck(BaseModel):
    """A single rule/check that an agent performed."""
    rule: str = ""
    result: str = "info"  # "pass", "fail", "warning", "info"
    detail: str = ""


class ChecklistItem(BaseModel):
    item: str = ""
    status: str = "incomplete"  # "complete", "incomplete", "missing"
    detail: str = ""


class ComplianceResult(BaseModel):
    agent_name: str = "Compliance Agent"
    checks_performed: list[AgentCheck] = []
    checklist: list[ChecklistItem] = []
    overall_status: str = "incomplete"
    missing_items: list[str] = []
    additional_info_requests: list[str] = []
    error: str | None = None


class DiagnosisValidation(BaseModel):
    code: str = ""
    valid: bool = False
    description: str = ""
    billable: bool = False


class ClinicalExtraction(BaseModel):
    chief_complaint: str = ""
    history_of_present_illness: str = ""
    prior_treatments: list[str] = []
    severity_indicators: list[str] = []
    functional_limitations: list[str] = []
    diagnostic_findings: list[str] = []
    duration_and_progression: str = ""
    extraction_confidence: int = 0  # 0-100 overall extraction confidence


class LiteratureReference(BaseModel):
    title: str = ""
    pmid: str = ""
    relevance: str = ""


class ClinicalTrialReference(BaseModel):
    nct_id: str = ""
    title: str = ""
    status: str = ""
    relevance: str = ""


class ClinicalResult(BaseModel):
    agent_name: str = "Clinical Reviewer Agent"
    checks_performed: list[AgentCheck] = []
    diagnosis_validation: list[DiagnosisValidation] = []
    clinical_extraction: ClinicalExtraction | None = None
    literature_support: list[LiteratureReference] = []
    clinical_trials: list[ClinicalTrialReference] = []
    clinical_summary: str = ""
    tool_results: list[ToolResult] = []
    error: str | None = None


class ProviderVerification(BaseModel):
    npi: str = ""
    name: str = ""
    specialty: str = ""
    status: str = ""  # "active", "inactive", "not_found"
    detail: str = ""


class CoveragePolicy(BaseModel):
    policy_id: str = ""
    title: str = ""
    type: str = ""  # "LCD", "NCD"
    relevant: bool = True


class CriterionAssessment(BaseModel):
    criterion: str = ""
    status: str = "INSUFFICIENT"  # "MET", "NOT_MET", "INSUFFICIENT"
    confidence: int = 0  # 0-100 per-criterion confidence
    evidence: list[str] = []
    notes: str = ""
    source: str = ""
    # Backward compat field
    met: bool = False


class DocumentationGap(BaseModel):
    what: str = ""
    critical: bool = False
    request: str = ""


class CoverageResult(BaseModel):
    agent_name: str = "Coverage Agent"
    checks_performed: list[AgentCheck] = []
    provider_verification: ProviderVerification | None = None
    coverage_policies: list[CoveragePolicy] = []
    criteria_assessment: list[CriterionAssessment] = []
    coverage_criteria_met: list[str] = []
    coverage_criteria_not_met: list[str] = []
    policy_references: list[str] = []
    coverage_limitations: list[str] = []
    documentation_gaps: list[DocumentationGap] = []
    tool_results: list[ToolResult] = []
    error: str | None = None


class AgentResults(BaseModel):
    compliance: ComplianceResult | None = None
    clinical: ClinicalResult | None = None
    coverage: CoverageResult | None = None


class SynthesisOutput(BaseModel):
    """Output schema for the Synthesis Decision Agent.

    Used as structured output format to enforce consistent JSON from the
    synthesis agent. Fields match the keys consumed by the orchestrator
    in run_multi_agent_review().
    """
    recommendation: str = "pend_for_review"  # "approve" or "pend_for_review"
    confidence: float = 0.0
    confidence_level: str = ""  # "HIGH", "MEDIUM", "LOW"
    summary: str = ""
    clinical_rationale: str = ""
    decision_gate: str = ""  # "gate_1_provider", "gate_2_codes", "gate_3_necessity", "approved"
    coverage_criteria_met: list[str] = []
    coverage_criteria_not_met: list[str] = []
    missing_documentation: list[str] = []
    policy_references: list[str] = []
    criteria_summary: str = ""
    disclaimer: str = ""


class AuditTrail(BaseModel):
    data_sources: list[str] = []
    review_started: str = ""
    review_completed: str = ""
    extraction_confidence: int = 0
    assessment_confidence: int = 0
    criteria_met_count: str = ""  # "N/M" format


class ReviewResponse(BaseModel):
    request_id: str
    recommendation: str  # "approve", "pend_for_review"
    confidence: float = 0.0
    confidence_level: str = ""  # "HIGH", "MEDIUM", "LOW"
    summary: str
    tool_results: list[ToolResult]
    clinical_rationale: str
    coverage_criteria_met: list[str] = []
    coverage_criteria_not_met: list[str] = []
    missing_documentation: list[str] = []
    documentation_gaps: list[DocumentationGap] = []
    policy_references: list[str] = []
    disclaimer: str = "AI-assisted draft. Medicare LCDs/NCDs applied. Human review required."
    agent_results: AgentResults | None = None
    audit_trail: AuditTrail | None = None
    audit_justification: str | None = None
    audit_justification_pdf: str | None = None  # Base64-encoded PDF


# --- Decision & Notification models ---


class DecisionRequest(BaseModel):
    """POST /api/decision request body."""
    request_id: str
    action: str  # "accept" or "override"
    override_recommendation: str | None = None  # "approve" or "pend_for_review"
    override_rationale: str | None = None
    reviewer_name: str
    reviewer_id: str | None = None


class NotificationLetter(BaseModel):
    """Generated notification letter content."""
    authorization_number: str
    letter_type: str  # "approval" or "pend"
    effective_date: str
    expiration_date: str | None = None
    patient_name: str
    provider_name: str
    body_text: str
    appeal_rights: str | None = None
    documentation_deadline: str | None = None
    pdf_base64: str | None = None  # Base64-encoded PDF bytes


class DecisionResponse(BaseModel):
    """POST /api/decision response body."""
    request_id: str
    authorization_number: str
    final_recommendation: str  # "approve" or "pend_for_review"
    decided_by: str
    decided_at: str
    was_overridden: bool
    letter: NotificationLetter


class ReviewSummary(BaseModel):
    """Lightweight summary for GET /api/reviews list endpoint."""
    request_id: str
    patient_name: str
    recommendation: str
    confidence_level: str
    reviewed_at: str
    decision_made: bool = False
