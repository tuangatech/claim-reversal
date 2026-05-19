# agents/__init__.py
"""Agent definitions — only the Writer Agent uses CrewAI; others are direct tool calls."""

from agents.writer_agent import AppealWriterAgent

__all__ = ["AppealWriterAgent"]

