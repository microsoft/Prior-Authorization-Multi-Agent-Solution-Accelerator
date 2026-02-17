"""Notification letter generation for prior authorization decisions.

Produces plain-text letters from templates and PDF versions via fpdf2.
Authorization number format: PA-YYYYMMDD-XXXXX (monotonic counter).
"""

import base64
import io
import threading
from datetime import date, timedelta

from fpdf import FPDF

_counter_lock = threading.Lock()
_counter = 0


def generate_authorization_number() -> str:
    """Generate a unique PA authorization number: PA-YYYYMMDD-XXXXX."""
    global _counter
    with _counter_lock:
        _counter += 1
        seq = _counter
    return f"PA-{date.today().strftime('%Y%m%d')}-{seq:05d}"


_DISCLAIMER_HEADER = """\
AI-ASSISTED DRAFT - REVIEW REQUIRED
Coverage policies reflect Medicare LCDs/NCDs only. If this review is for a
commercial or Medicare Advantage plan, payer-specific policies were not applied.
All decisions require human clinical review before finalization."""


def generate_approval_letter(
    authorization_number: str,
    patient_name: str,
    patient_dob: str,
    provider_name: str,
    provider_npi: str,
    procedure_codes: list[str],
    diagnosis_codes: list[str],
    summary: str,
    insurance_id: str = "",
    policy_references: list[str] | None = None,
) -> dict:
    """Generate an APPROVAL notification letter.

    Returns dict matching NotificationLetter schema.
    Approval validity: today -> today + 90 days.
    """
    today = date.today()
    expiration = today + timedelta(days=90)

    insurance_line = f"\n  Insurance ID: {insurance_id}" if insurance_id else ""
    policy_section = ""
    if policy_references:
        refs = "\n".join(f"  - {ref}" for ref in policy_references)
        policy_section = f"\n\nCOVERAGE POLICY REFERENCE:\n{refs}"

    body = f"""{_DISCLAIMER_HEADER}

======================================================
PRIOR AUTHORIZATION APPROVAL NOTIFICATION
======================================================

Authorization Number: {authorization_number}
Date: {today.isoformat()}

Dear {provider_name} (NPI: {provider_npi}),

This letter confirms that the prior authorization request for the following
services has been APPROVED.

PATIENT INFORMATION:
  Name: {patient_name}
  Date of Birth: {patient_dob}{insurance_line}

APPROVED SERVICES:
  Procedure Code(s): {', '.join(procedure_codes)}
  Diagnosis Code(s): {', '.join(diagnosis_codes)}

AUTHORIZATION PERIOD:
  Effective Date:  {today.isoformat()}
  Expiration Date: {expiration.isoformat()}{policy_section}

CLINICAL SUMMARY:
{summary}

TERMS AND CONDITIONS:
This authorization is valid for the services described above during the
authorization period. Services must be rendered within the effective dates.
This authorization does not guarantee payment. Payment is subject to
eligibility verification at the time of service.

If you have questions regarding this authorization, please contact the
utilization management department and reference authorization number
{authorization_number}.

Sincerely,
Utilization Management Department"""

    return {
        "authorization_number": authorization_number,
        "letter_type": "approval",
        "effective_date": today.isoformat(),
        "expiration_date": expiration.isoformat(),
        "patient_name": patient_name,
        "provider_name": provider_name,
        "body_text": body,
        "appeal_rights": None,
        "documentation_deadline": None,
    }


def generate_pend_letter(
    authorization_number: str,
    patient_name: str,
    patient_dob: str,
    provider_name: str,
    provider_npi: str,
    procedure_codes: list[str],
    diagnosis_codes: list[str],
    missing_documentation: list[str],
    documentation_gaps: list[dict],
    summary: str,
    insurance_id: str = "",
    policy_references: list[str] | None = None,
) -> dict:
    """Generate a PEND (request for additional information) notification letter.

    Returns dict matching NotificationLetter schema.
    Documentation deadline: today + 30 days.
    """
    today = date.today()
    deadline = today + timedelta(days=30)

    # Build missing info section
    missing_items = []
    for item in missing_documentation:
        missing_items.append(f"  - {item}")
    for gap in documentation_gaps:
        what = gap.get("what", "")
        request_text = gap.get("request", "")
        critical = gap.get("critical", False)
        label = "REQUIRED" if critical else "Requested"
        missing_items.append(f"  - [{label}] {what}")
        if request_text:
            missing_items.append(f"    Action: {request_text}")

    missing_section = "\n".join(missing_items) if missing_items else "  - Additional clinical documentation"

    insurance_line = f"\n  Insurance ID: {insurance_id}" if insurance_id else ""
    policy_section = ""
    if policy_references:
        refs = "\n".join(f"  - {ref}" for ref in policy_references)
        policy_section = f"\n\nCOVERAGE POLICY REFERENCE:\n{refs}"

    appeal_rights = (
        f"If you disagree with this request for additional information, "
        f"you may submit a written appeal within 30 days of this notice. "
        f"Include the reference number {authorization_number} with all "
        f"correspondence. Documentation deadline: {deadline.isoformat()}."
    )

    body = f"""{_DISCLAIMER_HEADER}

======================================================
PRIOR AUTHORIZATION - REQUEST FOR ADDITIONAL INFORMATION
======================================================

Reference Number: {authorization_number}
Date: {today.isoformat()}

Dear {provider_name} (NPI: {provider_npi}),

The prior authorization request for the following services has been PENDED
pending receipt of additional documentation.

PATIENT INFORMATION:
  Name: {patient_name}
  Date of Birth: {patient_dob}{insurance_line}

REQUESTED SERVICES:
  Procedure Code(s): {', '.join(procedure_codes)}
  Diagnosis Code(s): {', '.join(diagnosis_codes)}{policy_section}

CLINICAL SUMMARY:
{summary}

ADDITIONAL DOCUMENTATION REQUIRED:
{missing_section}

DEADLINE: Please submit the requested documentation by {deadline.isoformat()}.

If the required documentation is not received by the deadline, the request
will be reviewed based on the information currently on file.

APPEAL RIGHTS:
{appeal_rights}

To submit additional documentation, contact the utilization management
department and reference number {authorization_number}.

Sincerely,
Utilization Management Department"""

    return {
        "authorization_number": authorization_number,
        "letter_type": "pend",
        "effective_date": today.isoformat(),
        "expiration_date": None,
        "patient_name": patient_name,
        "provider_name": provider_name,
        "body_text": body,
        "appeal_rights": appeal_rights,
        "documentation_deadline": deadline.isoformat(),
    }


