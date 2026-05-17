# shared/events.py
"""SSE event schema and valid step names."""

from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class WorkflowStep(StrEnum):
    """Valid workflow step values emitted over the SSE stream."""

    # Intake substeps
    INTAKE_PARSING = "intake_parsing"
    INTAKE_CLASSIFYING = "intake_classifying"
    INTAKE_DEADLINE = "intake_deadline"
    INTAKE_HISTORY = "intake_history"
    INTAKE_SCORING = "intake_scoring"
    INTAKE_COMPLETE = "intake_complete"

    # Evidence substeps
    EVIDENCE_GATHERING = "evidence_gathering"
    EVIDENCE_FETCHING_RECORDS = "evidence_fetching_records"
    EVIDENCE_RECORDS_FOUND = "evidence_records_found"
    EVIDENCE_GUIDELINE_LOOKUP = "evidence_guideline_lookup"
    EVIDENCE_GUIDELINE_FOUND = "evidence_guideline_found"
    EVIDENCE_EVALUATING = "evidence_evaluating"
    EVIDENCE_SUFFICIENT = "evidence_sufficient"
    EVIDENCE_RETRY = "evidence_retry"
    EVIDENCE_GATHERED = "evidence_gathered"
    EVIDENCE_GATHERED_PARTIAL = "evidence_gathered_partial"
    HUMAN_REVIEW_REQUIRED = "human_review_required"
    HITL_RESPONSE_RECEIVED = "hitl_response_received"

    # Writer substeps
    DRAFTING_PAYER_RULES = "drafting_payer_rules"
    DRAFTING_RULES_LOADED = "drafting_rules_loaded"
    DRAFTING_COMPOSING = "drafting_composing"
    LETTER_DRAFTED = "letter_drafted"

    # Physician substeps
    PHYSICIAN_CHECKING = "physician_checking"
    PHYSICIAN_ROUTING = "physician_routing"
    PHYSICIAN_REVIEWED = "physician_reviewed"

    # Submission substeps
    SUBMISSION_PREPARING = "submission_preparing"
    SUBMISSION_SENDING = "submission_sending"
    APPEAL_SUBMITTED = "appeal_submitted"

    # Terminal
    CASE_CLOSED = "case_closed"
    ERROR = "error"


class WorkflowEvent(BaseModel):
    """Pydantic model emitted over the SSE stream."""

    claim_id: str
    step: WorkflowStep
    status: Literal["success", "warning", "error", "waiting"]
    message: str
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    payload: dict = Field(default_factory=dict)


