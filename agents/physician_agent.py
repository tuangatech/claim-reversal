# agents/physician_agent.py
"""Physician Sign-off CrewAI agent definition."""

from crewai import Agent

from shared.llm import get_crewai_llm_string


class PhysicianAgent:
    """Builds the Physician Sign-off agent."""

    def __init__(self, config: dict | None = None):
        self.config = config or {}

    def build(self) -> Agent:
        """Returns a CrewAI Agent for physician review and attestation."""
        return Agent(
            role="Physician Advisor",
            goal="Review appeal letters for clinical accuracy and provide physician attestation when required",
            backstory="You are a medical director who reviews clinical appeals to ensure the medical necessity argument is sound before signing off on submission to the payer.",
            llm=get_crewai_llm_string(),
            verbose=True,
        )

