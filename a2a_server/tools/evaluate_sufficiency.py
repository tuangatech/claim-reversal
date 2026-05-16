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

    prompt = f"""You are a strict clinical reviewer evaluating whether gathered medical evidence is sufficient to support a medical necessity appeal. You must evaluate indicator by indicator.

DIAGNOSIS CODES: {', '.join(diagnosis_codes)}

CLINICAL RECORDS GATHERED:
{records_text}

APPLICABLE GUIDELINES:
{guidelines_text}

EVALUATION METHOD — follow exactly:
1. List each medical necessity indicator from the guidelines above.
2. For EACH indicator, determine if there is DIRECT documentation in the clinical records that explicitly addresses it. An indicator is "met" ONLY if a record directly states or documents the specific criterion. Clinical inference or implication does NOT count.
3. Calculate the score: score = (number of indicators with direct documentation / total indicators) * 10

SCORING RULES:
- An imaging report alone does NOT satisfy "functional limitation documented" or "PT trial completed" or "failed conservative treatment" — those require their own dedicated records.
- A single record type (e.g., only imaging) can typically satisfy at most 1-2 indicators.
- If fewer than 70% of indicators have direct documentation, the score MUST be below 7.
- A partially completed PT trial (e.g., 4 weeks when 3 months is required) does NOT satisfy the "failed conservative treatment >= 3 months" indicator.
- "Patient states he completed PT" without duration/dates documentation does NOT count as meeting the PT trial indicator.
- Be strict: payers deny appeals that lack explicit documentation for each criterion.

Return ONLY valid JSON with exactly these keys:
{{"score": <float 0-10>, "reasoning": "<list which indicators are met vs unmet>"}}"""

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

    # Map score to sufficiency enum — threshold 7 means > 70% of indicators must be met
    sufficiency = (
        EvidenceSufficiency.SUFFICIENT if score >= 7
        else EvidenceSufficiency.INSUFFICIENT
    )

    return {
        "sufficiency": sufficiency,
        "reasoning": reasoning,
        "score": score,
    }


