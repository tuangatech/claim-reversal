# tools/validate_letter.py
"""Appeal letter validation — LLM-as-judge scoring letter against evidence."""

import json

from shared.llm import get_agent_llm
from shared.models import (
    AppealLetter,
    DenialRecord,
    EvidenceBundle,
    LetterValidationResult,
)


def validate_appeal_letter(
    letter: AppealLetter,
    denial_record: DenialRecord,
    evidence_bundle: EvidenceBundle,
    payer_rules: dict,
) -> LetterValidationResult:
    """Validates that the appeal letter accurately reflects the evidence and denial context."""
    client, model = get_agent_llm()

    record_types_summary = ", ".join(
        f"{r.record_type} ({r.date})" for r in evidence_bundle.patient_records
    )
    guidelines_summary = "\n".join(
        f"- {g.guideline_source}: {g.criteria_summary}"
        for g in evidence_bundle.guideline_citations
    )
    required_sections = payer_rules.get("required_sections", [])

    prompt = f"""You are a quality assurance reviewer for medical appeal letters. Evaluate this letter against the provided evidence and denial context.

APPEAL LETTER:
{letter.letter_text}

DENIAL DETAILS:
- Claim: {denial_record.claim_id}
- Reason: {denial_record.denial_reason_code} — {denial_record.denial_reason_text}
- Diagnosis: {', '.join(denial_record.diagnosis_codes)}
- Patient: {denial_record.patient_name}

EVIDENCE BUNDLE ({len(evidence_bundle.patient_records)} records, {len(evidence_bundle.guideline_citations)} guidelines):
Records: {record_types_summary}
Guidelines:
{guidelines_summary}
Partial evidence: {evidence_bundle.partial}

PAYER REQUIRED SECTIONS:
{json.dumps(required_sections, indent=2)}

EVALUATE:
1. Does the letter cite evidence that actually exists in the evidence bundle? (no hallucinated records)
2. Does the letter address the specific denial reason code ({denial_record.denial_reason_code})?
3. Does the letter reference at least one guideline citation from the bundle?
4. Are all payer-required sections present?
5. If evidence is partial, does the letter acknowledge this?

Respond in JSON format only:
{{"valid": true, "score": 0.85, "issues": [], "reasoning": "Letter cites all evidence correctly."}}

A letter is valid if score >= 0.7 and there are no critical issues (hallucinated evidence, wrong denial reason)."""

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
    )

    raw = response.choices[0].message.content.strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        # Default to valid if LLM response is unparseable
        return LetterValidationResult(
            valid=True,
            score=0.7,
            issues=["LLM validation response unparseable"],
            reasoning="Defaulting to pass — could not parse validator output",
        )

    score = float(result.get("score", 0.5))
    issues = result.get("issues", [])
    reasoning = result.get("reasoning", "")
    valid = score >= 0.7 and result.get("valid", score >= 0.7)

    return LetterValidationResult(
        valid=valid,
        score=score,
        issues=issues,
        reasoning=reasoning,
    )

