# tests/test_crew.py
"""End-to-end tests for the AppealCrew pipeline."""

import asyncio
import json
import os
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from shared.db import get_connection, init_db, seed_db
from shared.events import WorkflowStep

TEST_DB_PATH = "data/test_crew.db"


@pytest.fixture(autouse=True)
def reset_db(monkeypatch):
    """Creates a fresh test DB and redirects all get_connection calls to it."""
    Path(TEST_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    if Path(TEST_DB_PATH).exists():
        Path(TEST_DB_PATH).unlink()

    monkeypatch.setattr("shared.db.get_connection", lambda db_path=TEST_DB_PATH: _get_test_conn())
    monkeypatch.setattr("crew.appeal_crew.get_connection", lambda db_path=TEST_DB_PATH: _get_test_conn())
    monkeypatch.setattr("tools.triage_denial.get_claim_history", lambda claim_id: {"claim_id": claim_id, "prior_appeals": [], "prior_denials": [], "last_payment": None})
    monkeypatch.setattr("tools.submit_appeal.get_connection", lambda db_path=TEST_DB_PATH: _get_test_conn())
    monkeypatch.setattr("tools.submit_appeal.get_payer_appeal_rules", lambda payer_id: {"submission_format": "portal"})

    init_db(TEST_DB_PATH)
    seed_db(TEST_DB_PATH)
    yield

    if Path(TEST_DB_PATH).exists():
        Path(TEST_DB_PATH).unlink()


def _get_test_conn():
    """Returns a connection to the test DB."""
    conn = sqlite3.connect(TEST_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


async def _collect_events(queue: asyncio.Queue, timeout: float = 60.0) -> list:
    """Drains all events from the queue until a terminal event or timeout."""
    events = []
    terminal = {WorkflowStep.APPEAL_SUBMITTED, WorkflowStep.CASE_CLOSED, WorkflowStep.ERROR}
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            break
        try:
            event = await asyncio.wait_for(queue.get(), timeout=min(remaining, 5.0))
            events.append(event)
            if event.step in terminal:
                break
        except asyncio.TimeoutError:
            break
    return events


# --- Non-LLM tests ---


@pytest.mark.asyncio
async def test_crew_non_clinical_denial_closes(reset_db):
    """Administrative denial closes immediately at intake."""
    # Insert a mock claim with administrative denial code
    conn = _get_test_conn()
    eob = {
        "claim_id": "CLM-TEST-ADMIN",
        "patient_name": "Test Patient",
        "patient_id": "PAT-00001",
        "payer_id": "BCBS",
        "payer_name": "Blue Cross Blue Shield",
        "denial_reason_code": "CO-4",
        "denial_reason_text": "Service not authorized",
        "diagnosis_codes": ["J18.9"],
        "date_of_service": "2026-05-01",
        "denial_date": "2026-05-10",
        "claim_amount": 5000.00,
    }
    conn.execute(
        "INSERT OR REPLACE INTO appeals (id, status, denial_record) VALUES (?, ?, ?)",
        ("CLM-TEST-ADMIN", "pending", json.dumps(eob)),
    )
    conn.commit()
    conn.close()

    from crew.appeal_crew import AppealCrew

    queue = asyncio.Queue()
    crew = AppealCrew("CLM-TEST-ADMIN", queue)
    await crew.run()

    events = []
    while not queue.empty():
        events.append(await queue.get())

    steps = [e.step for e in events]
    assert WorkflowStep.INTAKE_COMPLETE in steps
    assert WorkflowStep.CASE_CLOSED in steps
    # Should NOT proceed to evidence or beyond
    assert WorkflowStep.EVIDENCE_GATHERING not in steps
    assert WorkflowStep.LETTER_DRAFTED not in steps


@pytest.mark.asyncio
async def test_crew_evidence_agent_unavailable(monkeypatch, reset_db):
    """When evidence agent is unreachable, crew emits ERROR gracefully."""
    # Point to a port that's not listening
    monkeypatch.setattr("crew.appeal_crew.EVIDENCE_AGENT_PORT", "9999")

    from crew.appeal_crew import AppealCrew

    queue = asyncio.Queue()
    crew = AppealCrew("CLM-2026-00123", queue)
    # Need to re-init http_client with the patched port
    crew.http_client = __import__("httpx").AsyncClient(base_url="http://localhost:9999", timeout=5.0)

    await crew.run()

    events = []
    while not queue.empty():
        events.append(await queue.get())

    steps = [e.step for e in events]
    # Intake should complete, then error on evidence
    assert WorkflowStep.INTAKE_COMPLETE in steps
    assert WorkflowStep.ERROR in steps
    # Should NOT crash or proceed to writer
    assert WorkflowStep.LETTER_DRAFTED not in steps


# --- LLM-dependent tests (require running A2A server + OpenRouter key) ---


@pytest.mark.llm
@pytest.mark.asyncio
async def test_crew_happy_path_sufficient(reset_db):
    """Full pipeline for CLM-2026-00123 (sufficient evidence) completes without HITL."""
    from crew.appeal_crew import AppealCrew

    queue = asyncio.Queue()
    crew = AppealCrew("CLM-2026-00123", queue)
    await crew.run()

    events = await _collect_events(queue, timeout=0.1)
    # Events already consumed by run(), collect any remaining
    all_events = []
    while not queue.empty():
        all_events.append(await queue.get())

    # Re-collect from the crew's emitted events by re-reading from queue
    # Actually, events are put on queue during run(), let's just check DB state
    conn = _get_test_conn()
    row = conn.execute("SELECT status, evidence_bundle, appeal_letter, submission FROM appeals WHERE id=?", ("CLM-2026-00123",)).fetchone()
    conn.close()

    assert row["status"] == "submitted"
    assert row["evidence_bundle"] is not None
    bundle = json.loads(row["evidence_bundle"])
    assert bundle["partial"] is False
    assert row["appeal_letter"] is not None
    assert row["submission"] is not None


@pytest.mark.llm
@pytest.mark.asyncio
async def test_crew_hitl_proceed(reset_db):
    """CLM-2026-00199 triggers HITL, proceed resumes and completes."""
    from crew.appeal_crew import AppealCrew

    queue = asyncio.Queue()
    crew = AppealCrew("CLM-2026-00199", queue)

    # Run crew in background, resume when HITL fires
    async def _run_with_resume():
        task = asyncio.create_task(crew.run())
        # Wait for HITL event
        while True:
            event = await asyncio.wait_for(queue.get(), timeout=120.0)
            if event.step == WorkflowStep.HUMAN_REVIEW_REQUIRED:
                crew.resume("proceed")
                break
        # Drain remaining events
        await task

    await _run_with_resume()

    conn = _get_test_conn()
    row = conn.execute("SELECT status, evidence_bundle FROM appeals WHERE id=?", ("CLM-2026-00199",)).fetchone()
    conn.close()

    assert row["status"] == "submitted"
    bundle = json.loads(row["evidence_bundle"])
    assert bundle["partial"] is True


@pytest.mark.llm
@pytest.mark.asyncio
async def test_crew_hitl_close(reset_db):
    """CLM-2026-00199 triggers HITL, close terminates pipeline."""
    from crew.appeal_crew import AppealCrew

    queue = asyncio.Queue()
    crew = AppealCrew("CLM-2026-00199", queue)

    async def _run_with_close():
        task = asyncio.create_task(crew.run())
        while True:
            event = await asyncio.wait_for(queue.get(), timeout=120.0)
            if event.step == WorkflowStep.HUMAN_REVIEW_REQUIRED:
                crew.resume("close")
                break
        await task

    await _run_with_close()

    conn = _get_test_conn()
    row = conn.execute("SELECT status, appeal_letter FROM appeals WHERE id=?", ("CLM-2026-00199",)).fetchone()
    conn.close()

    # Should not have submitted — no appeal letter
    assert row["status"] != "submitted"
    assert row["appeal_letter"] is None


@pytest.mark.llm
@pytest.mark.asyncio
async def test_crew_hitl_timeout(monkeypatch, reset_db):
    """HITL timeout auto-closes the case."""
    monkeypatch.setattr("crew.appeal_crew.HITL_TIMEOUT_SECONDS", 2)

    from crew.appeal_crew import AppealCrew

    queue = asyncio.Queue()
    crew = AppealCrew("CLM-2026-00199", queue)
    # Override timeout on the instance level too
    import crew.appeal_crew
    original = crew.appeal_crew.HITL_TIMEOUT_SECONDS
    crew.appeal_crew.HITL_TIMEOUT_SECONDS = 2

    await crew.run()

    # Collect events
    events = []
    while not queue.empty():
        events.append(await queue.get())

    steps = [e.step for e in events]
    assert WorkflowStep.CASE_CLOSED in steps
    # Should NOT have proceeded to writer
    assert WorkflowStep.LETTER_DRAFTED not in steps

    crew.appeal_crew.HITL_TIMEOUT_SECONDS = original

