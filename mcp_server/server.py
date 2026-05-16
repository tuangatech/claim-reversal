# mcp_server/server.py
"""MCP server entrypoint — registers shared tools and starts SSE transport."""

import json
import os

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

port = int(os.getenv("MCP_SERVER_PORT", "8002"))
mcp = FastMCP("Claim Denied MCP Server", host="0.0.0.0", port=port)


@mcp.tool()
def lookup_clinical_guideline(diagnosis_code: str) -> dict:
    """Returns clinical guideline criteria for a diagnosis code."""
    return {"code": diagnosis_code, "guideline_source": "stub", "criteria_summary": "Phase 1 stub"}


@mcp.tool()
def get_payer_appeal_rules(payer_id: str) -> dict:
    """Returns payer-specific appeal rules."""
    return {"payer_id": payer_id, "appeal_window_days": 90, "submission_format": "stub"}


@mcp.tool()
def log_appeal_event(claim_id: str, event_type: str, payload: str, agent_name: str) -> dict:
    """Writes an appeal event to the audit log."""
    print(f"[AUDIT] {agent_name} | {claim_id} | {event_type} | {payload}")
    return {"event_id": "stub-id", "timestamp": "now"}


@mcp.tool()
def get_claim_history(claim_id: str) -> dict:
    """Retrieves prior denial and appeal history for a claim."""
    return {"claim_id": claim_id, "prior_denials": [], "prior_appeals": []}


if __name__ == "__main__":
    mcp.run(transport="sse")
