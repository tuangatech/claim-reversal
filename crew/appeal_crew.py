# crew/appeal_crew.py
"""Crew runner — orchestrates the full appeal pipeline with A2A delegation and HITL."""

import asyncio
import json
import os

import httpx
import structlog
from dotenv import load_dotenv

from agents.writer_agent import AppealWriterAgent
from shared.db import get_connection
from shared.events import WorkflowEvent, WorkflowStep
from shared.mcp_client import McpClient
from shared.models import (
    AppealLetter,
    DenialRecord,
    EvidenceBundle,
    PhysicianReview,
    SubmissionConfirmation,
)
from tools.input_guardrail import scan_denial_record
from tools.physician_review import physician_review
from tools.submit_appeal import submit_appeal
from tools.triage_denial import triage_denial

load_dotenv()

EVIDENCE_AGENT_PORT = os.environ.get("EVIDENCE_AGENT_PORT", "8001")
HITL_TIMEOUT_SECONDS = int(os.environ.get("HITL_TIMEOUT_SECONDS", "300"))
SUBSTEP_DELAY = 1.0

logger = structlog.get_logger()


class AppealCrew:
    """Assembles and runs the sequential appeal pipeline with A2A + HITL."""

    def __init__(self, claim_id: str, event_queue: asyncio.Queue):
        self.claim_id = claim_id
        self.event_queue = event_queue
        self.http_client = httpx.AsyncClient(
            base_url=f"http://localhost:{EVIDENCE_AGENT_PORT}",
            timeout=120.0,
        )
        self.mcp_client = McpClient()
        self.hitl_event = asyncio.Event()
        self.hitl_choice: str | None = None
        self.a2a_task_id: str | None = None

        # Populated during the pipeline
        self.denial_record: DenialRecord | None = None
        self.evidence_bundle: EvidenceBundle | None = None
        self.appeal_letter: AppealLetter | None = None

    async def run(self) -> None:
        """Runs the full pipeline: Guardrail → Intake → Evidence → Writer → Physician → Submission."""
        structlog.contextvars.bind_contextvars(claim_id=self.claim_id)
        logger.info("pipeline_started")
        try:
            await self.mcp_client.connect()

            # Step 0: Input guardrail
            guardrail_passed = await self._run_guardrail()
            if not guardrail_passed:
                logger.warning("pipeline_rejected", reason="input_guardrail_failed")
                return

            self.denial_record = await self._run_intake()
            if self.denial_record is None:
                await self._emit(WorkflowStep.CASE_CLOSED, "warning", "Claim not eligible for appeal.")
                logger.info("pipeline_closed", reason="not_eligible")
                return

            self.evidence_bundle = await self._run_evidence()
            if self.evidence_bundle is None:
                # CASE_CLOSED already emitted by _run_evidence or timeout handler
                logger.info("pipeline_closed", reason="evidence_closed")
                return

            self.appeal_letter = await self._run_writer()
            await self._run_physician()
            await self._run_submission()
            logger.info("pipeline_completed")
        except Exception as exc:
            logger.error("pipeline_failed", error=str(exc))
            await self._emit(WorkflowStep.ERROR, "error", f"Pipeline failed: {exc}")
        finally:
            await self.mcp_client.disconnect()
            await self.http_client.aclose()

    def resume(self, choice: str) -> None:
        """Called by main.py when the human POSTs to /appeal/{claim_id}/resume."""
        self.hitl_choice = choice
        self.hitl_event.set()

    # --- Private pipeline steps ---

    async def _run_guardrail(self) -> bool:
        """Scans the denial record for prompt injection before starting the pipeline."""
        conn = get_connection()
        row = conn.execute("SELECT denial_record FROM appeals WHERE id = ?", (self.claim_id,)).fetchone()
        conn.close()

        denial_record_json = row["denial_record"]

        await self._emit(WorkflowStep.INPUT_VALIDATING, "success", "Scanning denial record for prompt injection...")
        await asyncio.sleep(SUBSTEP_DELAY)

        result = await asyncio.to_thread(scan_denial_record, denial_record_json)
        logger.info("guardrail_completed", passed=result.passed, checks_run=result.checks_run, confidence=result.confidence)

        if result.passed:
            await self._emit(
                WorkflowStep.INPUT_VALIDATED, "success",
                f"Denial record verified — no prompt injection detected",
                payload={"checks_run": result.checks_run, "confidence": result.confidence},
            )
            return True

        await self._emit(
            WorkflowStep.INPUT_REJECTED, "error",
            f"Prompt injection detected in denial record — workflow rejected",
            payload={"flagged_segments": result.flagged_segments, "reasoning": result.reasoning},
        )

        # Update DB status
        conn = get_connection()
        conn.execute(
            "UPDATE appeals SET status='rejected', updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (self.claim_id,),
        )
        conn.commit()
        conn.close()
        return False

    async def _run_intake(self) -> DenialRecord | None:
        """Triages the denial and returns a DenialRecord if the claim should proceed."""
        conn = get_connection()
        row = conn.execute("SELECT denial_record FROM appeals WHERE id = ?", (self.claim_id,)).fetchone()
        conn.close()

        eob_data = json.loads(row["denial_record"])

        # Substep: parsing
        await self._emit(WorkflowStep.INTAKE_PARSING, "success", f"Parsing denial reason code {eob_data['denial_reason_code']}...")
        await asyncio.sleep(SUBSTEP_DELAY)

        # Fetch claim history via MCP
        claim_history = await self.mcp_client.get_claim_history(self.claim_id)

        # Run triage (rules-based, no LLM) — pass MCP data as parameter
        triage_result = await asyncio.to_thread(
            triage_denial,
            claim_id=self.claim_id,
            denial_reason_code=eob_data["denial_reason_code"],
            claim_amount=eob_data["claim_amount"],
            payer_id=eob_data["payer_id"],
            date_of_service=eob_data["date_of_service"],
            denial_date=eob_data["denial_date"],
            claim_history=claim_history,
        )

        # Substep: classifying
        denial_type = "Clinical" if triage_result["is_clinical"] else "Administrative"
        await self._emit(WorkflowStep.INTAKE_CLASSIFYING, "success", f"Classifying denial type → {denial_type}")
        await asyncio.sleep(SUBSTEP_DELAY)

        # Substep: deadline
        await self._emit(WorkflowStep.INTAKE_DEADLINE, "success", f"Checking appeal deadline → {triage_result['days_remaining']} days remaining")
        await asyncio.sleep(SUBSTEP_DELAY)

        # Substep: history
        prior_count = len(claim_history.get("prior_appeals", []))
        history_msg = f"Found {prior_count} prior appeal(s)" if prior_count > 0 else "No prior appeals"
        await self._emit(WorkflowStep.INTAKE_HISTORY, "success", f"Checking prior appeal history → {history_msg}")
        await asyncio.sleep(SUBSTEP_DELAY)

        # Substep: scoring
        score = triage_result["worthiness_score"]
        await self._emit(WorkflowStep.INTAKE_SCORING, "success", f"Scoring worthiness → {score} ({triage_result['reasoning']})")
        await asyncio.sleep(SUBSTEP_DELAY)

        await self.mcp_client.log_appeal_event(
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
        logger.info("step_completed", step="intake", recommendation=recommendation, worthiness_score=score)
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
            logger.error("a2a_call_failed", error=str(exc))
            await self._emit(WorkflowStep.ERROR, "error", f"Evidence agent unavailable: {exc}")
            return None

        result = response.json()
        status_state = result["status"]["state"]
        logger.info("a2a_response_received", status=status_state)

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
        """Delegates letter writing to the CrewAI Writer Agent (draft→validate→retry loop)."""
        await self._emit(WorkflowStep.DRAFTING_PAYER_RULES, "success", f"Loading payer appeal rules for {self.denial_record.payer_name}...")
        await asyncio.sleep(SUBSTEP_DELAY)

        payer_rules = await self.mcp_client.get_payer_appeal_rules(self.denial_record.payer_id)

        sections = payer_rules.get("required_sections", [])
        sections_text = ", ".join(sections[:3]) if sections else "standard format"
        await self._emit(WorkflowStep.DRAFTING_RULES_LOADED, "success", f"Required sections: {sections_text}")
        await asyncio.sleep(SUBSTEP_DELAY)

        # Delegate to CrewAI Writer Agent
        writer = AppealWriterAgent(
            denial_record=self.denial_record,
            evidence_bundle=self.evidence_bundle,
            payer_rules=payer_rules,
            event_queue=self.event_queue,
            claim_id=self.claim_id,
        )
        letter, validation = await asyncio.to_thread(writer.run_sync)

        issue_count = len(validation.issues) if validation else 0
        score = validation.score if validation else 0.0
        logger.info("step_completed", step="writer", validation_score=score, issues=issue_count)

        await self.mcp_client.log_appeal_event(
            claim_id=self.claim_id,
            event_type="letter_drafted",
            payload={
                "payer_id": self.denial_record.payer_id,
                "partial_evidence": self.evidence_bundle.partial,
                "validation_score": score,
                "validation_issues": validation.issues if validation else [],
            },
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

        await self.mcp_client.log_appeal_event(
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

        payer_rules = await self.mcp_client.get_payer_appeal_rules(self.denial_record.payer_id)
        method = payer_rules.get("submission_format", "mail")
        await self._emit(WorkflowStep.SUBMISSION_SENDING, "success", f"Submitting to {self.denial_record.payer_name} via {method}...")
        await asyncio.sleep(SUBSTEP_DELAY * 2)

        confirmation = await asyncio.to_thread(
            submit_appeal,
            claim_id=self.claim_id,
            payer_id=self.denial_record.payer_id,
            letter_text=self.appeal_letter.letter_text,
            payer_rules=payer_rules,
        )

        await self.mcp_client.log_appeal_event(
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

