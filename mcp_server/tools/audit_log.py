# mcp_server/tools/audit_log.py
"""Writes appeal events to the appeal_events table in claims.db."""

import json
from datetime import datetime, timezone
from uuid import uuid4

from shared.db import get_connection


def log_appeal_event(
    claim_id: str,
    event_type: str,
    payload: dict,
    agent_name: str,
) -> dict:
    """Inserts an event row into appeal_events and returns the event_id and timestamp."""

    event_id = str(uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()

    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO appeal_events (id, claim_id, event_type, agent_name, payload, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (event_id, claim_id, event_type, agent_name, json.dumps(payload), timestamp),
        )
        conn.commit()
    finally:
        conn.close()

    return {"event_id": event_id, "timestamp": timestamp}

