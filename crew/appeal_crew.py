# crew/appeal_crew.py
"""Crew runner — orchestrates the full appeal pipeline."""

from crewai import Crew, Task

from agents.intake_agent import DenialIntakeAgent
from agents.physician_agent import PhysicianAgent
from agents.submission_agent import SubmissionAgent
from agents.writer_agent import AppealWriterAgent


class AppealCrew:
    """Assembles and runs the CrewAI crew for clinical denial appeals."""

    def __init__(self):
        self.intake_agent = DenialIntakeAgent().build()
        self.writer_agent = AppealWriterAgent().build()
        self.physician_agent = PhysicianAgent().build()
        self.submission_agent = SubmissionAgent().build()

    def kickoff(self, claim_id: str) -> str:
        """Runs the sequential crew pipeline. A2A evidence step is stubbed in Phase 1."""
        intake_task = Task(
            description=f"Triage denial for claim {claim_id}",
            expected_output="DenialRecord with classification and recommendation",
            agent=self.intake_agent,
        )
        writer_task = Task(
            description=f"Draft appeal letter for claim {claim_id}",
            expected_output="Formatted appeal letter",
            agent=self.writer_agent,
        )
        physician_task = Task(
            description=f"Review and sign off on appeal for claim {claim_id}",
            expected_output="Physician review decision",
            agent=self.physician_agent,
        )
        submission_task = Task(
            description=f"Submit appeal for claim {claim_id}",
            expected_output="Submission confirmation with confirmation number",
            agent=self.submission_agent,
        )

        crew = Crew(
            agents=[self.intake_agent, self.writer_agent, self.physician_agent, self.submission_agent],
            tasks=[intake_task, writer_task, physician_task, submission_task],
            verbose=True,
        )

        result = crew.kickoff()
        return str(result)

