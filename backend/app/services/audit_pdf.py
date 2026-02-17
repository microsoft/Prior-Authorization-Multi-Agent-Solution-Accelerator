"""Audit Justification PDF generation for prior authorization reviews.

Produces a professional, color-coded PDF with 8 sections matching the
markdown audit justification document. Uses fpdf2 (already a project
dependency via notification.py).

Returns base64-encoded PDF bytes for JSON transport.
"""

import base64
import io
from datetime import datetime, timezone

from fpdf import FPDF


# ---------------------------------------------------------------------------
# Color palette
# ---------------------------------------------------------------------------
_BLUE = (0, 70, 140)
_LIGHT_BLUE_FILL = (220, 235, 250)
_GREEN_FILL = (212, 237, 218)
_GREEN_TEXT = (25, 135, 84)
_AMBER_FILL = (255, 243, 205)
_AMBER_TEXT = (133, 100, 4)
_RED_TEXT = (180, 0, 0)
_GRAY_ROW = (248, 249, 250)
_GRAY_TEXT = (100, 100, 100)
_LIGHT_GRAY_TEXT = (150, 150, 150)
_BLACK = (0, 0, 0)
_WHITE = (255, 255, 255)


class _AuditPDF(FPDF):
    """Custom FPDF subclass for audit justification documents."""

    def header(self) -> None:
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(*_GRAY_TEXT)
        self.cell(
            0, 6,
            "PRIOR AUTHORIZATION REVIEW -- AUDIT JUSTIFICATION",
            align="C",
        )
        self.ln(4)
        self.set_draw_color(*_BLUE)
        self.set_line_width(0.5)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(6)

    def footer(self) -> None:
        self.set_y(-20)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(*_LIGHT_GRAY_TEXT)
        self.cell(0, 4, "AI-ASSISTED DRAFT -- REVIEW REQUIRED", align="C")
        self.ln(3)
        self.cell(
            0, 4,
            f"Page {self.page_no()}/{{nb}}",
            align="C",
        )


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _section_heading(pdf: FPDF, number: int, title: str) -> None:
    """Render a numbered section heading with blue underline."""
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*_BLUE)
    pdf.cell(0, 8, f"{number}. {title}")
    pdf.ln(2)
    pdf.set_draw_color(*_BLUE)
    pdf.set_line_width(0.3)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(4)
    pdf.set_text_color(*_BLACK)


def _kv(pdf: FPDF, key: str, value: str, bold_value: bool = False) -> None:
    """Render a key-value pair."""
    pdf.set_x(10)  # Reset to left margin
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(50, 6, f"{key}:")
    pdf.set_font("Helvetica", "B" if bold_value else "", 9)
    pdf.cell(0, 6, _safe_str(value))
    pdf.ln(5)


def _bullet(pdf: FPDF, text: str) -> None:
    """Render a bullet point."""
    pdf.set_font("Helvetica", "", 9)
    pdf.set_x(10)  # Reset to left margin
    pdf.cell(5, 5, "-")
    pdf.multi_cell(0, 5, _safe_str(text))
    pdf.set_x(10)  # Reset after multi_cell


def _decision_badge(pdf: FPDF, recommendation: str) -> None:
    """Render a colored decision badge."""
    is_approve = recommendation.lower() in ("approve", "approved")
    fill = _GREEN_FILL if is_approve else _AMBER_FILL
    text = "APPROVE" if is_approve else "PEND FOR REVIEW"

    pdf.set_fill_color(*fill)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(*_BLACK)
    pdf.cell(0, 10, f"Decision: {text}", align="C", fill=True)
    pdf.ln(8)


def _confidence_bar(pdf: FPDF, value: float, level: str) -> None:
    """Render a simple confidence bar with percentage."""
    bar_width = 60
    bar_height = 6
    x = 10  # left margin
    y = pdf.get_y()

    # Background
    pdf.set_fill_color(230, 230, 230)
    pdf.rect(x, y, bar_width, bar_height, "F")

    # Fill
    pct = max(0.0, min(1.0, value))
    if pct >= 0.8:
        pdf.set_fill_color(*_GREEN_TEXT)
    elif pct >= 0.5:
        pdf.set_fill_color(*_AMBER_TEXT)
    else:
        pdf.set_fill_color(*_RED_TEXT)
    pdf.rect(x, y, bar_width * pct, bar_height, "F")

    # Label — at x=73, well within right margin at x=200
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(*_BLACK)
    pdf.set_xy(x + bar_width + 3, y)
    pdf.cell(40, bar_height, f"{int(pct * 100)}% ({level})")
    pdf.ln(8)


