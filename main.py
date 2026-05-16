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

from shared.db import get_connection, init_db, seed_db
from shared.events import WorkflowEvent, WorkflowStep


event_queues: dict[str, asyncio.Queue] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise and seed the database on startup."""
    init_db()
    seed_db()
    yield


app = FastAPI(title="Claim Denied", lifespan=lifespan)

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


async def run_crew(claim_id: str) -> None:
    """Stub crew runner — emits fake workflow events to simulate the pipeline."""
    steps = [
        (WorkflowStep.INTAKE_COMPLETE, "success", "Denial triaged. Clinical denial confirmed, appeal recommended."),
        (WorkflowStep.EVIDENCE_GATHERING, "success", "Gathering clinical evidence from patient records..."),
        (WorkflowStep.EVIDENCE_GATHERED, "success", "Clinical evidence bundle assembled. Records and guidelines collected."),
        (WorkflowStep.LETTER_DRAFTED, "success", "Appeal letter drafted with clinical evidence and guideline citations."),
        (WorkflowStep.PHYSICIAN_REVIEWED, "success", "Physician review complete. Appeal approved for submission."),
        (WorkflowStep.APPEAL_SUBMITTED, "success", "Appeal submitted to payer. Confirmation number generated."),
    ]
    for step, status, message in steps:
        await asyncio.sleep(1)
        event = WorkflowEvent(
            claim_id=claim_id,
            step=step,
            status=status,
            message=message,
        )
        await emit_event(claim_id, event)


@app.post("/appeal")
async def start_appeal(request: AppealRequest):
    """Kick off the appeal workflow for a claim."""
    conn = get_connection()
    row = conn.execute("SELECT id FROM appeals WHERE id = ?", (request.claim_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail=f"Claim {request.claim_id} not found")

    event_queues[request.claim_id] = asyncio.Queue()
    asyncio.create_task(run_crew(request.claim_id))
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
    return {"status": "not_implemented_yet", "claim_id": claim_id, "choice": request.choice}


@app.get("/health")
async def health():
    """Health check."""
    return {"status": "ok", "service": "main-app"}

