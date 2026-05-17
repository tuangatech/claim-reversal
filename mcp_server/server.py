# mcp_server/server.py
"""MCP server entrypoint — registers shared tools and starts SSE transport."""

import sys
from pathlib import Path

# Ensure project root is on sys.path when run as `python mcp_server/server.py`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import os

import structlog
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from shared.db import init_db, seed_db
from shared.logging import configure_logging

load_dotenv()
configure_logging("mcp-server")
logger = structlog.get_logger()

port = int(os.getenv("MCP_SERVER_PORT", "8002"))
mcp = FastMCP("Claim Reversal MCP Server", host="0.0.0.0", port=port)

# Ensure DB is ready before tools try to access it
init_db()
seed_db()

# Import real implementations
from mcp_server.tools.audit_log import log_appeal_event as _log_appeal_event
from mcp_server.tools.claim_history import get_claim_history as _get_claim_history
from mcp_server.tools.lookup_guideline import lookup_clinical_guideline as _lookup_clinical_guideline
from mcp_server.tools.payer_rules import get_payer_appeal_rules as _get_payer_appeal_rules


@mcp.tool()
def lookup_clinical_guideline(diagnosis_code: str) -> dict:
    """Returns clinical guideline criteria for a diagnosis code."""
    logger.info("tool_called", tool="lookup_clinical_guideline", diagnosis_code=diagnosis_code)
    result = _lookup_clinical_guideline(diagnosis_code)
    logger.info("tool_completed", tool="lookup_clinical_guideline", found=result.get("guideline_source") is not None)
    return result


@mcp.tool()
def get_payer_appeal_rules(payer_id: str) -> dict:
    """Returns payer-specific appeal rules."""
    logger.info("tool_called", tool="get_payer_appeal_rules", payer_id=payer_id)
    result = _get_payer_appeal_rules(payer_id)
    logger.info("tool_completed", tool="get_payer_appeal_rules", payer_name=result.get("payer_name"))
    return result


@mcp.tool()
def log_appeal_event(claim_id: str, event_type: str, payload: str, agent_name: str) -> dict:
    """Writes an appeal event to the audit log."""
    # MCP transport passes payload as JSON string; parse it
    parsed_payload = json.loads(payload) if isinstance(payload, str) else payload
    logger.info("tool_called", tool="log_appeal_event", claim_id=claim_id, event_type=event_type, agent_name=agent_name)
    result = _log_appeal_event(claim_id, event_type, parsed_payload, agent_name)
    logger.info("tool_completed", tool="log_appeal_event", event_id=result.get("event_id"))
    return result


@mcp.tool()
def get_claim_history(claim_id: str) -> dict:
    """Retrieves prior denial and appeal history for a claim."""
    logger.info("tool_called", tool="get_claim_history", claim_id=claim_id)
    result = _get_claim_history(claim_id)
    logger.info("tool_completed", tool="get_claim_history", claim_id=claim_id)
    return result


if __name__ == "__main__":
    mcp.run(transport="sse")