def _table_header(pdf: FPDF, columns: list[tuple[str, int]]) -> None:
    """Render a table header row with blue background."""
    pdf.set_fill_color(*_LIGHT_BLUE_FILL)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(*_BLUE)
    for label, width in columns:
        pdf.cell(width, 7, label, border=1, fill=True)
    pdf.ln()
    pdf.set_text_color(*_BLACK)


def _table_row(
    pdf: FPDF,
    cells: list[tuple[str, int]],
    row_index: int,
    status_col: int | None = None,
) -> None:
    """Render a table data row with alternating background."""
    if row_index % 2 == 1:
        pdf.set_fill_color(*_GRAY_ROW)
    else:
        pdf.set_fill_color(*_WHITE)

    pdf.set_font("Helvetica", "", 8)
    for i, (text, width) in enumerate(cells):
        # Color-code status columns
        if status_col is not None and i == status_col:
            val = text.upper().strip()
            if val == "MET" or val == "YES":
                pdf.set_text_color(*_GREEN_TEXT)
                pdf.set_font("Helvetica", "B", 8)
            elif val == "NOT_MET" or val == "NO":
                pdf.set_text_color(*_RED_TEXT)
                pdf.set_font("Helvetica", "B", 8)
            elif val == "INSUFFICIENT":
                pdf.set_text_color(*_AMBER_TEXT)
                pdf.set_font("Helvetica", "B", 8)

        pdf.cell(width, 6, _safe_str(text)[:60], border=1, fill=True)

        # Reset after status column
        if status_col is not None and i == status_col:
            pdf.set_text_color(*_BLACK)
            pdf.set_font("Helvetica", "", 8)

    pdf.ln()


def _safe_str(value) -> str:
    """Convert value to string, replacing characters unsupported by Helvetica."""
    if value is None:
        return "N/A"
    s = str(value)
    # Replace Unicode characters not in the Helvetica (Latin-1) character set
    s = s.replace("\u2014", "--")   # em dash
    s = s.replace("\u2013", "-")    # en dash
    s = s.replace("\u2018", "'")    # left single quote
    s = s.replace("\u2019", "'")    # right single quote
    s = s.replace("\u201c", '"')    # left double quote
    s = s.replace("\u201d", '"')    # right double quote
    s = s.replace("\u2022", "-")    # bullet
    s = s.replace("\u2026", "...")  # ellipsis
    # Catch-all: replace any remaining non-Latin-1 chars with '?'
    s = s.encode("latin-1", errors="replace").decode("latin-1")
    return s


def _check_page_space(pdf: FPDF, needed: float) -> None:
    """Add a new page if insufficient space remains."""
    if pdf.get_y() + needed > pdf.h - 25:
        pdf.add_page()


# ---------------------------------------------------------------------------
# Main PDF generator
# ---------------------------------------------------------------------------

