# tools/physician_review.py
"""Physician review tool — checks requirement and simulates review."""

from shared.models import PhysicianReview


def physician_review(
    claim_id: str,
    denial_type: str,
    claim_amount: float,
    payer_id: str,
    letter_text: str,
) -> PhysicianReview:
    """Determines if physician attestation is required and simulates the review."""
    return {}

