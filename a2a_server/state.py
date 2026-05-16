# a2a_server/state.py
"""AppealState TypedDict and related enums for the LangGraph graph."""

from enum import StrEnum
from typing import Optional, TypedDict


class EvidenceSufficiency(StrEnum):
    """Result of evidence evaluation."""

    SUFFICIENT = "sufficient"
    INSUFFICIENT = "insufficient"
    HUMAN_REVIEW = "human_review"


class HumanChoice(StrEnum):
    """Choices available to the human reviewer at the HITL point."""

    PROCEED = "proceed"
    CLOSE = "close"


class AppealState(TypedDict):
    """LangGraph state for the Clinical Evidence Agent graph."""

    # Input
    claim_id: str
    diagnosis_codes: list[str]
    payer_id: str
    denial_reason_code: str

    # Gathered evidence
    patient_records: Optional[list[dict]]
    guideline_citations: Optional[list[dict]]
    lcd_policy_text: Optional[str]

    # Evaluation
    sufficiency: Optional[EvidenceSufficiency]
    sufficiency_reasoning: Optional[str]
    retry_count: int
    include_supplemental: bool

    # HITL
    human_choice: Optional[HumanChoice]
    hitl_triggered: bool

    # Output
    evidence_bundle: Optional[dict]
    closed_reason: Optional[str]
    error: Optional[str]