# ---------------------------------------------------------------------------
# PDF generation
# ---------------------------------------------------------------------------

class _LetterPDF(FPDF):
    """Custom FPDF subclass with header/footer for PA letters."""

    def __init__(self, letter_type: str, auth_number: str) -> None:
        super().__init__()
        self._letter_type = letter_type
        self._auth_number = auth_number

    def header(self) -> None:
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(100, 100, 100)
        self.cell(0, 6, "PRIOR AUTHORIZATION — UTILIZATION MANAGEMENT", align="C")
        self.ln(4)
        self.set_draw_color(0, 100, 180)
        self.set_line_width(0.5)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(6)

    def footer(self) -> None:
        self.set_y(-20)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(150, 150, 150)
        self.cell(0, 4, "AI-ASSISTED DRAFT — REVIEW REQUIRED", align="C")
        self.ln(3)
        self.cell(
            0, 4,
            f"Ref: {self._auth_number}  |  Page {self.page_no()}/{{nb}}",
            align="C",
        )


def generate_letter_pdf(letter_dict: dict) -> str:
    """Generate a PDF version of a notification letter and return base64-encoded bytes.

    Args:
        letter_dict: Dict matching the NotificationLetter schema (as returned by
            generate_approval_letter or generate_pend_letter).

    Returns:
        Base64-encoded PDF string (suitable for JSON transport).
    """
    letter_type = letter_dict.get("letter_type", "approval")
    auth_number = letter_dict.get("authorization_number", "")
    patient_name = letter_dict.get("patient_name", "")
    provider_name = letter_dict.get("provider_name", "")
    effective_date = letter_dict.get("effective_date", "")
    expiration_date = letter_dict.get("expiration_date")
    body_text = letter_dict.get("body_text", "")
    appeal_rights = letter_dict.get("appeal_rights")
    doc_deadline = letter_dict.get("documentation_deadline")

    pdf = _LetterPDF(letter_type=letter_type, auth_number=auth_number)
    pdf.alias_nb_pages()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=25)

    # --- Title ---
    if letter_type == "approval":
        pdf.set_fill_color(212, 237, 218)  # green tint
        title_text = "PRIOR AUTHORIZATION APPROVAL NOTIFICATION"
    else:
        pdf.set_fill_color(255, 243, 205)  # amber tint
        title_text = "PRIOR AUTHORIZATION — REQUEST FOR ADDITIONAL INFORMATION"

    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 12, title_text, align="C", fill=True)
    pdf.ln(10)

    # --- Authorization / Reference number ---
    pdf.set_font("Helvetica", "B", 10)
    label = "Authorization Number" if letter_type == "approval" else "Reference Number"
    pdf.cell(55, 7, f"{label}:")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 7, auth_number)
    pdf.ln(6)

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(55, 7, "Date:")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 7, effective_date)
    pdf.ln(10)

    # --- Patient & Provider info ---
    _section_heading(pdf, "PATIENT INFORMATION")
    _kv(pdf, "Name", patient_name)
    _kv(pdf, "Date of Birth", letter_dict.get("patient_dob", ""))
    insurance_id = letter_dict.get("insurance_id", "")
    if insurance_id:
        _kv(pdf, "Insurance ID", insurance_id)
    pdf.ln(4)

    _section_heading(pdf, "PROVIDER INFORMATION")
    _kv(pdf, "Name", provider_name)
    _kv(pdf, "NPI", letter_dict.get("provider_npi", ""))
    pdf.ln(4)

    # --- Codes ---
    procedure_codes = letter_dict.get("procedure_codes", [])
    diagnosis_codes = letter_dict.get("diagnosis_codes", [])
    if procedure_codes or diagnosis_codes:
        heading = "APPROVED SERVICES" if letter_type == "approval" else "REQUESTED SERVICES"
        _section_heading(pdf, heading)
        if procedure_codes:
            _kv(pdf, "Procedure Code(s)", ", ".join(procedure_codes))
        if diagnosis_codes:
            _kv(pdf, "Diagnosis Code(s)", ", ".join(diagnosis_codes))
        pdf.ln(4)

    # --- Policy reference ---
    policy_refs = letter_dict.get("policy_references", [])
    if policy_refs:
        _section_heading(pdf, "COVERAGE POLICY REFERENCE")
        pdf.set_font("Helvetica", "", 9)
        for ref in policy_refs:
            pdf.cell(6, 5, "\u2022")
            pdf.multi_cell(0, 5, ref)
        pdf.ln(4)

    # --- Authorization period (approval only) ---
    if letter_type == "approval" and expiration_date:
        _section_heading(pdf, "AUTHORIZATION PERIOD")
        _kv(pdf, "Effective Date", effective_date)
        _kv(pdf, "Expiration Date", expiration_date)
        pdf.ln(4)

    # --- Clinical summary ---
    summary = letter_dict.get("summary", "")
    if summary:
        _section_heading(pdf, "CLINICAL SUMMARY")
        pdf.set_font("Helvetica", "", 9)
        pdf.multi_cell(0, 5, summary)
        pdf.ln(4)

    # --- Missing documentation (pend only) ---
    if letter_type == "pend":
        missing_docs = letter_dict.get("missing_documentation", [])
        doc_gaps = letter_dict.get("documentation_gaps", [])
        if missing_docs or doc_gaps:
            _section_heading(pdf, "ADDITIONAL DOCUMENTATION REQUIRED")
            pdf.set_font("Helvetica", "", 9)
            for item in missing_docs:
                pdf.cell(6, 5, "\u2022")
                pdf.multi_cell(0, 5, item)
            for gap in doc_gaps:
                what = gap.get("what", "") if isinstance(gap, dict) else str(gap)
                critical = gap.get("critical", False) if isinstance(gap, dict) else False
                tag = "[REQUIRED]" if critical else "[Requested]"
                pdf.set_font("Helvetica", "B", 9)
                pdf.cell(6, 5, "\u2022")
                pdf.cell(22, 5, tag)
                pdf.set_font("Helvetica", "", 9)
                pdf.multi_cell(0, 5, what)
            pdf.ln(4)

        if doc_deadline:
            _section_heading(pdf, "DEADLINE")
            pdf.set_font("Helvetica", "B", 9)
            pdf.set_text_color(180, 0, 0)
            pdf.multi_cell(0, 5, f"Please submit the requested documentation by {doc_deadline}.")
            pdf.set_text_color(0, 0, 0)
            pdf.ln(4)

    # --- Appeal rights (pend only) ---
    if appeal_rights:
        _section_heading(pdf, "APPEAL RIGHTS")
        pdf.set_font("Helvetica", "", 9)
        pdf.multi_cell(0, 5, appeal_rights)
        pdf.ln(4)

    # --- Terms (approval only) ---
    if letter_type == "approval":
        _section_heading(pdf, "TERMS AND CONDITIONS")
        pdf.set_font("Helvetica", "", 8)
        pdf.multi_cell(
            0, 4,
            "This authorization is valid for the services described above during "
            "the authorization period. Services must be rendered within the "
            "effective dates. This authorization does not guarantee payment. "
            "Payment is subject to eligibility verification at the time of service.",
        )
        pdf.ln(4)

    # --- Closing ---
    pdf.ln(6)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, "Sincerely,")
    pdf.ln(8)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 6, "Utilization Management Department")

    # --- Disclaimer watermark bar ---
    pdf.ln(12)
    pdf.set_fill_color(255, 243, 205)
    pdf.set_font("Helvetica", "I", 7)
    pdf.set_text_color(133, 100, 4)
    pdf.multi_cell(
        0, 4,
        "DISCLAIMER: This is an AI-assisted draft. Coverage policies reflect "
        "Medicare LCDs/NCDs only. If this review is for a commercial or Medicare "
        "Advantage plan, payer-specific policies were not applied. All decisions "
        "require human clinical review before finalization.",
        fill=True,
    )

    # --- Output to base64 ---
    buf = io.BytesIO()
    pdf.output(buf)
    pdf_bytes = buf.getvalue()
    return base64.b64encode(pdf_bytes).decode("ascii")


def _section_heading(pdf: FPDF, text: str) -> None:
    """Render a bold section heading with underline."""
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(0, 70, 140)
    pdf.cell(0, 7, text)
    pdf.ln(2)
    pdf.set_draw_color(0, 70, 140)
    pdf.set_line_width(0.3)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(4)
    pdf.set_text_color(0, 0, 0)


def _kv(pdf: FPDF, key: str, value: str) -> None:
    """Render a key-value pair."""
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(55, 6, f"{key}:")
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 6, value)
    pdf.ln(5)
