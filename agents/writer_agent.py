# agents/writer_agent.py
"""Appeal Writer CrewAI agent definition."""

from crewai import Agent

from shared.llm import get_crewai_llm_string


class AppealWriterAgent:
    """Builds the Appeal Writer agent."""

    def __init__(self, config: dict | None = None):
        self.config = config or {}

    def build(self) -> Agent:
        """Returns a CrewAI Agent for drafting appeal letters."""
        return Agent(
            role="Appeal Writer",
            goal="Draft a compelling, payer-compliant appeal letter using clinical evidence and guideline citations",
            backstory="You are a skilled medical appeal writer who assembles formal rebuttal letters that clearly argue medical necessity using clinical documentation and payer-specific formatting requirements.",
            llm=get_crewai_llm_string(),
            verbose=True,
        )

