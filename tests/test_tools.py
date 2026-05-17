# tests/test_tools.py
"""Unit tests for all tool functions — called directly, no running services needed."""

import os
import sqlite3
from datetime import date, timedelta
from pathlib import Path

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
    """Resets the test database before each test and patches all DB access to use it."""
    db_file = Path(TEST_DB_PATH)
    if db_file.exists():
        db_file.unlink()

    # Patch get_connection everywhere it's imported
    monkeypatch.setattr("shared.db.get_connection", _make_test_connection)
    monkeypatch.setattr("mcp_server.tools.audit_log.get_connection", _make_test_connection)
    monkeypatch.setattr("mcp_server.tools.claim_history.get_connection", _make_test_connection)
    monkeypatch.setattr("tools.submit_appeal.get_connection", _make_test_connection)

    init_db(TEST_DB_PATH)
    seed_db(TEST_DB_PATH)

    yield

    if db_file.exists():
        db_file.unlink()


# --- Step 2.1: triage_denial ---

class TestTriageDenial:
    def test_clinical_proceed(self):
        from tools.triage_denial import triage_denial

        denial_date = (date.today() - timedelta(days=5)).isoformat()
        date_of_service = (date.today() - timedelta(days=10)).isoformat()

        r = triage_denial("CLM-2026-00123", "CO-50", 12400.0, "HUMANA", date_of_service, denial_date)

        assert r["is_clinical"] is True
        assert r["is_open"] is True
        assert r["recommendation"] == "proceed"
        assert r["worthiness_score"] >= 50

    def test_administrative(self):
        from tools.triage_denial import triage_denial

        denial_date = (date.today() - timedelta(days=5)).isoformat()
        r = triage_denial("CLM-2026-00123", "CO-4", 5000.0, "HUMANA", "2026-05-01", denial_date)

        assert r["is_clinical"] is False
        assert r["denial_type"] == "administrative"

    def test_deadline_closed(self):
        from tools.triage_denial import triage_denial

        denial_date = (date.today() - timedelta(days=100)).isoformat()
        r = triage_denial("CLM-2026-00123", "CO-50", 12400.0, "AETNA", "2026-01-01", denial_date)

        assert r["is_open"] is False
        assert r["days_remaining"] < 0

    def test_deadline_overrides_score(self):
        """Expired deadline forces recommendation=close even with high score."""
        from tools.triage_denial import triage_denial

        denial_date = (date.today() - timedelta(days=100)).isoformat()
        r = triage_denial("CLM-2026-00123", "CO-50", 12400.0, "AETNA", "2026-01-01", denial_date)

        # Score is still computed (clinical + high value = 70 minus deadline penalty)
        assert r["worthiness_score"] >= 50
        # But recommendation is overridden because deadline expired
        assert r["recommendation"] == "close"

    def test_low_worthiness(self):
        from tools.triage_denial import triage_denial

        denial_date = (date.today() - timedelta(days=5)).isoformat()
        r = triage_denial("CLM-2026-00123", "CO-50", 200.0, "HUMANA", "2026-05-01", denial_date)

        assert r["recommendation"] == "close"

    def test_unknown_code(self):
        from tools.triage_denial import triage_denial

        denial_date = (date.today() - timedelta(days=5)).isoformat()
        r = triage_denial("CLM-2026-00123", "CO-9999", 5000.0, "HUMANA", "2026-05-01", denial_date)

        assert r["is_clinical"] is False

    def test_co57_is_clinical(self):
        """CO-57 (experimental/investigational) should be classified as clinical."""
        from tools.triage_denial import triage_denial

        denial_date = (date.today() - timedelta(days=5)).isoformat()
        r = triage_denial("CLM-2026-00123", "CO-57", 5000.0, "HUMANA", "2026-05-01", denial_date)

        assert r["is_clinical"] is True
        assert r["denial_type"] == "clinical"


# --- Step 2.5: fetch_patient_records ---

class TestFetchPatientRecords:
    def test_sufficient_records(self):
        from a2a_server.tools.fetch_records import fetch_patient_records

        records = fetch_patient_records("CLM-2026-00123", "2026-05-01")

        assert len(records) >= 3
        assert records[0].record_type == "admission_note"
        assert records[0].date == "2026-05-01"
        assert records[0].content != ""

    def test_sparse_records(self):
        from a2a_server.tools.fetch_records import fetch_patient_records

        records = fetch_patient_records("CLM-2026-00199", "2026-04-15", include_supplemental=False)

        assert len(records) == 1

    def test_supplemental_records(self):
        from a2a_server.tools.fetch_records import fetch_patient_records

        records = fetch_patient_records("CLM-2026-00199", "2026-04-15", include_supplemental=True)

        assert len(records) == 3  # 1 base + 2 supplemental

    def test_not_found(self):
        from a2a_server.tools.fetch_records import fetch_patient_records

        records = fetch_patient_records("CLM-NONEXISTENT", "2026-01-01")

        assert records == []


