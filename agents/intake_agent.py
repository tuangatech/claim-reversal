# agents/intake_agent.py
"""Denial Intake CrewAI agent definition."""

from crewai import Agent

from shared.llm import get_crewai_llm_string


class DenialIntakeAgent:
    """Builds the Denial Intake Specialist agent."""

    def __init__(self, config: dict | None = None):
        self.config = config or {}

    def build(self) -> Agent:
        """Returns a CrewAI Agent for denial triage."""
        return Agent(
            role="Denial Intake Specialist",
            goal="Triage incoming clinical denials, classify type, validate appeal window, and score worthiness",
            backstory="You are an experienced billing specialist who quickly assesses whether a denied claim is worth appealing based on clinical classification, dollar amount, and deadline constraints.",
            llm=get_crewai_llm_string(),
            verbose=True,
        )

