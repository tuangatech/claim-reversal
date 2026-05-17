# tests/test_validate_letter.py
"""Tests for the appeal letter validation tool (LLM-as-judge)."""

import pytest

from shared.models import (
    AppealLetter,
    ClinicalRecord,
    DenialRecord,
    EvidenceBundle,
    GuidelineCitation,
)

DENIAL_RECORD = DenialRecord(
    claim_id="CLM-2026-00123",
    patient_name="Maria Santos",
    patient_id="PAT-67234",
    payer_id="HUMANA",
    payer_name="Humana Medicare Advantage",
    denial_reason_code="CO-50",
    denial_reason_text="Not medically necessary",
    is_clinical=True,
    diagnosis_codes=["J18.9"],
    date_of_service="2026-05-01",
    denial_date="2026-05-10",
    claim_amount=12400.0,
    appeal_deadline="2026-07-09",
    days_remaining=53,
    worthiness_score=85,
    recommendation="proceed",
)

EVIDENCE_BUNDLE = EvidenceBundle(
    claim_id="CLM-2026-00123",
    patient_records=[
        ClinicalRecord(
            record_type="admission_note",
            content="67F presenting with fever 102.4F, productive cough, tachypnea. CXR shows bilateral infiltrates. WBC 18.2. Started on IV antibiotics.",
            date="2026-05-01",
            author="Dr. Rodriguez",
        ),
        ClinicalRecord(
            record_type="progress_note",
            content="Day 2: O2 sat 89% on RA, requiring 3L NC. CRP 145. Blood cultures pending. Continuing IV levofloxacin.",
            date="2026-05-02",
            author="Dr. Rodriguez",
        ),
        ClinicalRecord(
            record_type="lab_result",
            content="WBC: 18.2 (H), CRP: 145 mg/L (H), Procalcitonin: 2.4 ng/mL (H), Blood culture: Streptococcus pneumoniae",
            date="2026-05-01",
            author="Lab",
        ),
    ],
    guideline_citations=[
        GuidelineCitation(
            diagnosis_code="J18.9",
            guideline_source="InterQual 2024 — Acute Care: Pneumonia",
            criteria_summary="Inpatient admission justified when: O2 sat <90% on RA, WBC >15k, or hemodynamic instability",
            medical_necessity_indicators=["hypoxia", "leukocytosis", "IV antibiotics required"],
            confidence=0.92,
        ),
    ],
    sufficiency_reasoning="Evidence demonstrates clear medical necessity.",
    partial=False,
)

PAYER_RULES = {
    "payer_name": "Humana Medicare Advantage",
    "appeal_window_days": 60,
    "submission_format": "mail",
    "required_sections": [
        "patient_identification",
        "claim_reference",
        "clinical_summary",
        "medical_necessity_argument",
        "guideline_citations",
        "conclusion_and_request",
    ],
    "contact_address": "Humana Appeals, P.O. Box 14165, Lexington, KY 40512",
}

GOOD_LETTER_TEXT = """
Dear Humana Medicare Advantage Appeals Department,

RE: Appeal of Denial — Claim CLM-2026-00123
Patient: Maria Santos (PAT-67234)
Date of Service: 2026-05-01
Denial Reason: CO-50 — Not medically necessary

PATIENT IDENTIFICATION:
Maria Santos, DOB 1959-03-14, Member ID PAT-67234.

CLAIM REFERENCE:
We are appealing the denial of claim CLM-2026-00123 for inpatient services totaling $12,400.00.

CLINICAL SUMMARY:
The patient presented on 2026-05-01 with fever of 102.4F, productive cough, and tachypnea.
Chest X-ray showed bilateral infiltrates. WBC was elevated at 18.2. O2 saturation was 89% on
room air requiring supplemental oxygen via nasal cannula. Blood cultures grew Streptococcus pneumoniae.
IV antibiotics (levofloxacin) were initiated.

MEDICAL NECESSITY ARGUMENT:
The patient's condition met criteria for inpatient admission based on:
- Hypoxia (O2 sat 89% on RA, requiring supplemental oxygen)
- Leukocytosis (WBC 18.2, significantly elevated)
- Need for IV antibiotics not available in outpatient setting
- Hemodynamic monitoring required due to sepsis markers (Procalcitonin 2.4)

GUIDELINE CITATIONS:
Per InterQual 2024 — Acute Care: Pneumonia guidelines, inpatient admission is justified when
O2 sat <90% on RA, WBC >15k, or hemodynamic instability is present. This patient met multiple criteria.

CONCLUSION AND REQUEST:
We respectfully request reconsideration of this denial. The clinical evidence clearly demonstrates
that inpatient admission was medically necessary. Please reverse the denial and process payment.

Sincerely,
Appeals Department
St. Mary's Regional Medical Center
"""


