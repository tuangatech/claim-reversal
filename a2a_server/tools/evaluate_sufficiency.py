# a2a_server/tools/evaluate_sufficiency.py
"""Scores whether gathered evidence is sufficient for a medical necessity argument."""

import json

from a2a_server.state import EvidenceSufficiency
from shared.llm import get_agent_llm
from shared.models import ClinicalRecord, GuidelineCitation


def evaluate_evidence_sufficiency(
    patient_records: list[ClinicalRecord],
    guideline_citations: list[GuidelineCitation],
    diagnosis_codes: list[str],
) -> dict:
    """LLM-scored evaluation of evidence sufficiency."""

    client, model = get_agent_llm()

    records_text = "\n".join(
        f"- [{r.record_type}] ({r.date}, {r.author or 'unknown'}): {r.content}"
        for r in patient_records
    )

    guidelines_text = "\n".join(
        f"- {g.guideline_source}: {g.criteria_summary}\n  Indicators: {', '.join(g.medical_necessity_indicators)}"
        for g in guideline_citations
    )

    prompt = f"""You are a clinical reviewer evaluating whether gathered medical evidence is sufficient to support a medical necessity appeal.

DIAGNOSIS CODES: {', '.join(diagnosis_codes)}

CLINICAL RECORDS GATHERED:
{records_text}

APPLICABLE GUIDELINES:
{guidelines_text}

Score the evidence sufficiency on a scale of 0-10:
- 0-3: Clearly insufficient — missing critical documentation
- 4-5: Borderline — some evidence but significant gaps
- 6-7: Adequate — meets most criteria with reasonable documentation
- 8-10: Strong — comprehensive evidence clearly meeting all criteria

Consider:
1. Does the evidence address each medical necessity indicator from the guidelines?
2. Are there gaps in documentation that would weaken the appeal?
3. Is the clinical narrative consistent and compelling?

Return ONLY valid JSON with exactly these keys:
{{"score": <float 0-10>, "reasoning": "<brief explanation of score>"}}"""

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
    )

    response_text = response.choices[0].message.content.strip()

    # Parse JSON response, handling potential markdown code fences
    if response_text.startswith("```"):
        response_text = response_text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    result = json.loads(response_text)
    score = float(result["score"])
    reasoning = result["reasoning"]

    # Map score to sufficiency enum
    sufficiency = (
        EvidenceSufficiency.SUFFICIENT if score >= 6
        else EvidenceSufficiency.INSUFFICIENT
    )

    return {
        "sufficiency": sufficiency,
        "reasoning": reasoning,
        "score": score,
    }

