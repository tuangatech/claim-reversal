# tools/submit_appeal.py
"""Appeal submission tool — simulates submitting to the payer."""

from datetime import datetime, timezone
from uuid import uuid4

from mcp_server.tools.payer_rules import get_payer_appeal_rules
from shared.db import get_connection
from shared.models import SubmissionConfirmation


def submit_appeal(
    claim_id: str,
    payer_id: str,
    letter_text: str,
) -> SubmissionConfirmation:
    """Simulates appeal submission and returns a confirmation."""

    confirmation_number = f"CONF-{payer_id[:3].upper()}-{uuid4().hex[:8].upper()}"
    submitted_at = datetime.now(timezone.utc).isoformat()

    # Look up submission method from payer rules
    rules = get_payer_appeal_rules(payer_id)
    submission_method = rules.get("submission_format", "mail")

    # Update appeal status in DB
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE appeals SET status = ?, submission = ?, updated_at = ? WHERE id = ?",
            ("submitted", f'{{"confirmation_number": "{confirmation_number}", "method": "{submission_method}"}}', submitted_at, claim_id),
        )
        conn.commit()
    finally:
        conn.close()

    return SubmissionConfirmation(
        claim_id=claim_id,
        confirmation_number=confirmation_number,
        submitted_at=submitted_at,
        submission_method=submission_method,
        payer_id=payer_id,
    )

