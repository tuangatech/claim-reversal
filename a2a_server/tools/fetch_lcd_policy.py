# a2a_server/tools/fetch_lcd_policy.py
"""LCD policy retrieval — mock no-op; Playwright in stretch goal."""

import os


def fetch_lcd_policy(diagnosis_code: str) -> dict:
    """Returns LCD policy text. No-op when USE_PLAYWRIGHT is false."""

    use_playwright = os.environ.get("USE_PLAYWRIGHT", "false").lower() == "true"

    if not use_playwright:
        return {"policy_text": "", "source_url": ""}

    # Stretch goal: Playwright implementation would go here
    raise NotImplementedError("Playwright LCD policy fetch not yet implemented")

