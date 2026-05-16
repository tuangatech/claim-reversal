# tools/triage_denial.py
"""Denial triage tool — classifies, checks deadline, scores worthiness."""

from datetime import date, timedelta

from mcp_server.tools.claim_history import get_claim_history

# Clinical denial reason codes per business spec
CLINICAL_CODES = {
    "CO-50": "Not medically necessary",
    "CO-57": "Experimental/investigational",
    "CO-97": "Payment included in allowance for another service",
    "CO-167": "Diagnosis is not covered",
}

ADMINISTRATIVE_CODES = {
    "CO-4": "Service not authorized",
    "CO-16": "Claim lacks information",
    "CO-22": "Coordination of benefits",
}

# Payer appeal windows in days
PAYER_APPEAL_WINDOWS = {
    "BCBS": 90,
    "AETNA": 60,
    "UHC": 180,
    "CIGNA": 90,
    "HUMANA": 60,
}
DEFAULT_APPEAL_WINDOW = 90


def triage_denial(
    claim_id: str,
    denial_reason_code: str,
    claim_amount: float,
    payer_id: str,
    date_of_service: str,
    denial_date: str,
) -> dict:
    """Performs all intake logic: classify denial, check deadline, score worthiness."""

    # 1. Classify denial
    if denial_reason_code in CLINICAL_CODES:
        is_clinical = True
        denial_type = "clinical"
        description = CLINICAL_CODES[denial_reason_code]
    elif denial_reason_code in ADMINISTRATIVE_CODES:
        is_clinical = False
        denial_type = "administrative"
        description = ADMINISTRATIVE_CODES[denial_reason_code]
    else:
        is_clinical = False
        denial_type = "administrative"
        description = "Unknown denial reason code"

    # 2. Check deadline
    appeal_window_days = PAYER_APPEAL_WINDOWS.get(payer_id.upper(), DEFAULT_APPEAL_WINDOW)
    denial_dt = date.fromisoformat(denial_date)
    appeal_deadline = denial_dt + timedelta(days=appeal_window_days)
    days_remaining = (appeal_deadline - date.today()).days
    is_open = days_remaining > 0

    # 3. Score worthiness
    score = 0
    reasoning_parts = []

    if claim_amount >= 5000:
        score += 40
        reasoning_parts.append(f"+40 (amount ${claim_amount:,.0f} >= $5,000)")
    elif claim_amount >= 1000:
        score += 30
        reasoning_parts.append(f"+30 (amount ${claim_amount:,.0f} >= $1,000)")
    elif claim_amount >= 500:
        score += 10
        reasoning_parts.append(f"+10 (amount ${claim_amount:,.0f} >= $500)")
    else:
        reasoning_parts.append(f"+0 (amount ${claim_amount:,.0f} below threshold)")

    if is_clinical:
        score += 30
        reasoning_parts.append("+30 (clinical denial)")

    if days_remaining < 14:
        score -= 20
        reasoning_parts.append(f"-20 (only {days_remaining} days remaining)")

    # Check prior appeal history for same denial reason
    history = get_claim_history(claim_id)
    prior_appeals = history.get("prior_appeals", [])
    has_prior_rejected = any(
        a.get("event_type") == "case_closed" for a in prior_appeals
    )
    if has_prior_rejected:
        score -= 15
        reasoning_parts.append("-15 (prior appeal for same reason was rejected)")

    # Determine recommendation
    if not is_open:
        recommendation = "close"
        reasoning_parts.append(f"OVERRIDE: deadline expired ({days_remaining} days past)")
    elif score >= 50:
        recommendation = "proceed"
    else:
        recommendation = "close"

    return {
        "is_clinical": is_clinical,
        "denial_type": denial_type,
        "description": description,
        "appeal_deadline": appeal_deadline.isoformat(),
        "days_remaining": days_remaining,
        "is_open": is_open,
        "worthiness_score": score,
        "recommendation": recommendation,
        "reasoning": "; ".join(reasoning_parts),
    }

