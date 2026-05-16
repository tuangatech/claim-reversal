# tests/test_a2a_server.py
"""Integration tests for the A2A server HTTP endpoints."""

import sqlite3
from pathlib import Path

import httpx
import pytest

from shared.db import init_db, seed_db

TEST_DB_PATH = "data/claims_test.db"


def _make_test_connection(db_path: str = TEST_DB_PATH) -> sqlite3.Connection:
    """Returns a connection to the test database."""
    conn = sqlite3.connect(TEST_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@pytest.fixture(autouse=True)
def reset_db(monkeypatch):
    """Resets the test database before each test."""
    db_file = Path(TEST_DB_PATH)
    if db_file.exists():
        db_file.unlink()

    monkeypatch.setattr("shared.db.get_connection", _make_test_connection)
    monkeypatch.setattr("a2a_server.graph.get_connection", _make_test_connection)
    monkeypatch.setattr("mcp_server.tools.audit_log.get_connection", _make_test_connection)
    monkeypatch.setattr("mcp_server.tools.claim_history.get_connection", _make_test_connection)
    monkeypatch.setattr("tools.submit_appeal.get_connection", _make_test_connection)

    init_db(TEST_DB_PATH)
    seed_db(TEST_DB_PATH)

    yield

    if db_file.exists():
        db_file.unlink()


@pytest.fixture
def client():
    """Creates an httpx async client for the A2A server."""
    from a2a_server.app import app
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


# --- Non-LLM tests ---

class TestA2AEndpoints:
    @pytest.mark.asyncio
    async def test_health(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "evidence-agent"

    @pytest.mark.asyncio
    async def test_agent_card(self, client):
        resp = await client.get("/.well-known/agent-card.json")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Clinical Evidence Agent"
        assert data["protocolVersion"] == "0.3.0"
        assert len(data["skills"]) == 1
        assert data["skills"][0]["name"] == "clinical_evidence_gathering"

    @pytest.mark.asyncio
    async def test_invalid_payload_missing_messages(self, client):
        resp = await client.post("/a2a", json={})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_invalid_payload_missing_fields(self, client):
        resp = await client.post("/a2a", json={
            "messages": [{"role": "user", "parts": [{"type": "data", "data": {
                "claim_id": "CLM-2024-00123",
                # Missing diagnosis_codes, payer_id, denial_reason_code
            }}]}]
        })
        assert resp.status_code == 400
        assert "Missing required fields" in resp.json()["error"]

    @pytest.mark.asyncio
    async def test_invalid_json(self, client):
        resp = await client.post(
            "/a2a",
            content=b"not json",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 400


# --- LLM-dependent tests ---

@pytest.mark.llm
class TestA2AIntegration:
    @pytest.mark.asyncio
    async def test_task_send_sufficient(self, client):
        """CLM-2024-00123 should complete with evidence bundle."""
        resp = await client.post("/a2a", json={
            "messages": [{"role": "user", "parts": [{"type": "data", "data": {
                "claim_id": "CLM-2024-00123",
                "diagnosis_codes": ["J18.9"],
                "payer_id": "HUMANA",
                "denial_reason_code": "CO-50",
            }}]}]
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"]["state"] == "completed"
        evidence = data["messages"][0]["parts"][0]["data"]["evidence_bundle"]
        assert evidence is not None
        assert evidence["partial"] is False

    @pytest.mark.asyncio
    async def test_task_send_hitl_and_resume_proceed(self, client):
        """CLM-2024-00199 should suspend, then resume with proceed."""
        # Initial request — should suspend
        resp = await client.post("/a2a", json={
            "messages": [{"role": "user", "parts": [{"type": "data", "data": {
                "claim_id": "CLM-2024-00199",
                "diagnosis_codes": ["M17.11"],
                "payer_id": "BCBS",
                "denial_reason_code": "CO-50",
            }}]}]
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"]["state"] == "input-required"
        task_id = data["id"]
        assert task_id is not None

        hitl_data = data["messages"][0]["parts"][0]["data"]
        assert "options" in hitl_data
        assert "proceed" in hitl_data["options"]

        # Resume with proceed
        resp2 = await client.post("/a2a", json={
            "id": task_id,
            "messages": [{"role": "user", "parts": [{"type": "data", "data": {
                "human_choice": "proceed",
            }}]}]
        })
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["status"]["state"] == "completed"
        evidence = data2["messages"][0]["parts"][0]["data"]["evidence_bundle"]
        assert evidence["partial"] is True

    @pytest.mark.asyncio
    async def test_task_send_hitl_close(self, client):
        """CLM-2024-00199 should suspend, then close on human decision."""
        # Initial request — should suspend
        resp = await client.post("/a2a", json={
            "messages": [{"role": "user", "parts": [{"type": "data", "data": {
                "claim_id": "CLM-2024-00199",
                "diagnosis_codes": ["M17.11"],
                "payer_id": "BCBS",
                "denial_reason_code": "CO-50",
            }}]}]
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"]["state"] == "input-required"
        task_id = data["id"]

        # Resume with close
        resp2 = await client.post("/a2a", json={
            "id": task_id,
            "messages": [{"role": "user", "parts": [{"type": "data", "data": {
                "human_choice": "close",
            }}]}]
        })
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["status"]["state"] == "completed"
        assert data2["messages"][0]["parts"][0]["data"]["closed_reason"] == "insufficient_evidence_human_closed"

