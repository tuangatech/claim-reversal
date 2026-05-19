# tests/test_main.py
"""HTTP-level integration tests for the FastAPI main app."""

import json
import sqlite3
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from mcp_server.tools.claim_history import get_claim_history as _local_get_claim_history
from mcp_server.tools.lookup_guideline import lookup_clinical_guideline as _local_lookup_guideline
from mcp_server.tools.payer_rules import get_payer_appeal_rules as _local_get_payer_rules
from shared.db import init_db, seed_db
from shared.models import InputGuardrailResult

TEST_DB_PATH = "data/test_main.db"


class _MockMcpClient:
    """Fake MCP client for test isolation."""

    async def connect(self, **kwargs):
        pass

    async def disconnect(self):
        pass

    async def lookup_clinical_guideline(self, diagnosis_code: str) -> dict:
        return _local_lookup_guideline(diagnosis_code)

    async def get_payer_appeal_rules(self, payer_id: str) -> dict:
        return _local_get_payer_rules(payer_id)

    async def log_appeal_event(self, claim_id: str, event_type: str, payload: dict, agent_name: str) -> dict:
        return {"event_id": "test", "timestamp": "2026-01-01T00:00:00Z"}

    async def get_claim_history(self, claim_id: str) -> dict:
        return _local_get_claim_history(claim_id)


@pytest.fixture(autouse=True)
def reset_db(monkeypatch):
    """Creates a fresh test DB and redirects all get_connection calls."""
    Path(TEST_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    if Path(TEST_DB_PATH).exists():
        Path(TEST_DB_PATH).unlink()

    def _get_test_conn(db_path=TEST_DB_PATH):
        conn = sqlite3.connect(TEST_DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr("shared.db.get_connection", _get_test_conn)
    monkeypatch.setattr("crew.appeal_crew.get_connection", _get_test_conn)
    monkeypatch.setattr("mcp_server.tools.audit_log.get_connection", _get_test_conn)
    monkeypatch.setattr("mcp_server.tools.claim_history.get_connection", _get_test_conn)
    monkeypatch.setattr("tools.submit_appeal.get_connection", _get_test_conn)

    # Mock MCP client so tests don't require a live MCP server
    monkeypatch.setattr("crew.appeal_crew.McpClient", _MockMcpClient)

    # Mock guardrail to bypass LLM call
    monkeypatch.setattr("crew.appeal_crew.scan_denial_record", lambda _: InputGuardrailResult(
        passed=True, checks_run=["pattern_scan", "llm_classifier"], flagged_segments=[], confidence=0.95, reasoning="Mock: passed"
    ))

    init_db(TEST_DB_PATH)
    seed_db(TEST_DB_PATH)
    yield

    if Path(TEST_DB_PATH).exists():
        Path(TEST_DB_PATH).unlink()


@pytest_asyncio.fixture
async def client():
    """Async HTTP client bound to the FastAPI app."""
    from main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_health(client):
    """GET /health returns OK."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "service": "main-app"}


@pytest.mark.asyncio
async def test_post_appeal_starts_workflow(client):
    """POST /appeal with valid claim_id returns 200 and started status."""
    resp = await client.post("/appeal", json={"claim_id": "CLM-2026-00123"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["claim_id"] == "CLM-2026-00123"
    assert data["status"] == "started"


@pytest.mark.asyncio
async def test_post_appeal_invalid_claim(client):
    """POST /appeal with nonexistent claim_id returns 404."""
    resp = await client.post("/appeal", json={"claim_id": "CLM-NONEXISTENT"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_resume_no_active_workflow(client):
    """POST /appeal/{claim_id}/resume without active workflow returns 404."""
    resp = await client.post("/appeal/CLM-2026-00123/resume", json={"choice": "proceed"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_resume_invalid_choice(client):
    """POST /appeal/{claim_id}/resume with invalid choice returns 400."""
    # First start a workflow so there's an active crew
    await client.post("/appeal", json={"claim_id": "CLM-2026-00123"})
    # Give crew a moment to start
    import asyncio
    await asyncio.sleep(0.1)

    resp = await client.post("/appeal/CLM-2026-00123/resume", json={"choice": "maybe"})
    assert resp.status_code == 400
    assert "proceed" in resp.json()["detail"] or "close" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_stream_endpoint_responds(client):
    """GET /stream/{claim_id} returns SSE content type."""
    # Start a workflow first
    await client.post("/appeal", json={"claim_id": "CLM-2026-00123"})

    # Request the stream (non-streaming, just check headers)
    resp = await client.get("/stream/CLM-2026-00123")
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")


