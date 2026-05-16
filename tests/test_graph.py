# tests/test_graph.py
"""Tests for the LangGraph Clinical Evidence graph — direct invocation."""

import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest
from langgraph.types import Command

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


def _make_initial_state(claim_id: str, diagnosis_codes: list, payer_id: str) -> dict:
    """Builds a fresh AppealState for graph invocation."""
    return {
        "claim_id": claim_id,
        "diagnosis_codes": diagnosis_codes,
        "payer_id": payer_id,
        "denial_reason_code": "CO-50",
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


# --- Node unit tests (no LLM) ---

class TestNodeUnits:
    def test_fetch_records_node(self):
        from a2a_server.graph import fetch_records

        state = _make_initial_state("CLM-2024-00123", ["J18.9"], "HUMANA")
        result = fetch_records(state)

        assert "patient_records" in result
        assert len(result["patient_records"]) >= 3
        assert result["patient_records"][0]["record_type"] == "admission_note"

    def test_fetch_records_supplemental(self):
        from a2a_server.graph import fetch_records

        state = _make_initial_state("CLM-2024-00199", ["M17.11"], "BCBS")
        state["include_supplemental"] = True
        result = fetch_records(state)

        assert len(result["patient_records"]) == 3

    def test_lookup_guideline_node(self):
        from a2a_server.graph import lookup_guideline

        state = _make_initial_state("CLM-2024-00123", ["J18.9"], "HUMANA")
        result = lookup_guideline(state)

        assert "guideline_citations" in result
        assert len(result["guideline_citations"]) == 1
        assert "InterQual" in result["guideline_citations"][0]["guideline_source"]

    def test_lookup_guideline_multiple_codes(self):
        from a2a_server.graph import lookup_guideline

        state = _make_initial_state("CLM-2024-00123", ["J18.9", "M17.11"], "HUMANA")
        result = lookup_guideline(state)

        assert len(result["guideline_citations"]) == 2

    def test_increment_retry_node(self):
        from a2a_server.graph import increment_retry

        state = _make_initial_state("CLM-2024-00199", ["M17.11"], "BCBS")
        state["retry_count"] = 0
        result = increment_retry(state)

        assert result["retry_count"] == 1
        assert result["include_supplemental"] is True

    def test_increment_retry_second(self):
        from a2a_server.graph import increment_retry

        state = _make_initial_state("CLM-2024-00199", ["M17.11"], "BCBS")
        state["retry_count"] = 1
        result = increment_retry(state)

        assert result["retry_count"] == 2

    def test_build_bundle_node(self):
        from a2a_server.graph import build_bundle

        state = _make_initial_state("CLM-2024-00123", ["J18.9"], "HUMANA")
        state["patient_records"] = [
            {"record_type": "admission_note", "content": "test", "date": "2026-05-01", "author": "Dr. Test"}
        ]
        state["guideline_citations"] = [
            {"diagnosis_code": "J18.9", "guideline_source": "InterQual 2024", "criteria_summary": "test", "medical_necessity_indicators": ["test"], "confidence": 0.9}
        ]
        state["sufficiency_reasoning"] = "Evidence meets criteria"

        result = build_bundle(state)

        assert result["evidence_bundle"] is not None
        assert result["evidence_bundle"]["partial"] is False
        assert result["evidence_bundle"]["claim_id"] == "CLM-2024-00123"

    def test_build_bundle_partial_node(self):
        from a2a_server.graph import build_bundle_partial

        state = _make_initial_state("CLM-2024-00199", ["M17.11"], "BCBS")
        state["patient_records"] = [
            {"record_type": "imaging_report", "content": "MRI knee", "date": "2026-04-10", "author": "Dr. Park"}
        ]
        state["guideline_citations"] = [
            {"diagnosis_code": "M17.11", "guideline_source": "MCG 27th", "criteria_summary": "test", "medical_necessity_indicators": ["test"], "confidence": 0.85}
        ]
        state["sufficiency_reasoning"] = "Insufficient documentation"

        result = build_bundle_partial(state)

        assert result["evidence_bundle"]["partial"] is True

    def test_close_case_node(self):
        from a2a_server.graph import close_case

        state = _make_initial_state("CLM-2024-00199", ["M17.11"], "BCBS")
        result = close_case(state)

        assert result["closed_reason"] == "insufficient_evidence_human_closed"

    def test_fetch_lcd_node(self):
        from a2a_server.graph import fetch_lcd
        import os
        os.environ["USE_PLAYWRIGHT"] = "false"

        state = _make_initial_state("CLM-2024-00123", ["J18.9"], "HUMANA")
        result = fetch_lcd(state)

        assert result["lcd_policy_text"] == ""


# --- Conditional edge logic tests (no LLM) ---

class TestRouting:
    def test_route_sufficient(self):
        from a2a_server.graph import route_after_evaluation
        from a2a_server.state import EvidenceSufficiency

        state = _make_initial_state("CLM-2024-00123", ["J18.9"], "HUMANA")
        state["sufficiency"] = EvidenceSufficiency.SUFFICIENT
        state["retry_count"] = 0

        assert route_after_evaluation(state) == "build_bundle"

    def test_route_insufficient_retry(self):
        from a2a_server.graph import route_after_evaluation
        from a2a_server.state import EvidenceSufficiency

        state = _make_initial_state("CLM-2024-00199", ["M17.11"], "BCBS")
        state["sufficiency"] = EvidenceSufficiency.INSUFFICIENT
        state["retry_count"] = 0

        assert route_after_evaluation(state) == "increment_retry"

    def test_route_insufficient_hitl(self):
        from a2a_server.graph import route_after_evaluation
        from a2a_server.state import EvidenceSufficiency

        state = _make_initial_state("CLM-2024-00199", ["M17.11"], "BCBS")
        state["sufficiency"] = EvidenceSufficiency.INSUFFICIENT
        state["retry_count"] = 2

        assert route_after_evaluation(state) == "human_review_interrupt"

    def test_route_hitl_proceed(self):
        from a2a_server.graph import route_after_hitl
        from a2a_server.state import HumanChoice

        state = _make_initial_state("CLM-2024-00199", ["M17.11"], "BCBS")
        state["human_choice"] = HumanChoice.PROCEED

        assert route_after_hitl(state) == "build_bundle_partial"

    def test_route_hitl_close(self):
        from a2a_server.graph import route_after_hitl
        from a2a_server.state import HumanChoice

        state = _make_initial_state("CLM-2024-00199", ["M17.11"], "BCBS")
        state["human_choice"] = HumanChoice.CLOSE

        assert route_after_hitl(state) == "close_case"


# --- Full graph integration tests (require LLM) ---

@pytest.mark.llm
class TestGraphIntegration:
    def test_sufficient_first_try(self):
        """CLM-2024-00123 (pneumonia) should be sufficient on first evaluation."""
        from a2a_server.graph import graph

        config = {"configurable": {"thread_id": f"test-sufficient-{uuid4().hex[:8]}"}}
        state = _make_initial_state("CLM-2024-00123", ["J18.9"], "HUMANA")
        result = graph.invoke(state, config=config)

        assert result["evidence_bundle"] is not None
        assert result["evidence_bundle"]["partial"] is False
        assert result["retry_count"] == 0
        assert result["hitl_triggered"] is False

    def test_insufficient_triggers_retry(self):
        """CLM-2024-00199 (knee) should trigger at least one retry."""
        from a2a_server.graph import graph

        config = {"configurable": {"thread_id": f"test-retry-{uuid4().hex[:8]}"}}
        state = _make_initial_state("CLM-2024-00199", ["M17.11"], "BCBS")
        result = graph.invoke(state, config=config)

        # Graph either completed with retries or suspended at HITL
        assert result["retry_count"] >= 1

    def test_hitl_suspend(self):
        """CLM-2024-00199 should suspend after 2 retries."""
        from a2a_server.graph import graph

        config = {"configurable": {"thread_id": f"test-hitl-{uuid4().hex[:8]}"}}
        state = _make_initial_state("CLM-2024-00199", ["M17.11"], "BCBS")
        result = graph.invoke(state, config=config)

        # Verify suspension
        state_snapshot = graph.get_state(config)
        assert state_snapshot.next  # non-empty means suspended
        assert result.get("evidence_bundle") is None
        assert result["retry_count"] >= 2

    def test_hitl_resume_proceed(self):
        """Invoke fresh, suspend, then resume with proceed — self-contained."""
        from a2a_server.graph import graph

        thread_id = f"test-proceed-{uuid4().hex[:8]}"
        config = {"configurable": {"thread_id": thread_id}}
        state = _make_initial_state("CLM-2024-00199", ["M17.11"], "BCBS")

        # Invoke to suspension
        graph.invoke(state, config=config)

        # Verify suspended
        state_snapshot = graph.get_state(config)
        assert state_snapshot.next

        # Resume with proceed
        result = graph.invoke(
            Command(resume={"choice": "proceed"}),
            config=config,
        )

        assert result["evidence_bundle"] is not None
        assert result["evidence_bundle"]["partial"] is True

    def test_hitl_resume_close(self):
        """Invoke fresh, suspend, then resume with close — self-contained."""
        from a2a_server.graph import graph

        thread_id = f"test-close-{uuid4().hex[:8]}"
        config = {"configurable": {"thread_id": thread_id}}
        state = _make_initial_state("CLM-2024-00199", ["M17.11"], "BCBS")

        # Invoke to suspension
        graph.invoke(state, config=config)

        # Verify suspended
        state_snapshot = graph.get_state(config)
        assert state_snapshot.next

        # Resume with close
        result = graph.invoke(
            Command(resume={"choice": "close"}),
            config=config,
        )

        assert result["closed_reason"] == "insufficient_evidence_human_closed"
        assert result.get("evidence_bundle") is None