@pytest.mark.llm
class TestValidateLetter:
    """Tests for validate_appeal_letter — requires LLM API."""

    def test_valid_letter_passes(self):
        from tools.validate_letter import validate_appeal_letter

        letter = AppealLetter(
            claim_id="CLM-2026-00123",
            payer_id="HUMANA",
            payer_name="Humana Medicare Advantage",
            letter_text=GOOD_LETTER_TEXT,
            submission_format="mail",
            required_attachments=["admission_note", "progress_note", "lab_result"],
            drafted_at="2026-05-17T10:00:00Z",
        )

        result = validate_appeal_letter(letter, DENIAL_RECORD, EVIDENCE_BUNDLE, PAYER_RULES)

        assert result.valid is True
        assert result.score >= 0.7

    def test_hallucinated_evidence_fails(self):
        from tools.validate_letter import validate_appeal_letter

        bad_text = """
        Dear Appeals Department,
        RE: Claim CLM-2026-00123, Patient Maria Santos
        Denial: CO-50 — Not medically necessary

        Based on the MRI performed on 2026-01-15 showing advanced stage 4 metastatic cancer,
        and the PET scan confirming spread to lymph nodes, this patient clearly required
        inpatient surgical intervention. The echocardiogram from 2026-02-20 showed ejection
        fraction of 25% requiring ICU-level monitoring.

        Per NCCN guidelines for oncology staging, this level of care is standard.

        Please reverse this denial.
        """

        letter = AppealLetter(
            claim_id="CLM-2026-00123",
            payer_id="HUMANA",
            payer_name="Humana Medicare Advantage",
            letter_text=bad_text,
            submission_format="mail",
            required_attachments=["admission_note"],
            drafted_at="2026-05-17T10:00:00Z",
        )

        result = validate_appeal_letter(letter, DENIAL_RECORD, EVIDENCE_BUNDLE, PAYER_RULES)

        assert result.valid is False
        assert result.score < 0.7

    def test_wrong_denial_reason_fails(self):
        from tools.validate_letter import validate_appeal_letter

        bad_text = """
        Dear Appeals Department,
        RE: Claim CLM-2026-00123, Patient Maria Santos

        We are appealing the denial for CO-57 — experimental/investigational treatment.
        The treatment provided is FDA-approved and widely used in clinical practice.
        Per the admission note from 2026-05-01, the patient had pneumonia requiring IV antibiotics.
        InterQual 2024 criteria for pneumonia support this admission.

        Please reverse this denial.
        """

        letter = AppealLetter(
            claim_id="CLM-2026-00123",
            payer_id="HUMANA",
            payer_name="Humana Medicare Advantage",
            letter_text=bad_text,
            submission_format="mail",
            required_attachments=["admission_note"],
            drafted_at="2026-05-17T10:00:00Z",
        )

        result = validate_appeal_letter(letter, DENIAL_RECORD, EVIDENCE_BUNDLE, PAYER_RULES)

        assert result.valid is False