def generate_audit_justification_pdf(
    request_data: dict,
    synthesis: dict,
    compliance_result: dict,
    clinical_result: dict,
    coverage_result: dict,
    audit_trail: dict,
) -> str:
    """Generate a professional audit justification PDF.

    Args:
        request_data: Original prior auth request data.
        synthesis: Orchestrator synthesis output (recommendation, confidence, etc.).
        compliance_result: Compliance agent output.
        clinical_result: Clinical reviewer agent output.
        coverage_result: Coverage agent output.
        audit_trail: Audit trail metadata dict.

    Returns:
        Base64-encoded PDF string.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    recommendation = synthesis.get("recommendation", "pend_for_review")
    confidence = synthesis.get("confidence", 0)
    confidence_level = synthesis.get("confidence_level", "LOW")

    pdf = _AuditPDF()
    pdf.alias_nb_pages()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=25)

    # --- Disclaimer banner ---
    pdf.set_fill_color(*_AMBER_FILL)
    pdf.set_font("Helvetica", "BI", 8)
    pdf.set_text_color(*_AMBER_TEXT)
    pdf.multi_cell(
        0, 4,
        "WARNING: AI-ASSISTED DRAFT -- REVIEW REQUIRED. "
        "All recommendations are drafts requiring human clinical review. "
        "Coverage policies reflect Medicare LCDs/NCDs only. "
        "Commercial and Medicare Advantage plans may differ.",
        fill=True,
    )
    pdf.set_text_color(*_BLACK)
    pdf.ln(6)

    # =================================================================
    # Section 1: Executive Summary
    # =================================================================
    _section_heading(pdf, 1, "Executive Summary")

    _decision_badge(pdf, recommendation)

    _kv(pdf, "Review Date", now)
    _kv(pdf, "Patient", f"{request_data.get('patient_name', 'N/A')} (DOB: {request_data.get('patient_dob', 'N/A')})")
    _kv(pdf, "Provider NPI", request_data.get("provider_npi", "N/A"))
    _kv(pdf, "Insurance ID", request_data.get("insurance_id") or "Not provided")
    _kv(pdf, "Diagnosis Codes", ", ".join(request_data.get("diagnosis_codes", [])))
    _kv(pdf, "Procedure Codes", ", ".join(request_data.get("procedure_codes", [])))

    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 6, "Confidence:")
    pdf.ln(5)
    _confidence_bar(pdf, confidence, confidence_level)

    summary_text = synthesis.get("summary", "N/A")
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 6, "Summary:")
    pdf.ln(5)
    pdf.set_font("Helvetica", "", 9)
    pdf.multi_cell(0, 5, _safe_str(summary_text))
    pdf.ln(4)

    # =================================================================
    # Section 2: Medical Necessity Assessment
    # =================================================================
    _check_page_space(pdf, 40)
    _section_heading(pdf, 2, "Medical Necessity Assessment")

    # Provider info
    pv = coverage_result.get("provider_verification", {})
    if pv and isinstance(pv, dict):
        _kv(pdf, "Provider", f"{pv.get('name', 'N/A')} - {pv.get('specialty', 'N/A')}")
        _kv(pdf, "Provider Status", pv.get("status", "N/A"))

    # Coverage policies
    policies = coverage_result.get("coverage_policies", [])
    if policies:
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(0, 6, "Coverage Policies Applied:")
        pdf.ln(5)
        for p in policies:
            if isinstance(p, dict):
                _bullet(pdf, f"{p.get('policy_id', '?')}: {p.get('title', 'N/A')} ({p.get('type', '?')})")

    # Clinical evidence
    extraction = clinical_result.get("clinical_extraction", {})
    if isinstance(extraction, dict) and extraction:
        pdf.ln(3)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(0, 6, "Clinical Evidence Summary:")
        pdf.ln(5)
        if extraction.get("chief_complaint"):
            _bullet(pdf, f"Chief Complaint: {extraction['chief_complaint']}")
        if extraction.get("prior_treatments"):
            treatments = extraction["prior_treatments"][:5]
            _bullet(pdf, f"Prior Treatments: {'; '.join(treatments)}")
        if extraction.get("severity_indicators"):
            indicators = extraction["severity_indicators"][:5]
            _bullet(pdf, f"Severity Indicators: {'; '.join(indicators)}")
        _kv(pdf, "Extraction Confidence", f"{extraction.get('extraction_confidence', 0)}%")

    # Literature support (PubMed)
    lit = clinical_result.get("literature_support", [])
    if lit and isinstance(lit, list):
        pdf.ln(3)
        _check_page_space(pdf, 20)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(0, 6, "Literature Support (PubMed):")
        pdf.ln(5)
        for ref in lit[:5]:
            if isinstance(ref, dict):
                title = _safe_str(ref.get("title", "Untitled"))
                pmid = ref.get("pmid", "")
                relevance = _safe_str(ref.get("relevance", ""))
                pmid_label = f" (PMID: {pmid})" if pmid else ""
                _bullet(pdf, f"{title}{pmid_label}")
                if relevance:
                    pdf.set_x(15)
                    pdf.set_font("Helvetica", "I", 8)
                    pdf.multi_cell(0, 4, _safe_str(f"Relevance: {relevance}"))
                    pdf.set_font("Helvetica", "", 9)

    # Clinical trials (ClinicalTrials.gov)
    trials = clinical_result.get("clinical_trials", [])
    if trials and isinstance(trials, list):
        pdf.ln(3)
        _check_page_space(pdf, 20)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(0, 6, "Relevant Clinical Trials:")
        pdf.ln(5)
        for trial in trials[:5]:
            if isinstance(trial, dict):
                nct_id = trial.get("nct_id", "")
                title = _safe_str(trial.get("title", "Untitled"))
                status = trial.get("status", "")
                relevance = _safe_str(trial.get("relevance", ""))
                status_label = f" [{status}]" if status else ""
                _bullet(pdf, f"{nct_id}: {title}{status_label}")
                if relevance:
                    pdf.set_x(15)
                    pdf.set_font("Helvetica", "I", 8)
                    pdf.multi_cell(0, 4, _safe_str(f"Relevance: {relevance}"))
                    pdf.set_font("Helvetica", "", 9)

    pdf.ln(3)

    # =================================================================
    # Section 3: Criterion-by-Criterion Evaluation
    # =================================================================
    _check_page_space(pdf, 40)
    _section_heading(pdf, 3, "Criterion-by-Criterion Evaluation")

    criteria = coverage_result.get("criteria_assessment", [])
    if criteria:
        met_count = audit_trail.get("criteria_met_count", "0/0")
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(0, 6, f"Criteria Met: {met_count}")
        pdf.ln(6)

        # Table: Criterion | Status | Confidence | Evidence
        col_widths = [60, 22, 22, 86]
        columns = [
            ("Criterion", col_widths[0]),
            ("Status", col_widths[1]),
            ("Confidence", col_widths[2]),
            ("Key Evidence", col_widths[3]),
        ]
        _table_header(pdf, columns)

        for idx, c in enumerate(criteria):
            if not isinstance(c, dict):
                continue
            _check_page_space(pdf, 8)
            status = c.get("status", "INSUFFICIENT")
            conf = f"{c.get('confidence', 0)}%"
            evidence = c.get("evidence", [])
            evidence_text = "; ".join(evidence[:2]) if isinstance(evidence, list) else str(evidence)
            _table_row(
                pdf,
                [
                    (_safe_str(c.get("criterion", "N/A")), col_widths[0]),
                    (status, col_widths[1]),
                    (conf, col_widths[2]),
                    (evidence_text[:58], col_widths[3]),
                ],
                idx,
                status_col=1,
            )
    else:
        pdf.set_font("Helvetica", "I", 9)
        pdf.cell(0, 6, "No coverage criteria were identified for evaluation.")
        pdf.ln(5)

    pdf.ln(4)

    # =================================================================
    # Section 4: Validation Checks
    # =================================================================
    _check_page_space(pdf, 40)
    _section_heading(pdf, 4, "Validation Checks")

    # Provider verification
    if pv and isinstance(pv, dict):
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(0, 6, f"Provider Verification: NPI {pv.get('npi', 'N/A')} - {pv.get('status', 'N/A')}")
        pdf.ln(6)

    # Diagnosis code table
    dx_val = clinical_result.get("diagnosis_validation", [])
    if dx_val:
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(0, 6, "Diagnosis Code Validation:")
        pdf.ln(6)

        dx_cols = [("Code", 25), ("Description", 100), ("Billable", 25), ("Valid", 25)]
        _table_header(pdf, dx_cols)

        for idx, d in enumerate(dx_val):
            if not isinstance(d, dict):
                continue
            _check_page_space(pdf, 8)
            desc = _safe_str(d.get("description", "N/A"))[:55]
            billable = "Yes" if d.get("billable") else "No"
            valid = "Yes" if d.get("valid") else "No"
            _table_row(
                pdf,
                [
                    (d.get("code", "?"), 25),
                    (desc, 100),
                    (billable, 25),
                    (valid, 25),
                ],
                idx,
                status_col=3,
            )
        pdf.ln(4)

    # Compliance checklist
    checklist = compliance_result.get("checklist", [])
    if checklist:
        _check_page_space(pdf, 30)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(0, 6, "Compliance Checklist:")
        pdf.ln(6)

        cl_cols = [("Item", 60), ("Status", 30), ("Detail", 85)]
        _table_header(pdf, cl_cols)

        for idx, item in enumerate(checklist):
            if not isinstance(item, dict):
                continue
            _check_page_space(pdf, 8)
            status = item.get("status", "?")
            _table_row(
                pdf,
                [
                    (_safe_str(item.get("item", "?")), 60),
                    (status, 30),
                    (_safe_str(item.get("detail", ""))[:50], 85),
                ],
                idx,
                status_col=1,
            )
        pdf.ln(4)

    # =================================================================
    # Section 5: Decision Rationale
    # =================================================================
    _check_page_space(pdf, 40)
    _section_heading(pdf, 5, "Decision Rationale")

    _kv(pdf, "Decision", recommendation.upper(), bold_value=True)
    _kv(pdf, "Decision Gate", synthesis.get("decision_gate", "N/A"))
    _kv(pdf, "Confidence", f"{confidence_level} ({int(confidence * 100)}%)")

    pdf.ln(2)
    rationale = synthesis.get("clinical_rationale", "No rationale provided.")
    pdf.set_font("Helvetica", "", 9)
    pdf.multi_cell(0, 5, _safe_str(rationale))
    pdf.ln(3)

    # Supporting facts
    met_criteria = synthesis.get("coverage_criteria_met", [])
    if met_criteria:
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(0, 6, "Key Supporting Facts:")
        pdf.ln(5)
        for m in met_criteria:
            _bullet(pdf, m)
    pdf.ln(3)

    # =================================================================
    # Section 6: Documentation Gaps
    # =================================================================
    gaps = coverage_result.get("documentation_gaps", [])
    missing = synthesis.get("missing_documentation", [])
    if gaps or missing:
        _check_page_space(pdf, 30)
        _section_heading(pdf, 6, "Documentation Gaps")

        for g in gaps:
            if isinstance(g, dict):
                critical = g.get("critical", False)
                label = "[CRITICAL]" if critical else "[Non-critical]"
                pdf.set_x(10)  # Reset to left margin before each gap
                pdf.set_font("Helvetica", "B", 9)
                if critical:
                    pdf.set_text_color(*_RED_TEXT)
                else:
                    pdf.set_text_color(*_AMBER_TEXT)
                pdf.cell(5, 5, "-")
                pdf.cell(25, 5, label)
                pdf.set_text_color(*_BLACK)
                pdf.set_font("Helvetica", "", 9)
                pdf.multi_cell(0, 5, _safe_str(g.get("what", "N/A")))
                if g.get("request"):
                    pdf.set_x(40)
                    pdf.set_font("Helvetica", "I", 8)
                    pdf.multi_cell(0, 4, _safe_str(f"Action: {g['request']}"))
                    pdf.set_font("Helvetica", "", 9)

        for m in missing:
            _bullet(pdf, m)

        pdf.ln(3)

    # =================================================================
    # Section 7: Audit Trail
    # =================================================================
    _check_page_space(pdf, 40)
    _section_heading(pdf, 7, "Audit Trail")

    # Data sources
    data_sources = audit_trail.get("data_sources", [])
    if data_sources:
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(0, 6, "Data Sources:")
        pdf.ln(5)
        for src in data_sources:
            _bullet(pdf, src)
        pdf.ln(3)

    _kv(pdf, "Review Started", audit_trail.get("review_started", "N/A"))
    _kv(pdf, "Review Completed", audit_trail.get("review_completed", "N/A"))
    _kv(pdf, "Extraction Confidence", f"{audit_trail.get('extraction_confidence', 0)}%")
    _kv(pdf, "Assessment Confidence", f"{audit_trail.get('assessment_confidence', 0)}%")
    _kv(pdf, "Criteria Met", audit_trail.get("criteria_met_count", "0/0"))
    pdf.ln(3)

    # =================================================================
    # Section 8: Regulatory Compliance
    # =================================================================
    _check_page_space(pdf, 30)
    _section_heading(pdf, 8, "Regulatory Compliance")

    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 6, "Decision Policy: LENIENT Mode (default)")
    pdf.ln(5)
    pdf.set_font("Helvetica", "", 9)
    _bullet(pdf, "Provider verification: Required")
    _bullet(pdf, "Code validation: Required")
    _bullet(pdf, "Medical necessity criteria: All must be MET for approval")
    _bullet(pdf, "Unmet/insufficient criteria: Results in PEND (not DENY)")
    pdf.ln(4)

    # --- Final disclaimer bar ---
    _check_page_space(pdf, 15)
    pdf.ln(4)
    pdf.set_fill_color(*_AMBER_FILL)
    pdf.set_font("Helvetica", "I", 7)
    pdf.set_text_color(*_AMBER_TEXT)
    pdf.multi_cell(
        0, 4,
        "DISCLAIMER: This is an AI-assisted draft. Coverage policies reflect "
        "Medicare LCDs/NCDs only. If this review is for a commercial or Medicare "
        "Advantage plan, payer-specific policies were not applied. All decisions "
        "require human clinical review before finalization.",
        fill=True,
    )

    # --- Footer line ---
    pdf.set_text_color(*_GRAY_TEXT)
    pdf.set_font("Helvetica", "I", 7)
    pdf.ln(3)
    pdf.cell(
        0, 4,
        f"Generated: {now} | AI-Assisted Prior Authorization Review System",
        align="C",
    )

    # --- Output to base64 ---
    buf = io.BytesIO()
    pdf.output(buf)
    pdf_bytes = buf.getvalue()
    return base64.b64encode(pdf_bytes).decode("ascii")
