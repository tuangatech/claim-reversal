# a2a_server/graph.py
"""LangGraph StateGraph for the Clinical Evidence Agent."""

import json
import sys
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from a2a_server.state import AppealState, EvidenceSufficiency, HumanChoice
from a2a_server.tools.evaluate_sufficiency import evaluate_evidence_sufficiency
from a2a_server.tools.fetch_lcd_policy import fetch_lcd_policy
from a2a_server.tools.fetch_records import fetch_patient_records
from mcp_server.tools.lookup_guideline import lookup_clinical_guideline
from shared.db import get_connection
from shared.models import ClinicalRecord, EvidenceBundle, GuidelineCitation


# --- Helpers ---

def _get_date_of_service(claim_id: str) -> str:
    """Reads date_of_service from the appeals table denial_record JSON."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT denial_record FROM appeals WHERE id = ?", (claim_id,)
        ).fetchone()
        if row and row["denial_record"]:
            return json.loads(row["denial_record"]).get("date_of_service", "")
        return ""
    finally:
        conn.close()


# --- Node functions ---

def fetch_records(state: AppealState) -> dict:
    """Fetches patient records from mock data fixtures."""
    date_of_service = _get_date_of_service(state["claim_id"])
    records = fetch_patient_records(
        state["claim_id"],
        date_of_service,
        include_supplemental=state.get("include_supplemental", False),
    )
    return {"patient_records": [r.model_dump() for r in records]}


def lookup_guideline(state: AppealState) -> dict:
    """Looks up clinical guidelines for each diagnosis code."""
    citations = []
    for code in state["diagnosis_codes"]:
        result = lookup_clinical_guideline(code)
        citations.append(result)
    return {"guideline_citations": citations}


def fetch_lcd(state: AppealState) -> dict:
    """Fetches LCD policy text (no-op in mock mode)."""
    result = fetch_lcd_policy(state["diagnosis_codes"][0])
    return {"lcd_policy_text": result.get("policy_text", "")}


def evaluate_sufficiency_node(state: AppealState) -> dict:
    """LLM-scored evaluation of whether evidence meets payer criteria."""
    # Reconstruct Pydantic objects from state dicts
    records = [ClinicalRecord(**r) for r in (state.get("patient_records") or [])]
    citations = [GuidelineCitation(**c) for c in (state.get("guideline_citations") or [])]

    result = evaluate_evidence_sufficiency(records, citations, state["diagnosis_codes"])

    return {
        "sufficiency": result["sufficiency"],
        "sufficiency_reasoning": result["reasoning"],
    }


def increment_retry(state: AppealState) -> dict:
    """Increments retry count and enables supplemental record fetching."""
    return {
        "retry_count": state["retry_count"] + 1,
        "include_supplemental": True,
    }


def human_review_interrupt(state: AppealState) -> dict:
    """Suspends the graph for human review via interrupt()."""
    payload = {
        "claim_id": state["claim_id"],
        "sufficiency_reasoning": state.get("sufficiency_reasoning", ""),
        "evidence_gathered": {
            "record_count": len(state.get("patient_records") or []),
            "guideline_count": len(state.get("guideline_citations") or []),
        },
        "options": ["proceed", "close"],
    }
    # interrupt() suspends here; returns the value from Command(resume=...)
    choice = interrupt(payload)
    return {
        "hitl_triggered": True,
        "human_choice": choice["choice"],
    }


def build_bundle(state: AppealState) -> dict:
    """Assembles a complete EvidenceBundle from gathered state."""
    bundle = EvidenceBundle(
        claim_id=state["claim_id"],
        patient_records=[ClinicalRecord(**r) for r in (state.get("patient_records") or [])],
        guideline_citations=[GuidelineCitation(**c) for c in (state.get("guideline_citations") or [])],
        lcd_policy_text=state.get("lcd_policy_text"),
        sufficiency_reasoning=state.get("sufficiency_reasoning", ""),
        partial=False,
    )
    return {"evidence_bundle": bundle.model_dump()}


def build_bundle_partial(state: AppealState) -> dict:
    """Assembles a partial EvidenceBundle (human chose to proceed with incomplete evidence)."""
    bundle = EvidenceBundle(
        claim_id=state["claim_id"],
        patient_records=[ClinicalRecord(**r) for r in (state.get("patient_records") or [])],
        guideline_citations=[GuidelineCitation(**c) for c in (state.get("guideline_citations") or [])],
        lcd_policy_text=state.get("lcd_policy_text"),
        sufficiency_reasoning=state.get("sufficiency_reasoning", ""),
        partial=True,
    )
    return {"evidence_bundle": bundle.model_dump()}


def close_case(state: AppealState) -> dict:
    """Closes the case — no appeal will be filed."""
    return {"closed_reason": "insufficient_evidence_human_closed"}


# --- Conditional edge functions ---

def route_after_evaluation(state: AppealState) -> str:
    """Routes based on sufficiency score and retry count."""
    if state["sufficiency"] == EvidenceSufficiency.SUFFICIENT:
        return "build_bundle"
    elif state["retry_count"] >= 2:
        return "human_review_interrupt"
    else:
        return "increment_retry"


def route_after_hitl(state: AppealState) -> str:
    """Routes based on human's HITL decision."""
    if state["human_choice"] == HumanChoice.PROCEED:
        return "build_bundle_partial"
    return "close_case"


# --- Graph assembly ---

builder = StateGraph(AppealState)

builder.add_node("fetch_records", fetch_records)
builder.add_node("lookup_guideline", lookup_guideline)
builder.add_node("fetch_lcd", fetch_lcd)
builder.add_node("evaluate_sufficiency", evaluate_sufficiency_node)
builder.add_node("increment_retry", increment_retry)
builder.add_node("human_review_interrupt", human_review_interrupt)
builder.add_node("build_bundle", build_bundle)
builder.add_node("build_bundle_partial", build_bundle_partial)
builder.add_node("close_case", close_case)

# Linear edges
builder.add_edge(START, "fetch_records")
builder.add_edge("fetch_records", "lookup_guideline")
builder.add_edge("lookup_guideline", "fetch_lcd")
builder.add_edge("fetch_lcd", "evaluate_sufficiency")

# Conditional: after evaluation
builder.add_conditional_edges("evaluate_sufficiency", route_after_evaluation)

# Retry loops back
builder.add_edge("increment_retry", "fetch_records")

# Conditional: after HITL
builder.add_conditional_edges("human_review_interrupt", route_after_hitl)

# Terminal edges
builder.add_edge("build_bundle", END)
builder.add_edge("build_bundle_partial", END)
builder.add_edge("close_case", END)

# Compile with in-memory checkpointer for interrupt/resume support
checkpointer = MemorySaver()
graph = builder.compile(checkpointer=checkpointer)

