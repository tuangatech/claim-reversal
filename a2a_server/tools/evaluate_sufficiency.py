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

    # Collect all indicator names from guidelines
    all_indicators = []
    for g in guideline_citations:
        all_indicators.extend(g.medical_necessity_indicators)

    indicators_list = "\n".join(f"  - \"{ind}\"" for ind in all_indicators)

    prompt = f"""You are a strict clinical reviewer evaluating whether gathered medical evidence is sufficient to support a medical necessity appeal.

DIAGNOSIS CODES: {', '.join(diagnosis_codes)}

CLINICAL RECORDS GATHERED:
{records_text}

APPLICABLE GUIDELINES:
{guidelines_text}

INDICATORS TO EVALUATE:
{indicators_list}

For EACH indicator listed above, determine if it is "met" or "unmet" based on the clinical records.

RULES:
- "met" = records contain EXPLICIT clinical data for it (vitals, lab values, scores, dates, treatment records).
- "unmet" = no record provides specific data. Vague references or patient self-reports without corroborating records do NOT count.
- Time-based criteria must be met exactly: "3 months of conservative treatment" requires documentation of 3+ months, not 4 weeks.
- A patient's verbal statement (e.g., "patient states he did PT") does NOT satisfy an indicator unless corroborated by treatment records with dates and outcomes.

Return ONLY valid JSON with exactly these keys:
{{"indicators": [{{"name": "<indicator>", "met": true/false, "evidence": "<brief cite or 'none'>"}}], "reasoning": "<one sentence summary>"}}"""

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
    indicators = result["indicators"]
    reasoning = result["reasoning"]

    # Compute score deterministically from indicator verdicts
    met_count = sum(1 for ind in indicators if ind.get("met") is True)
    total_count = len(indicators) if indicators else 1
    score = (met_count / total_count) * 10

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
