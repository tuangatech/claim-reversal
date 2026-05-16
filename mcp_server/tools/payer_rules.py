# mcp_server/tools/payer_rules.py
"""Returns payer-specific appeal rules."""

PAYER_RULES = {
    "BCBS": {
        "payer_id": "BCBS",
        "payer_name": "Blue Cross Blue Shield",
        "appeal_window_days": 90,
        "submission_format": "portal",
        "required_sections": [
            "Patient Demographics",
            "Denial Reference",
            "Clinical Summary",
            "Medical Necessity Argument",
            "Supporting Documentation List",
            "Physician Attestation",
        ],
        "contact_address": "BCBS Appeals Department, PO Box 2500, Chicago, IL 60601",
    },
    "AETNA": {
        "payer_id": "AETNA",
        "payer_name": "Aetna",
        "appeal_window_days": 60,
        "submission_format": "fax or mail",
        "required_sections": [
            "Member Information",
            "Claim Reference",
            "Clinical Rationale",
            "Evidence Summary",
            "Conclusion",
        ],
        "contact_address": "Aetna Clinical Appeals, PO Box 14079, Lexington, KY 40512",
    },
    "UHC": {
        "payer_id": "UHC",
        "payer_name": "UnitedHealthcare",
        "appeal_window_days": 180,
        "submission_format": "portal",
        "required_sections": [
            "Member ID and Claim Number",
            "Date of Service",
            "Denial Reason Response",
            "Clinical Evidence",
            "Guideline Citations",
            "Medical Necessity Statement",
            "Provider Signature",
        ],
        "contact_address": "UHC Appeals, PO Box 30555, Salt Lake City, UT 84130",
    },
    "CIGNA": {
        "payer_id": "CIGNA",
        "payer_name": "Cigna Healthcare",
        "appeal_window_days": 90,
        "submission_format": "fax or portal",
        "required_sections": [
            "Patient Info",
            "Claim Details",
            "Clinical Argument",
            "Attached Documentation",
            "Guideline References",
            "Provider Contact",
        ],
        "contact_address": "Cigna Appeals, PO Box 188011, Chattanooga, TN 37422",
    },
    "HUMANA": {
        "payer_id": "HUMANA",
        "payer_name": "Humana",
        "appeal_window_days": 60,
        "submission_format": "mail",
        "required_sections": [
            "Beneficiary Information",
            "Service Details",
            "Medical Necessity Justification",
            "Clinical Documentation Summary",
            "Requesting Provider Signature",
        ],
        "contact_address": "Humana Appeals, PO Box 14618, Lexington, KY 40512",
    },
}

DEFAULT_RULES = {
    "payer_id": "UNKNOWN",
    "payer_name": "Unknown Payer",
    "appeal_window_days": 90,
    "submission_format": "fax",
    "required_sections": [
        "Patient Information",
        "Claim Reference",
        "Clinical Justification",
        "Supporting Documentation",
    ],
    "contact_address": "Appeals Department",
}


def get_payer_appeal_rules(payer_id: str) -> dict:
    """Returns payer-specific submission format, required sections, and deadline rules."""

    return PAYER_RULES.get(payer_id.upper(), {**DEFAULT_RULES, "payer_id": payer_id})

