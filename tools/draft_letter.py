# tools/draft_letter.py
"""Appeal letter drafting tool — composes and formats the appeal letter."""

from shared.models import AppealLetter, DenialRecord, EvidenceBundle


def draft_appeal_letter(
    denial_record: DenialRecord,
    evidence_bundle: EvidenceBundle,
    payer_rules: dict,
) -> AppealLetter:
    """Drafts a formal medical appeal letter using LLM composition."""
    return {}

