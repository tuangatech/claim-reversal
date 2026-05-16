# a2a_server/tools/fetch_records.py
"""Fetches clinical records for a claim from mock fixtures."""

from shared.models import ClinicalRecord


def fetch_patient_records(claim_id: str, date_of_service: str) -> list[ClinicalRecord]:
    """Returns clinical records from hardcoded mock data."""
    return []

