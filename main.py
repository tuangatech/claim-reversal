# main.py
"""FastAPI main application — SSE event queue, crew kickoff, HITL resume endpoint."""

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from crew.appeal_crew import AppealCrew
from shared.db import get_connection, init_db, seed_db
from shared.events import WorkflowEvent, WorkflowStep


event_queues: dict[str, asyncio.Queue] = {}
active_crews: dict[str, AppealCrew] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise and seed the database on startup."""
    init_db()
    seed_db()
    yield


app = FastAPI(title="Claim Reversal", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AppealRequest(BaseModel):
    """Request body for POST /appeal."""
    claim_id: str


class ResumeRequest(BaseModel):
    """Request body for POST /appeal/{claim_id}/resume."""
    choice: str


async def emit_event(claim_id: str, event: WorkflowEvent) -> None:
    """Put a workflow event onto the claim's SSE queue."""
    if claim_id not in event_queues:
        event_queues[claim_id] = asyncio.Queue()
    await event_queues[claim_id].put(event)


async def _run_and_cleanup(claim_id: str, crew: AppealCrew) -> None:
    """Runs the crew and removes it from active_crews when done."""
    try:
        await crew.run()
    finally:
        active_crews.pop(claim_id, None)


@app.get("/claims")
async def list_claims():
    """Returns all denied claims available for processing."""
    conn = get_connection()
    rows = conn.execute("SELECT id, denial_record FROM appeals").fetchall()
    conn.close()

    claims = []
    for row in rows:
        eob = json.loads(row["denial_record"])
        claims.append({
            "claim_id": row["id"],
            "patient_name": eob.get("patient_name", ""),
            "patient_dob": eob.get("patient_dob", ""),
            "patient_sex": eob.get("patient_sex", ""),
            "diagnosis_codes": eob.get("diagnosis_codes", []),
            "service_description": eob.get("service_description", ""),
            "claim_amount": eob.get("claim_amount", 0),
            "date_of_service": eob.get("date_of_service", ""),
            "payer_name": eob.get("payer_name", ""),
            "denial_reason_code": eob.get("denial_reason_code", ""),
            "denial_reason_text": eob.get("denial_reason_text", ""),
            "facility": eob.get("facility", ""),
        })
    return {"claims": claims}


@app.post("/appeal")
async def start_appeal(request: AppealRequest):
    """Kick off the appeal workflow for a claim."""
    conn = get_connection()
    row = conn.execute("SELECT id FROM appeals WHERE id = ?", (request.claim_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail=f"Claim {request.claim_id} not found")

    # Reset claim state for re-run (testing/demo — same claim can be submitted multiple times)
    conn.execute(
        "UPDATE appeals SET status='pending', evidence_bundle=NULL, appeal_letter=NULL, submission=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (request.claim_id,),
    )
    conn.execute("DELETE FROM appeal_events WHERE claim_id=?", (request.claim_id,))
    conn.commit()
    conn.close()

    # Create SSE queue and crew
    event_queues[request.claim_id] = asyncio.Queue()
    crew = AppealCrew(request.claim_id, event_queues[request.claim_id])
    active_crews[request.claim_id] = crew

    # Spawn the pipeline as a background task
    asyncio.create_task(_run_and_cleanup(request.claim_id, crew))
    return {"claim_id": request.claim_id, "status": "started"}


@app.get("/stream/{claim_id}")
async def stream_events(claim_id: str):
    """SSE endpoint — streams workflow events for a claim."""

    async def event_generator():
        if claim_id not in event_queues:
            event_queues[claim_id] = asyncio.Queue()
        queue = event_queues[claim_id]

        terminal_steps = {
            WorkflowStep.APPEAL_SUBMITTED,
            WorkflowStep.CASE_CLOSED,
            WorkflowStep.ERROR,
        }

        while True:
            try:
                event: WorkflowEvent = await asyncio.wait_for(queue.get(), timeout=30.0)
                data = event.model_dump_json()
                yield f"event: workflow_step\ndata: {data}\n\n"
                if event.step in terminal_steps:
                    break
            except asyncio.TimeoutError:
                ts = datetime.now(timezone.utc).isoformat()
                yield f"event: heartbeat\ndata: {json.dumps({'timestamp': ts})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/appeal/{claim_id}/resume")
async def resume_appeal(claim_id: str, request: ResumeRequest):
    """HITL resume endpoint — accepts human decision to proceed or close."""
    crew = active_crews.get(claim_id)
    if not crew:
        raise HTTPException(status_code=404, detail="No active workflow for this claim")
    if request.choice not in ("proceed", "close"):
        raise HTTPException(status_code=400, detail="Choice must be 'proceed' or 'close'")
    crew.resume(request.choice)
    return {"claim_id": claim_id, "choice": request.choice, "status": "resumed"}


@app.get("/health")
async def health():
    """Health check."""
    return {"status": "ok", "service": "main-app"}


