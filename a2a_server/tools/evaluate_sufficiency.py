# a2a_server/tools/evaluate_sufficiency.py
"""Scores whether gathered evidence is sufficient for a medical necessity argument."""

from shared.models import ClinicalRecord, GuidelineCitation


def evaluate_evidence_sufficiency(
    patient_records: list[ClinicalRecord],
    guideline_citations: list[GuidelineCitation],
    diagnosis_codes: list[str],
) -> dict:
    """LLM-scored evaluation of evidence sufficiency."""
    return {}

