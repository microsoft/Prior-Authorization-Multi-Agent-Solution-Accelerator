"""Pydantic output schema for the Synthesis Decision Agent.

Kept in sync with backend/app/models/schemas.py.
Used as response_format for MAF structured output — guarantees the
agent emits valid JSON matching this model on every call.
"""
from typing import Literal
from pydantic import BaseModel


class SynthesisOutput(BaseModel):
    recommendation: str = "pend_for_review"  # "approve" or "pend_for_review"
    confidence: float = 0.0
    confidence_level: str = ""  # "HIGH", "MEDIUM", "LOW"
    summary: str = ""
    clinical_rationale: str = ""
    decision_gate: Literal["gate_1_provider", "gate_2_codes", "gate_3_necessity", "approved"] = "gate_3_necessity"
    coverage_criteria_met: list[str] = []
    coverage_criteria_not_met: list[str] = []
    missing_documentation: list[str] = []
    policy_references: list[str] = []
    criteria_summary: str = ""
    synthesis_audit_trail: str = ""  # JSON-encoded audit trail (dict not supported in structured output)
    disclaimer: str = ""
