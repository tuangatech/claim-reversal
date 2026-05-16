# a2a_server/app.py
"""Standalone FastAPI application — Clinical Evidence A2A server."""

import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="Clinical Evidence A2A Agent")

AGENT_CARD = {
    "name": "Clinical Evidence Agent",
    "description": "Gathers and evaluates clinical evidence for medical necessity appeals",
    "url": f"http://localhost:{os.getenv('EVIDENCE_AGENT_PORT', '8001')}",
    "version": "0.1.0",
    "protocol": "a2a",
    "protocolVersion": "0.3.0",
    "inputModes": ["application/json"],
    "outputModes": ["application/json"],
    "skills": [
        {
            "name": "clinical_evidence_gathering",
            "description": "Accepts a denial record (diagnosis codes + payer ID) and returns an evidence bundle",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "claim_id": {"type": "string"},
                    "diagnosis_codes": {"type": "array", "items": {"type": "string"}},
                    "payer_id": {"type": "string"},
                    "denial_reason_code": {"type": "string"},
                },
                "required": ["claim_id", "diagnosis_codes", "payer_id", "denial_reason_code"],
            },
        }
    ],
}


@app.get("/.well-known/agent-card.json")
async def agent_card():
    """Serves the A2A agent card for discovery."""
    return AGENT_CARD


@app.post("/a2a")
async def a2a_task(request: Request):
    """Stub A2A task endpoint — will handle tasks/send in Phase 3."""
    body = await request.json()
    return JSONResponse(
        content={"status": "stub", "message": "A2A endpoint not yet implemented", "received": body}
    )


@app.get("/health")
async def health():
    """Health check."""
    return {"status": "ok", "service": "evidence-agent"}

