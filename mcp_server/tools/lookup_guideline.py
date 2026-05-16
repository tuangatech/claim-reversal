# mcp_server/tools/lookup_guideline.py
"""Returns clinical guideline criteria for a diagnosis code."""

GUIDELINES = {
    "J18.9": {
        "diagnosis_code": "J18.9",
        "guideline_source": "InterQual 2024 — Acute Care",
        "criteria_summary": (
            "Inpatient admission for community-acquired pneumonia is appropriate when: "
            "(1) oxygen saturation < 92% on room air, (2) CURB-65 score >= 2, "
            "(3) IV antibiotics required, or (4) significant comorbidities precluding "
            "outpatient management."
        ),
        "medical_necessity_indicators": [
            "hypoxia requiring supplemental O2",
            "CURB-65 >= 2",
            "IV antibiotic therapy",
            "elevated inflammatory markers (WBC, CRP, procalcitonin)",
        ],
        "confidence": 0.92,
    },
    "M17.11": {
        "diagnosis_code": "M17.11",
        "guideline_source": "MCG 27th Edition — Surgical Care",
        "criteria_summary": (
            "Total knee arthroplasty is appropriate when: "
            "(1) radiographic evidence of Grade III-IV OA, "
            "(2) failure of at least 3 months of conservative treatment including PT, NSAIDs, and injections, "
            "(3) documented functional limitation (unable to walk > 2 blocks), and "
            "(4) BMI < 40 or optimization plan documented."
        ),
        "medical_necessity_indicators": [
            "radiographic OA Grade III-IV",
            "failed conservative treatment >= 3 months",
            "functional limitation documented",
            "PT trial completed",
            "BMI optimization if applicable",
        ],
        "confidence": 0.85,
    },
}


def lookup_clinical_guideline(diagnosis_code: str) -> dict:
    """Returns InterQual/MCG criteria for a diagnosis code."""

    if diagnosis_code in GUIDELINES:
        return GUIDELINES[diagnosis_code]

    return {
        "diagnosis_code": diagnosis_code,
        "guideline_source": "No specific guideline found",
        "criteria_summary": "No matching clinical guideline available for this diagnosis code.",
        "medical_necessity_indicators": [],
        "confidence": 0.0,
    }
