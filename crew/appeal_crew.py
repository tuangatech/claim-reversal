# crew/appeal_crew.py
"""Crew runner — orchestrates the full appeal pipeline with A2A delegation and HITL."""

import asyncio
import json
import os

import httpx
from dotenv import load_dotenv

from mcp_server.tools.audit_log import log_appeal_event
from mcp_server.tools.payer_rules import get_payer_appeal_rules
from shared.db import get_connection
from shared.events import WorkflowEvent, WorkflowStep
from shared.models import (
    AppealLetter,
    DenialRecord,
    EvidenceBundle,
    PhysicianReview,
    SubmissionConfirmation,
)
from tools.draft_letter import draft_appeal_letter
from tools.physician_review import physician_review
from tools.submit_appeal import submit_appeal
from tools.triage_denial import triage_denial

load_dotenv()

EVIDENCE_AGENT_PORT = os.environ.get("EVIDENCE_AGENT_PORT", "8001")
HITL_TIMEOUT_SECONDS = int(os.environ.get("HITL_TIMEOUT_SECONDS", "300"))
SUBSTEP_DELAY = 0.4


class AppealCrew:
    """Assembles and runs the sequential appeal pipeline with A2A + HITL."""

    def __init__(self, claim_id: str, event_queue: asyncio.Queue):
        self.claim_id = claim_id
        self.event_queue = event_queue
        self.http_client = httpx.AsyncClient(
            base_url=f"http://localhost:{EVIDENCE_AGENT_PORT}",
            timeout=120.0,
        )
        self.hitl_event = asyncio.Event()
        self.hitl_choice: str | None = None
        self.a2a_task_id: str | None = None

        # Populated during the pipeline
        self.denial_record: DenialRecord | None = None
        self.evidence_bundle: EvidenceBundle | None = None
        self.appeal_letter: AppealLetter | None = None

    async def run(self) -> None:
        """Runs the full pipeline: Intake → Evidence → Writer → Physician → Submission."""
        try:
            self.denial_record = await self._run_intake()
            if self.denial_record is None:
                await self._emit(WorkflowStep.CASE_CLOSED, "warning", "Claim not eligible for appeal.")
                return

            self.evidence_bundle = await self._run_evidence()
            if self.evidence_bundle is None:
                # CASE_CLOSED already emitted by _run_evidence or timeout handler
                return

            self.appeal_letter = await self._run_writer()
            await self._run_physician()
            await self._run_submission()
        except Exception as exc:
            await self._emit(WorkflowStep.ERROR, "error", f"Pipeline failed: {exc}")
        finally:
            await self.http_client.aclose()

    def resume(self, choice: str) -> None:
        """Called by main.py when the human POSTs to /appeal/{claim_id}/resume."""
        self.hitl_choice = choice
        self.hitl_event.set()

    # --- Private pipeline steps ---

    async def _run_intake(self) -> DenialRecord | None:
        """Triages the denial and returns a DenialRecord if the claim should proceed."""
        conn = get_connection()
        row = conn.execute("SELECT denial_record FROM appeals WHERE id = ?", (self.claim_id,)).fetchone()
        conn.close()

        eob_data = json.loads(row["denial_record"])

        # Substep: parsing
        await self._emit(WorkflowStep.INTAKE_PARSING, "success", f"Parsing denial reason code {eob_data['denial_reason_code']}...")
        await asyncio.sleep(SUBSTEP_DELAY)

        # Run triage (rules-based, no LLM)
        triage_result = await asyncio.to_thread(
            triage_denial,
            claim_id=self.claim_id,
            denial_reason_code=eob_data["denial_reason_code"],
            claim_amount=eob_data["claim_amount"],
            payer_id=eob_data["payer_id"],
            date_of_service=eob_data["date_of_service"],
            denial_date=eob_data["denial_date"],
        )

        # Substep: classifying
        denial_type = "Clinical" if triage_result["is_clinical"] else "Administrative"
        await self._emit(WorkflowStep.INTAKE_CLASSIFYING, "success", f"Classifying denial type → {denial_type}")
        await asyncio.sleep(SUBSTEP_DELAY)

        # Substep: deadline
        await self._emit(WorkflowStep.INTAKE_DEADLINE, "success", f"Checking appeal deadline → {triage_result['days_remaining']} days remaining")
        await asyncio.sleep(SUBSTEP_DELAY)

        # Substep: history
        await self._emit(WorkflowStep.INTAKE_HISTORY, "success", "Checking prior appeal history → No prior appeals")
        await asyncio.sleep(SUBSTEP_DELAY)

        # Substep: scoring
        score = triage_result["worthiness_score"]
        await self._emit(WorkflowStep.INTAKE_SCORING, "success", f"Scoring worthiness → {score} ({triage_result['reasoning']})")
        await asyncio.sleep(SUBSTEP_DELAY)

        log_appeal_event(
            claim_id=self.claim_id,
            event_type="intake_complete",
            payload=triage_result,
            agent_name="denial_intake_agent",
        )

        # Build DenialRecord from EOB + triage results
        denial_record = DenialRecord(
            claim_id=self.claim_id,
            patient_name=eob_data["patient_name"],
            patient_id=eob_data["patient_id"],
            payer_id=eob_data["payer_id"],
            payer_name=eob_data["payer_name"],
            denial_reason_code=eob_data["denial_reason_code"],
            denial_reason_text=eob_data["denial_reason_text"],
            is_clinical=triage_result["is_clinical"],
            diagnosis_codes=eob_data["diagnosis_codes"],
            date_of_service=eob_data["date_of_service"],
            denial_date=eob_data["denial_date"],
            claim_amount=eob_data["claim_amount"],
            appeal_deadline=triage_result["appeal_deadline"],
            days_remaining=triage_result["days_remaining"],
            worthiness_score=triage_result["worthiness_score"],
            recommendation=triage_result["recommendation"],
        )

        # Persist to DB
        conn = get_connection()
        conn.execute(
            "UPDATE appeals SET status='intake', denial_record=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (denial_record.model_dump_json(), self.claim_id),
        )
        conn.commit()
        conn.close()

        recommendation = triage_result["recommendation"]
        await self._emit(
            WorkflowStep.INTAKE_COMPLETE,
            "success",
            f"Recommendation: {'Proceed with appeal' if recommendation == 'proceed' else 'Close case'}",
        )

        if recommendation != "proceed":
            return None
        return denial_record

    async def _run_evidence(self) -> EvidenceBundle | None:
        """Delegates to the A2A evidence agent and handles HITL if needed."""
        await self._emit(WorkflowStep.EVIDENCE_GATHERING, "success", "Delegating to Clinical Evidence Agent...")
        await asyncio.sleep(SUBSTEP_DELAY)

        dos = self.denial_record.date_of_service
        await self._emit(WorkflowStep.EVIDENCE_FETCHING_RECORDS, "success", f"Fetching patient records for DOS {dos}...")
        await asyncio.sleep(SUBSTEP_DELAY)

        # Build A2A request
        payload = {
            "messages": [{"role": "user", "parts": [{"type": "data", "data": {
                "claim_id": self.denial_record.claim_id,
                "diagnosis_codes": self.denial_record.diagnosis_codes,
                "payer_id": self.denial_record.payer_id,
                "denial_reason_code": self.denial_record.denial_reason_code,
            }}]}]
        }

        # Send to A2A evidence agent
        try:
            response = await self.http_client.post("/a2a", json=payload)
            response.raise_for_status()
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as exc:
            await self._emit(WorkflowStep.ERROR, "error", f"Evidence agent unavailable: {exc}")
            return None

        result = response.json()
        status_state = result["status"]["state"]

        if status_state == "completed":
            return await self._handle_evidence_completed(result)

        if status_state == "input-required":
            return await self._handle_evidence_hitl(result)

        # Unexpected status
        await self._emit(WorkflowStep.ERROR, "error", f"Unexpected A2A status: {status_state}")
        return None

    async def _handle_evidence_completed(self, result: dict) -> EvidenceBundle | None:
        """Processes a completed A2A response (evidence found or case closed by graph)."""
        data = result["messages"][0]["parts"][0]["data"]

        if "closed_reason" in data:
            await self._emit(WorkflowStep.CASE_CLOSED, "warning", f"Evidence agent closed case: {data['closed_reason']}")
            return None

        bundle = self._parse_evidence_bundle(data["evidence_bundle"])

        record_count = len(bundle.patient_records)
        guideline_count = len(bundle.guideline_citations)

        # Emit evidence substeps based on what the graph found
        record_types = ", ".join(r.record_type for r in bundle.patient_records[:4])
        await self._emit(WorkflowStep.EVIDENCE_RECORDS_FOUND, "success", f"Found {record_count} clinical records ({record_types})")
        await asyncio.sleep(SUBSTEP_DELAY)

        diag_codes = ", ".join(self.denial_record.diagnosis_codes)
        await self._emit(WorkflowStep.EVIDENCE_GUIDELINE_LOOKUP, "success", f"Looking up clinical criteria for {diag_codes}...")
        await asyncio.sleep(SUBSTEP_DELAY)

        if guideline_count > 0:
            source = bundle.guideline_citations[0].guideline_source
            await self._emit(WorkflowStep.EVIDENCE_GUIDELINE_FOUND, "success", f"Retrieved {guideline_count} guideline citation(s) from {source}")
            await asyncio.sleep(SUBSTEP_DELAY)

        await self._emit(WorkflowStep.EVIDENCE_EVALUATING, "success", "Evaluating evidence sufficiency...")
        await asyncio.sleep(SUBSTEP_DELAY)

        await self._emit(WorkflowStep.EVIDENCE_SUFFICIENT, "success", f"Evidence {'sufficient' if not bundle.partial else 'partial'} — assembling bundle")
        await asyncio.sleep(SUBSTEP_DELAY)

        # Persist to DB
        conn = get_connection()
        conn.execute(
            "UPDATE appeals SET status='evidence', evidence_bundle=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (bundle.model_dump_json(), self.claim_id),
        )
        conn.commit()
        conn.close()

        step = WorkflowStep.EVIDENCE_GATHERED if not bundle.partial else WorkflowStep.EVIDENCE_GATHERED_PARTIAL
        await self._emit(step, "success", f"Evidence bundle assembled. {record_count} records, {guideline_count} guidelines.")

        return bundle

    async def _handle_evidence_hitl(self, result: dict) -> EvidenceBundle | None:
        """Handles the HITL pause: wait for human input or timeout, then resume A2A."""
        self.a2a_task_id = result["id"]
        data = result["messages"][0]["parts"][0]["data"]

        # Emit HITL event to the browser
        await self._emit(
            WorkflowStep.HUMAN_REVIEW_REQUIRED,
            "waiting",
            "Evidence insufficient after retries. Human decision required.",
            payload={
                "sufficiency_reasoning": data.get("sufficiency_reasoning", ""),
                "evidence_gathered": data.get("evidence_gathered", {}),
                "options": data.get("options", ["proceed", "close"]),
            },
        )

        # Wait for human or timeout
        try:
            await asyncio.wait_for(self.hitl_event.wait(), timeout=HITL_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            self.hitl_choice = "close"
            await self._emit(WorkflowStep.CASE_CLOSED, "warning", f"HITL timeout ({HITL_TIMEOUT_SECONDS}s) — case auto-closed.")
            # Still send resume to A2A to close the graph properly
            await self._send_a2a_resume("close")
            return None

        await self._emit(WorkflowStep.HITL_RESPONSE_RECEIVED, "success", f"Human chose: {self.hitl_choice}")

        # Send resume to A2A
        resume_result = await self._send_a2a_resume(self.hitl_choice)
        if resume_result is None:
            return None

        return await self._handle_evidence_completed(resume_result)

    async def _send_a2a_resume(self, choice: str) -> dict | None:
        """Sends the HITL resume to the A2A server with the stored task_id."""
        resume_payload = {
            "id": self.a2a_task_id,
            "messages": [{"role": "user", "parts": [{"type": "data", "data": {
                "human_choice": choice,
            }}]}],
        }

        try:
            response = await self.http_client.post("/a2a", json=resume_payload)
            response.raise_for_status()
            return response.json()
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as exc:
            await self._emit(WorkflowStep.ERROR, "error", f"Evidence agent unavailable on resume: {exc}")
            return None

    async def _run_writer(self) -> AppealLetter:
        """Drafts the appeal letter using LLM composition."""
        await self._emit(WorkflowStep.DRAFTING_PAYER_RULES, "success", f"Loading payer appeal rules for {self.denial_record.payer_name}...")
        await asyncio.sleep(SUBSTEP_DELAY)

        payer_rules = await asyncio.to_thread(get_payer_appeal_rules, self.denial_record.payer_id)

        sections = payer_rules.get("required_sections", [])
        sections_text = ", ".join(sections[:3]) if sections else "standard format"
        await self._emit(WorkflowStep.DRAFTING_RULES_LOADED, "success", f"Required sections: {sections_text}")
        await asyncio.sleep(SUBSTEP_DELAY)

        await self._emit(WorkflowStep.DRAFTING_COMPOSING, "success", "Drafting appeal letter...")

        letter = await asyncio.to_thread(draft_appeal_letter, self.denial_record, self.evidence_bundle, payer_rules)

        log_appeal_event(
            claim_id=self.claim_id,
            event_type="letter_drafted",
            payload={"payer_id": self.denial_record.payer_id, "partial_evidence": self.evidence_bundle.partial},
            agent_name="appeal_writer_agent",
        )

        # Persist to DB
        conn = get_connection()
        conn.execute(
            "UPDATE appeals SET status='drafting', appeal_letter=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (letter.model_dump_json(), self.claim_id),
        )
        conn.commit()
        conn.close()

        guideline_count = len(self.evidence_bundle.guideline_citations)
        record_count = len(self.evidence_bundle.patient_records)
        await self._emit(WorkflowStep.LETTER_DRAFTED, "success", f"Letter drafted — {guideline_count} guideline citations, {record_count} evidence references")
        return letter

    async def _run_physician(self) -> PhysicianReview:
        """Checks physician attestation requirement and simulates approval."""
        await self._emit(WorkflowStep.PHYSICIAN_CHECKING, "success", "Checking if physician attestation required...")
        await asyncio.sleep(SUBSTEP_DELAY)

        review = await asyncio.to_thread(
            physician_review,
            claim_id=self.claim_id,
            denial_type="clinical" if self.denial_record.is_clinical else "administrative",
            claim_amount=self.denial_record.claim_amount,
            payer_id=self.denial_record.payer_id,
            letter_text=self.appeal_letter.letter_text,
        )

        if review.physician_required:
            await self._emit(WorkflowStep.PHYSICIAN_CHECKING, "success", "Physician attestation required → Yes")
            await asyncio.sleep(SUBSTEP_DELAY)
            await self._emit(WorkflowStep.PHYSICIAN_ROUTING, "success", "Routing to Dr. Sarah Mitchell, MD — Medical Director")
            await asyncio.sleep(SUBSTEP_DELAY * 2)
        else:
            await self._emit(WorkflowStep.PHYSICIAN_CHECKING, "success", "Physician attestation required → No (bypassed)")
            await asyncio.sleep(SUBSTEP_DELAY)

        log_appeal_event(
            claim_id=self.claim_id,
            event_type="physician_reviewed",
            payload={"physician_required": review.physician_required, "status": review.review_status},
            agent_name="physician_agent",
        )

        # Update DB status
        conn = get_connection()
        conn.execute(
            "UPDATE appeals SET status='physician', updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (self.claim_id,),
        )
        conn.commit()
        conn.close()

        status_text = "Reviewed and approved" if review.physician_required else "Not required — bypassed"
        await self._emit(WorkflowStep.PHYSICIAN_REVIEWED, "success", status_text)
        return review

    async def _run_submission(self) -> SubmissionConfirmation:
        """Submits the appeal and records confirmation."""
        await self._emit(WorkflowStep.SUBMISSION_PREPARING, "success", "Preparing submission package...")
        await asyncio.sleep(SUBSTEP_DELAY)

        payer_rules = await asyncio.to_thread(get_payer_appeal_rules, self.denial_record.payer_id)
        method = payer_rules.get("submission_format", "mail")
        await self._emit(WorkflowStep.SUBMISSION_SENDING, "success", f"Submitting to {self.denial_record.payer_name} via {method}...")
        await asyncio.sleep(SUBSTEP_DELAY * 2)

        confirmation = await asyncio.to_thread(
            submit_appeal,
            claim_id=self.claim_id,
            payer_id=self.denial_record.payer_id,
            letter_text=self.appeal_letter.letter_text,
        )

        log_appeal_event(
            claim_id=self.claim_id,
            event_type="appeal_submitted",
            payload={"confirmation_number": confirmation.confirmation_number, "method": confirmation.submission_method},
            agent_name="submission_agent",
        )

        await self._emit(
            WorkflowStep.APPEAL_SUBMITTED,
            "success",
            f"Confirmation: {confirmation.confirmation_number}",
        )
        return confirmation

    # --- Helpers ---

    def _parse_evidence_bundle(self, bundle_data: dict) -> EvidenceBundle:
        """Parses A2A response data into an EvidenceBundle model."""
        return EvidenceBundle.model_validate(bundle_data)

    async def _emit(self, step: WorkflowStep, status: str, message: str, payload: dict | None = None) -> None:
        """Builds a WorkflowEvent and puts it on the SSE queue."""
        event = WorkflowEvent(
            claim_id=self.claim_id,
            step=step,
            status=status,
            message=message,
            payload=payload or {},
        )
        await self.event_queue.put(event)


