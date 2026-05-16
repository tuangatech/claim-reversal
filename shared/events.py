# shared/events.py
"""SSE event schema and valid step names."""

from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class WorkflowStep(StrEnum):
    """Valid workflow step values emitted over the SSE stream."""

    INTAKE_COMPLETE = "intake_complete"
    EVIDENCE_GATHERING = "evidence_gathering"
    EVIDENCE_GATHERED = "evidence_gathered"
    EVIDENCE_GATHERED_PARTIAL = "evidence_gathered_partial"
    HUMAN_REVIEW_REQUIRED = "human_review_required"
    HITL_RESPONSE_RECEIVED = "hitl_response_received"
    LETTER_DRAFTED = "letter_drafted"
    PHYSICIAN_REVIEWED = "physician_reviewed"
    APPEAL_SUBMITTED = "appeal_submitted"
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

