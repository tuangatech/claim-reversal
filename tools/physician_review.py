# tools/physician_review.py
"""Physician review tool — checks requirement and simulates review."""

from shared.models import PhysicianReview

# Payers that always require physician attestation for clinical denials
PHYSICIAN_REQUIRED_PAYERS = {"BCBS", "UHC"}


def physician_review(
    claim_id: str,
    denial_type: str,
    claim_amount: float,
    payer_id: str,
    letter_text: str,
) -> PhysicianReview:
    """Determines if physician attestation is required and simulates the review."""

    # Physician required if clinical AND (high-value OR specific payer)
    physician_required = (
        denial_type == "clinical"
        and (claim_amount >= 10000 or payer_id.upper() in PHYSICIAN_REQUIRED_PAYERS)
    )

    if not physician_required:
        return PhysicianReview(
            claim_id=claim_id,
            physician_required=False,
            review_status="bypassed",
            notes="Physician attestation not required for this appeal.",
        )

    # Simulated approval — always approves
    return PhysicianReview(
        claim_id=claim_id,
        physician_required=True,
        review_status="approved",
        notes="Reviewed and approved by Dr. Sarah Mitchell, MD — Medical Director.",
    )

