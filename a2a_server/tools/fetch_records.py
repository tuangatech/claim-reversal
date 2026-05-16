# a2a_server/tools/fetch_records.py
"""Fetches clinical records for a claim from mock fixtures."""

import json
from pathlib import Path

from shared.models import ClinicalRecord


def fetch_patient_records(
    claim_id: str,
    date_of_service: str,
    include_supplemental: bool = False,
) -> list[ClinicalRecord]:
    """Returns clinical records from hardcoded mock data."""

    file_path = Path("data/mock_records") / f"{claim_id}.json"

    if not file_path.exists():
        return []

    data = json.loads(file_path.read_text(encoding="utf-8"))

    records = [
        ClinicalRecord(**entry) for entry in data.get("records", [])
    ]

    if include_supplemental:
        supplemental = [
            ClinicalRecord(**entry) for entry in data.get("supplemental_records", [])
        ]
        records.extend(supplemental)

    return records

