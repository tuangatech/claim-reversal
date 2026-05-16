# tests/conftest.py
"""Shared pytest configuration and markers."""

import pytest


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "llm: marks tests that require an LLM API call")

