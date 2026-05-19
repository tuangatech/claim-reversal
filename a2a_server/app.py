# a2a_server/app.py
"""Standalone FastAPI application — Clinical Evidence A2A server."""

import sys
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from langgraph.types import Command

from a2a_server.graph import graph
from shared.db import init_db, seed_db
from shared.logging import configure_logging

configure_logging("evidence-agent")
logger = structlog.get_logger()

app = FastAPI(title="Clinical Evidence A2A Agent")

# Ensure DB is ready
init_db()
seed_db()

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
    """A2A task endpoint — handles initial invocation and HITL resume."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={"error": "Invalid JSON body"},
        )

    # Extract data from A2A message format
    messages = body.get("messages", [])
    if not messages or not messages[0].get("parts"):
        return JSONResponse(
            status_code=400,
            content={"error": "Missing messages or parts in request"},
        )

    data = messages[0]["parts"][0].get("data", {})
    task_id = body.get("id")
    is_resume = task_id and "human_choice" in data

    if is_resume:
        structlog.contextvars.bind_contextvars(claim_id=data.get("claim_id", ""), task_id=task_id)
        logger.info("a2a_resume_received", choice=data["human_choice"])
        # Resume a suspended graph
        config = {"configurable": {"thread_id": task_id}}

        # Verify the graph is actually suspended before attempting resume
        try:
            state_snapshot = graph.get_state(config)
        except Exception:
            return JSONResponse(
                status_code=404,
                content={"error": f"No checkpoint found for task_id: {task_id}"},
            )

        if not state_snapshot or not state_snapshot.next:
            return JSONResponse(
                status_code=409,
                content={"error": f"Task {task_id} is not suspended — cannot resume"},
            )

        try:
            result = await graph.ainvoke(
                Command(resume={"choice": data["human_choice"]}),
                config=config,
            )
        except Exception as e:
            return JSONResponse(
                status_code=500,
                content={"error": f"Failed to resume graph: {str(e)}"},
            )
        return _build_completed_response(task_id, result)

    # New task — validate required fields
    required = ["claim_id", "diagnosis_codes", "payer_id", "denial_reason_code"]
    missing = [f for f in required if f not in data]
    if missing:
        return JSONResponse(
            status_code=400,
            content={"error": f"Missing required fields: {missing}"},
        )

    # Generate task_id and invoke graph
    task_id = str(uuid4())
    structlog.contextvars.bind_contextvars(claim_id=data["claim_id"], task_id=task_id)
    logger.info("a2a_task_received")
    initial_state = {
        "claim_id": data["claim_id"],
        "diagnosis_codes": data["diagnosis_codes"],
        "payer_id": data["payer_id"],
        "denial_reason_code": data["denial_reason_code"],
        "retry_count": 0,
        "include_supplemental": False,
        "hitl_triggered": False,
        "patient_records": None,
        "guideline_citations": None,
        "lcd_policy_text": None,
        "sufficiency": None,
        "sufficiency_reasoning": None,
        "human_choice": None,
        "evidence_bundle": None,
        "closed_reason": None,
        "error": None,
    }

    config = {"configurable": {"thread_id": task_id}}
    result = await graph.ainvoke(initial_state, config=config)

    # Determine if graph completed or suspended at interrupt
    if result.get("evidence_bundle") is not None or result.get("closed_reason") is not None:
        logger.info("graph_completed", sufficiency=result.get("sufficiency"), retry_count=result.get("retry_count", 0))
        return _build_completed_response(task_id, result)

    # Graph suspended — check via get_state for confirmation
    state_snapshot = graph.get_state(config)
    if state_snapshot.next:
        logger.info("graph_suspended", retry_count=result.get("retry_count", 0))
        # Suspended at interrupt — return input-required
        return JSONResponse(content={
            "id": task_id,
            "status": {"state": "input-required"},
            "messages": [{
                "role": "agent",
                "parts": [{
                    "type": "data",
                    "data": {
                        "claim_id": result.get("claim_id", ""),
                        "sufficiency_reasoning": result.get("sufficiency_reasoning", ""),
                        "evidence_gathered": {
                            "record_count": len(result.get("patient_records") or []),
                            "guideline_count": len(result.get("guideline_citations") or []),
                        },
                        "options": ["proceed", "close"],
                    },
                }],
            }],
        })

    # Fallback — shouldn't reach here
    return _build_completed_response(task_id, result)


def _build_completed_response(task_id: str, result: dict) -> JSONResponse:
    """Builds a completed A2A response from graph result."""
    if result.get("closed_reason"):
        data = {"closed_reason": result["closed_reason"]}
    else:
        data = {"evidence_bundle": result.get("evidence_bundle")}

    return JSONResponse(content={
        "id": task_id,
        "status": {"state": "completed"},
        "messages": [{
            "role": "agent",
            "parts": [{"type": "data", "data": data}],
        }],
    })


@app.get("/health")
async def health():
    """Health check."""
    return {"status": "ok", "service": "evidence-agent"}