# --- Step 2.5: fetch_lcd_policy ---

class TestFetchLcdPolicy:
    def test_mock_noop(self):
        # Ensure USE_PLAYWRIGHT is false
        os.environ["USE_PLAYWRIGHT"] = "false"
        from a2a_server.tools.fetch_lcd_policy import fetch_lcd_policy

        r = fetch_lcd_policy("J18.9")

        assert r["policy_text"] == ""
        assert r["source_url"] == ""


# --- Step 2.6: lookup_clinical_guideline ---

class TestLookupGuideline:
    def test_j189(self):
        from mcp_server.tools.lookup_guideline import lookup_clinical_guideline

        r = lookup_clinical_guideline("J18.9")

        assert "InterQual" in r["guideline_source"]
        assert len(r["medical_necessity_indicators"]) > 0
        assert r["confidence"] > 0

    def test_m1711(self):
        from mcp_server.tools.lookup_guideline import lookup_clinical_guideline

        r = lookup_clinical_guideline("M17.11")

        assert "MCG" in r["guideline_source"]
        assert len(r["medical_necessity_indicators"]) > 0

    def test_unknown(self):
        from mcp_server.tools.lookup_guideline import lookup_clinical_guideline

        r = lookup_clinical_guideline("X99.99")

        assert r["medical_necessity_indicators"] == []
        assert r["confidence"] == 0.0


# --- Step 2.6: get_payer_appeal_rules ---

class TestPayerRules:
    def test_bcbs(self):
        from mcp_server.tools.payer_rules import get_payer_appeal_rules

        r = get_payer_appeal_rules("BCBS")

        assert r["appeal_window_days"] == 90
        assert len(r["required_sections"]) == 6
        assert r["submission_format"] == "portal"

    def test_unknown_payer(self):
        from mcp_server.tools.payer_rules import get_payer_appeal_rules

        r = get_payer_appeal_rules("XYZ_UNKNOWN")

        assert r["appeal_window_days"] == 90  # default
        assert r["submission_format"] == "fax"  # default


# --- Step 2.6: log_appeal_event ---

class TestAuditLog:
    def test_log_event(self):
        from mcp_server.tools.audit_log import log_appeal_event

        r = log_appeal_event("CLM-2026-00123", "test_event", {"key": "value"}, "test_agent")

        assert r["event_id"] != ""
        assert r["timestamp"] != ""

        # Verify row exists in DB
        conn = _make_test_connection()
        row = conn.execute(
            "SELECT * FROM appeal_events WHERE id = ?", (r["event_id"],)
        ).fetchone()
        conn.close()

        assert row is not None
        assert row["claim_id"] == "CLM-2026-00123"
        assert row["event_type"] == "test_event"


# --- Step 2.6: get_claim_history ---

class TestClaimHistory:
    def test_found(self):
        from mcp_server.tools.claim_history import get_claim_history

        r = get_claim_history("CLM-2026-00123")

        assert r["status"] != "not_found"
        assert r["claim_id"] == "CLM-2026-00123"

    def test_not_found(self):
        from mcp_server.tools.claim_history import get_claim_history

        r = get_claim_history("CLM-NONEXISTENT")

        assert r["status"] == "not_found"


# --- Step 2.3: physician_review ---

class TestPhysicianReview:
    def test_required_high_value_bcbs(self):
        from tools.physician_review import physician_review

        r = physician_review("CLM-2026-00123", "clinical", 15000.0, "BCBS", "test letter")

        assert r.physician_required is True
        assert r.review_status == "approved"

    def test_not_required(self):
        from tools.physician_review import physician_review

        r = physician_review("CLM-2026-00123", "clinical", 800.0, "AETNA", "test letter")

        assert r.physician_required is False
        assert r.review_status == "bypassed"

    def test_administrative_not_required(self):
        """Administrative denials never require physician review."""
        from tools.physician_review import physician_review

        r = physician_review("CLM-2026-00123", "administrative", 50000.0, "BCBS", "test letter")

        assert r.physician_required is False
        assert r.review_status == "bypassed"


# --- Step 2.4: submit_appeal ---

class TestSubmitAppeal:
    def test_submit(self):
        from tools.submit_appeal import submit_appeal

        r = submit_appeal("CLM-2026-00123", "HUMANA", "test letter text")

        assert r.confirmation_number.startswith("CONF-HUM-")
        assert r.submitted_at != ""
        assert r.payer_id == "HUMANA"
        assert r.submission_method == "mail"  # HUMANA uses mail


