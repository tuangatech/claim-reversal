# agents/writer_agent.py
"""Appeal Writer CrewAI agent — owns the draft→validate→retry loop autonomously."""

import asyncio
import json

from crewai import Agent, Crew, Task
from crewai.tools import tool

from shared.events import WorkflowEvent, WorkflowStep
from shared.llm import get_crewai_llm_string
from shared.models import (
    AppealLetter,
    DenialRecord,
    EvidenceBundle,
    LetterValidationResult,
)
from tools.draft_letter import draft_appeal_letter
from tools.validate_letter import validate_appeal_letter


class AppealWriterAgent:
    """Factory that builds a CrewAI Writer Agent with pre-bound tool closures."""

    def __init__(
        self,
        denial_record: DenialRecord,
        evidence_bundle: EvidenceBundle,
        payer_rules: dict,
        event_queue: asyncio.Queue,
        claim_id: str,
    ):
        self.denial_record = denial_record
        self.evidence_bundle = evidence_bundle
        self.payer_rules = payer_rules
        self.event_queue = event_queue
        self.claim_id = claim_id
        self.final_letter: AppealLetter | None = None
        self.final_validation: LetterValidationResult | None = None

    def _emit_sync(self, step: WorkflowStep, status: str, message: str) -> None:
        """Enqueues an SSE event from a sync context (inside CrewAI tool execution)."""
        event = WorkflowEvent(
            claim_id=self.claim_id,
            step=step,
            status=status,
            message=message,
            payload={},
        )
        self.event_queue.put_nowait(event)

    def _build_tools(self) -> list:
        """Creates pre-bound CrewAI tools that close over pipeline state."""
        denial_record = self.denial_record
        evidence_bundle = self.evidence_bundle
        payer_rules = self.payer_rules
        owner = self

        @tool("draft_appeal_letter")
        def draft_tool(validation_feedback: str = "") -> str:
            """Drafts a formal medical appeal letter using clinical evidence, guidelines, and payer rules. Pass validation_feedback from a prior failed validation to fix issues."""
            owner._emit_sync(WorkflowStep.DRAFTING_COMPOSING, "success", "Drafting appeal letter...")

            feedback_list = [f.strip() for f in validation_feedback.split(";") if f.strip()] if validation_feedback else None

            letter = draft_appeal_letter(
                denial_record=denial_record,
                evidence_bundle=evidence_bundle,
                payer_rules=payer_rules,
                validation_feedback=feedback_list,
            )
            owner.final_letter = letter
            return json.dumps({"status": "drafted", "claim_id": letter.claim_id, "letter_preview": letter.letter_text[:200]})

        @tool("validate_appeal_letter")
        def validate_tool(dummy: str = "") -> str:
            """Validates the most recently drafted letter against evidence and payer rules. Returns pass/fail with score and issues."""
            if owner.final_letter is None:
                return json.dumps({"error": "No letter drafted yet. Call draft_appeal_letter first."})

            owner._emit_sync(WorkflowStep.LETTER_VALIDATING, "success", "Validating letter against evidence...")

            validation = validate_appeal_letter(
                letter=owner.final_letter,
                denial_record=denial_record,
                evidence_bundle=evidence_bundle,
                payer_rules=payer_rules,
            )
            owner.final_validation = validation

            if validation.valid:
                owner._emit_sync(
                    WorkflowStep.LETTER_VALIDATED, "success",
                    f"Letter validated (score: {validation.score:.0%}). {len(validation.issues)} issue(s).",
                )
            else:
                issues_text = "; ".join(validation.issues[:3]) if validation.issues else "quality below threshold"
                owner._emit_sync(
                    WorkflowStep.LETTER_VALIDATING, "warning",
                    f"Validation failed (score: {validation.score:.0%}). Issues: {issues_text}",
                )

            return json.dumps({
                "valid": validation.valid,
                "score": validation.score,
                "issues": validation.issues,
                "reasoning": validation.reasoning,
            })

        return [draft_tool, validate_tool]

    def build_agent(self) -> Agent:
        """Returns the CrewAI Agent configured with pre-bound tools."""
        return Agent(
            role="Appeal Letter Writer",
            goal="Draft a compelling, payer-compliant appeal letter and validate it against the clinical evidence. Retry once if validation fails.",
            backstory=(
                "You are a skilled medical appeal writer who assembles formal rebuttal letters "
                "that clearly argue medical necessity using clinical documentation and payer-specific "
                "formatting requirements. You draft, validate, and fix until the letter passes quality checks."
            ),
            tools=self._build_tools(),
            llm=get_crewai_llm_string(),
            max_iter=6,
            verbose=False,
        )

    def build_task(self, agent: Agent) -> Task:
        """Returns the CrewAI Task that drives the draft→validate→retry loop."""
        sections = self.payer_rules.get("required_sections", [])
        sections_text = ", ".join(sections) if sections else "standard format"

        return Task(
            description=(
                f"Draft and validate an appeal letter for claim {self.claim_id}.\n"
                f"Payer: {self.denial_record.payer_name} ({self.denial_record.payer_id})\n"
                f"Denial reason: {self.denial_record.denial_reason_code} — {self.denial_record.denial_reason_text}\n"
                f"Required sections: {sections_text}\n"
                f"Evidence: {len(self.evidence_bundle.patient_records)} records, "
                f"{len(self.evidence_bundle.guideline_citations)} guidelines, "
                f"partial={self.evidence_bundle.partial}\n\n"
                "Steps:\n"
                "1. Call draft_appeal_letter to compose the letter\n"
                "2. Call validate_appeal_letter to check quality\n"
                "3. If validation fails, call draft_appeal_letter again with the issues as validation_feedback (semicolon-separated)\n"
                "4. Call validate_appeal_letter once more\n"
                "5. Return DONE regardless of second validation result\n\n"
                "Retry at most once. Do not loop more than that."
            ),
            expected_output="The word DONE after drafting and validating the letter.",
            agent=agent,
        )

    def run_sync(self) -> tuple[AppealLetter, LetterValidationResult]:
        """Builds and runs the CrewAI Crew synchronously. Returns (letter, validation)."""
        agent = self.build_agent()
        task = self.build_task(agent)
        crew = Crew(agents=[agent], tasks=[task], verbose=False)
        crew.kickoff()
        return self.final_letter, self.final_validation
