# tools/submit_appeal.py
"""Appeal submission tool — simulates submitting to the payer."""

from shared.models import SubmissionConfirmation


def submit_appeal(
    claim_id: str,
    payer_id: str,
    letter_text: str,
) -> SubmissionConfirmation:
    """Simulates appeal submission and returns a confirmation."""
    return {}

