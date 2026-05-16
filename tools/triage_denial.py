# tools/triage_denial.py
"""Denial triage tool — classifies, checks deadline, scores worthiness."""


def triage_denial(
    claim_id: str,
    denial_reason_code: str,
    claim_amount: float,
    payer_id: str,
    date_of_service: str,
    denial_date: str,
) -> dict:
    """Performs all intake logic: classify denial, check deadline, score worthiness."""
    return {}

