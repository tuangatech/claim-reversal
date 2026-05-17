# tools/draft_letter.py
"""Appeal letter drafting tool — composes and formats the appeal letter."""

import json
from datetime import datetime, timezone

from shared.llm import get_agent_llm
from shared.models import AppealLetter, DenialRecord, EvidenceBundle


def draft_appeal_letter(
    denial_record: DenialRecord,
    evidence_bundle: EvidenceBundle,
    payer_rules: dict,
    validation_feedback: list[str] | None = None,
) -> AppealLetter:
    """Drafts a formal medical appeal letter using LLM composition."""

    client, model = get_agent_llm()

    # Summarize clinical records for the prompt
    records_summary = "\n".join(
        f"- [{r.record_type}] ({r.date}) {r.content[:200]}"
        for r in evidence_bundle.patient_records
    )

    # Summarize guideline citations
    guidelines_summary = "\n".join(
        f"- {g.guideline_source}: {g.criteria_summary}"
        for g in evidence_bundle.guideline_citations
    )

    required_sections = payer_rules.get("required_sections", [])
    partial_note = (
        "\nIMPORTANT: The clinical evidence is PARTIAL — not all documentation was available. "
        "Note this in the letter but still argue medical necessity with available evidence."
        if evidence_bundle.partial
        else ""
    )

    feedback_note = ""
    if validation_feedback:
        formatted_issues = "\n".join(f"- {issue}" for issue in validation_feedback)
        feedback_note = (
            f"\n\nIMPORTANT — PREVIOUS DRAFT FAILED VALIDATION. Fix these issues:\n"
            f"{formatted_issues}\n\n"
            "Do NOT hallucinate evidence. Only cite records and guidelines that appear in the evidence bundle above."
        )

    prompt = f"""Write a formal medical appeal letter for a clinical denial reversal.

DENIAL DETAILS:
- Payer: {denial_record.payer_name} ({denial_record.payer_id})
- Patient: {denial_record.patient_name} (ID: {denial_record.patient_id})
- Claim ID: {denial_record.claim_id}
- Date of Service: {denial_record.date_of_service}
- Denial Reason: {denial_record.denial_reason_code} — {denial_record.denial_reason_text}
- Diagnosis Codes: {', '.join(denial_record.diagnosis_codes)}
- Claim Amount: ${denial_record.claim_amount:,.2f}

CLINICAL RECORDS:
{records_summary}

CLINICAL GUIDELINES:
{guidelines_summary}
{partial_note}

PAYER REQUIRED SECTIONS (include all of these):
{json.dumps(required_sections, indent=2)}

SUBMISSION FORMAT: {payer_rules.get('submission_format', 'mail')}
PAYER ADDRESS: {payer_rules.get('contact_address', 'Appeals Department')}
{feedback_note}
Write a professional, persuasive appeal letter that:
1. References the specific denial and claim
2. Presents the clinical evidence supporting medical necessity
3. Cites the relevant clinical guidelines
4. Addresses the payer's stated denial reason directly
5. Includes all payer-required sections
6. Closes with a clear request for reconsideration

Write ONLY the letter text. No commentary or explanation outside the letter."""

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )

    letter_text = response.choices[0].message.content

    return AppealLetter(
        claim_id=denial_record.claim_id,
        payer_id=denial_record.payer_id,
        payer_name=denial_record.payer_name,
        letter_text=letter_text,
        submission_format=payer_rules.get("submission_format", "mail"),
        required_attachments=[r.record_type for r in evidence_bundle.patient_records],
        drafted_at=datetime.now(timezone.utc).isoformat(),
    )


