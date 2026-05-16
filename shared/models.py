# shared/models.py
"""All Pydantic models shared across processes."""

from typing import Literal, Optional

from pydantic import BaseModel


class DenialRecord(BaseModel):
    """Structured output of Denial Intake."""

    claim_id: str
    patient_name: str
    patient_id: str
    payer_id: str
    payer_name: str
    denial_reason_code: str
    denial_reason_text: str
    is_clinical: bool
    diagnosis_codes: list[str]
    date_of_service: str
    denial_date: str
    claim_amount: float
    appeal_deadline: str
    days_remaining: int
    worthiness_score: int
    recommendation: Literal["proceed", "close", "skip"]


class ClinicalRecord(BaseModel):
    """A single patient record."""

    record_type: Literal[
        "admission_note",
        "progress_note",
        "discharge_summary",
        "lab_result",
        "imaging_report",
        "prior_auth",
    ]
    content: str
    date: str
    author: Optional[str] = None


class GuidelineCitation(BaseModel):
    """A clinical guideline result."""

    diagnosis_code: str
    guideline_source: str
    criteria_summary: str
    medical_necessity_indicators: list[str]
    confidence: float


class EvidenceBundle(BaseModel):
    """Output of the Clinical Evidence Agent."""

    claim_id: str
    patient_records: list[ClinicalRecord]
    guideline_citations: list[GuidelineCitation]
    lcd_policy_text: Optional[str] = None
    sufficiency_reasoning: str
    partial: bool = False


class AppealLetter(BaseModel):
    """Output of Appeal Writer."""

    claim_id: str
    payer_id: str
    payer_name: str
    letter_text: str
    submission_format: str
    required_attachments: list[str]
    drafted_at: str


class PhysicianReview(BaseModel):
    """Output of Physician Sign-off."""

    claim_id: str
    physician_required: bool
    review_status: Literal["approved", "flagged", "bypassed"]
    notes: Optional[str] = None


class SubmissionConfirmation(BaseModel):
    """Final output of Submission Agent."""

    claim_id: str
    confirmation_number: str
    submitted_at: str
    submission_method: str
    payer_id: str

