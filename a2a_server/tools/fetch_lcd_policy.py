# a2a_server/tools/fetch_lcd_policy.py
"""LCD policy retrieval — mock no-op; Playwright in stretch goal."""


def fetch_lcd_policy(diagnosis_code: str) -> dict:
    """Returns LCD policy text. No-op when USE_PLAYWRIGHT is false."""
    return {}

