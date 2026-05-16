# shared/llm.py
"""Single place to create OpenRouter-backed LLM clients."""

import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def get_agent_llm() -> tuple[OpenAI, str]:
    """Returns an OpenAI client pointed at OpenRouter and the agent model string."""

    api_key = os.environ["OPENROUTER_API_KEY"]
    model = os.environ.get("OPENROUTER_AGENT_MODEL", "openai/gpt-5-mini")
    client = OpenAI(base_url=OPENROUTER_BASE_URL, api_key=api_key)
    return client, model


def get_crewai_llm_string() -> str:
    """Returns the LiteLLM-formatted model string for CrewAI agent definitions."""

    model = os.environ.get("OPENROUTER_AGENT_MODEL", "openai/gpt-5-mini")
    return f"openrouter/{model}"

