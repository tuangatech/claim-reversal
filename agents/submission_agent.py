# agents/submission_agent.py
"""Submission CrewAI agent definition."""

from crewai import Agent

from shared.llm import get_crewai_llm_string


class SubmissionAgent:
    """Builds the Submission agent."""

    def __init__(self, config: dict | None = None):
        self.config = config or {}

    def build(self) -> Agent:
        """Returns a CrewAI Agent for submitting appeals to payers."""
        return Agent(
            role="Submission Specialist",
            goal="Submit the signed appeal to the payer through the required channel and record the confirmation",
            backstory="You are a billing specialist responsible for timely filing of appeals. You ensure the submission meets payer requirements and document the confirmation for audit purposes.",
            llm=get_crewai_llm_string(),
            verbose=True,
        )

