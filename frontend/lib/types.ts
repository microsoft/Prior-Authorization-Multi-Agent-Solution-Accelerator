export interface PriorAuthRequest {
  patient_name: string;
  patient_dob: string;
  provider_npi: string;
  diagnosis_codes: string[];
  procedure_codes: string[];
  clinical_notes: string;
  insurance_id?: string;
}

export interface ToolResult {
  tool_name: string;
  status: "pass" | "fail" | "warning";
  detail: string;
}

// --- Per-agent result types ---

export interface AgentCheck {
  rule: string;
  result: "pass" | "fail" | "warning" | "info";
  detail: string;
}

export interface ChecklistItem {
  item: string;
  status: "complete" | "incomplete" | "missing";
  detail: string;
}

export interface ComplianceResult {
  agent_name: string;
  checks_performed: AgentCheck[];
  checklist: ChecklistItem[];
  overall_status: "complete" | "incomplete";
  missing_items: string[];
  additional_info_requests: string[];
  error?: string;
}

export interface DiagnosisValidation {
  code: string;
  valid: boolean;
  description: string;
  billable: boolean;
}

export interface ClinicalExtraction {
  chief_complaint: string;
  history_of_present_illness: string;
  prior_treatments: string[];
  severity_indicators: string[];
  functional_limitations: string[];
  diagnostic_findings: string[];
  duration_and_progression: string;
  extraction_confidence: number; // 0-100
}

export interface LiteratureReference {
  title: string;
  pmid: string;
  relevance: string;
}

export interface ClinicalTrialReference {
  nct_id: string;
  title: string;
  status: string;
  relevance: string;
}

export interface ClinicalResult {
  agent_name: string;
  checks_performed: AgentCheck[];
  diagnosis_validation: DiagnosisValidation[];
  clinical_extraction?: ClinicalExtraction;
  literature_support: LiteratureReference[];
  clinical_trials: ClinicalTrialReference[];
  clinical_summary: string;
  tool_results: ToolResult[];
  error?: string;
}

export interface ProviderVerification {
  npi: string;
  name: string;
  specialty: string;
  status: "active" | "inactive" | "not_found";
  detail: string;
}

export interface CoveragePolicy {
  policy_id: string;
  title: string;
  type: "LCD" | "NCD";
  relevant: boolean;
}

export interface CriterionAssessment {
  criterion: string;
  status: "MET" | "NOT_MET" | "INSUFFICIENT";
  confidence: number; // 0-100
  evidence: string[];
  notes: string;
  source: string;
  met: boolean;
}

export interface DocumentationGap {
  what: string;
  critical: boolean;
  request: string;
}

export interface CoverageResult {
  agent_name: string;
  checks_performed: AgentCheck[];
  provider_verification?: ProviderVerification;
  coverage_policies: CoveragePolicy[];
  criteria_assessment: CriterionAssessment[];
  coverage_criteria_met: string[];
  coverage_criteria_not_met: string[];
  policy_references: string[];
  coverage_limitations: string[];
  documentation_gaps: DocumentationGap[];
  tool_results: ToolResult[];
  error?: string;
}

export interface AgentResults {
  compliance?: ComplianceResult;
  clinical?: ClinicalResult;
  coverage?: CoverageResult;
}

export interface AuditTrail {
  data_sources: string[];
  review_started: string;
  review_completed: string;
  extraction_confidence: number;
  assessment_confidence: number;
  criteria_met_count: string; // "N/M" format
}

export interface ReviewResponse {
  request_id: string;
  recommendation: "approve" | "pend_for_review";
  confidence: number;
  confidence_level: string; // "HIGH" | "MEDIUM" | "LOW"
  summary: string;
  tool_results: ToolResult[];
  clinical_rationale: string;
  coverage_criteria_met: string[];
  coverage_criteria_not_met: string[];
  missing_documentation: string[];
  documentation_gaps: DocumentationGap[];
  policy_references: string[];
  disclaimer: string;
  agent_results?: AgentResults;
  audit_trail?: AuditTrail;
  audit_justification?: string;
  audit_justification_pdf?: string;
}

// --- Progress tracking types (SSE streaming) ---

export type PhaseId =
  | "preflight"
  | "phase_1"
  | "phase_2"
  | "phase_3"
  | "phase_4";

export type AgentId =
  | "compliance"
  | "clinical"
  | "coverage"
  | "synthesis";

export type AgentStatus = "pending" | "running" | "done" | "error";

export interface AgentProgress {
  status: AgentStatus;
  detail: string;
}

export interface ProgressEvent {
  phase: PhaseId;
  status: "running" | "completed";
  progress_pct: number;
  message: string;
  agents: Partial<Record<AgentId, AgentProgress>>;
}

export interface ReviewProgress {
  currentPhase: PhaseId;
  progressPct: number;
  message: string;
  agents: Record<AgentId, AgentProgress>;
  phases: Record<PhaseId, "pending" | "running" | "completed">;
  error?: string;
}

// --- Decision & Notification types ---

export interface DecisionRequest {
  request_id: string;
  action: "accept" | "override";
  override_recommendation?: "approve" | "pend_for_review";
  override_rationale?: string;
  reviewer_name: string;
  reviewer_id?: string;
}

export interface NotificationLetter {
  authorization_number: string;
  letter_type: "approval" | "pend";
  effective_date: string;
  expiration_date?: string;
  patient_name: string;
  provider_name: string;
  body_text: string;
  appeal_rights?: string;
  documentation_deadline?: string;
  pdf_base64?: string;
}

export interface DecisionResponse {
  request_id: string;
  authorization_number: string;
  final_recommendation: "approve" | "pend_for_review";
  decided_by: string;
  decided_at: string;
  was_overridden: boolean;
  letter: NotificationLetter;
}
