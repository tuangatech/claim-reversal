# mcp_server/tools/claim_history.py
"""Retrieves prior denial and appeal history for a claim from claims.db."""

import json

from shared.db import get_connection


def get_claim_history(claim_id: str) -> dict:
    """Queries the appeals table for the row matching claim_id."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, status, denial_record FROM appeals WHERE id = ?",
            (claim_id,),
        ).fetchone()

        if row is None:
            return {
                "claim_id": claim_id,
                "status": "not_found",
                "prior_denials": [],
                "prior_appeals": [],
                "last_payment": None,
            }

        denial_record = json.loads(row["denial_record"]) if row["denial_record"] else {}

        # Check appeal_events for prior appeal submissions for this claim
        prior_appeal_rows = conn.execute(
            "SELECT event_type, payload, created_at FROM appeal_events "
            "WHERE claim_id = ? AND event_type IN ('appeal_submitted', 'case_closed') "
            "ORDER BY created_at DESC",
            (claim_id,),
        ).fetchall()

        prior_appeals = []
        for event_row in prior_appeal_rows:
            payload = json.loads(event_row["payload"]) if event_row["payload"] else {}
            prior_appeals.append({
                "event_type": event_row["event_type"],
                "payload": payload,
                "created_at": event_row["created_at"],
            })

        return {
            "claim_id": claim_id,
            "status": row["status"],
            "prior_denials": [{"denial_reason_code": denial_record.get("denial_reason_code", "")}] if denial_record else [],
            "prior_appeals": prior_appeals,
            "last_payment": None,
        }
    finally:
        conn.close()

