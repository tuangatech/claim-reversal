# shared/logging.py
"""Configures structlog for JSON output with claim_id correlation across services."""

import logging
import sys

import structlog


def configure_logging(service_name: str) -> None:
    """Configures structlog for JSON output with service identification."""
    # Set up stdlib logging to route through structlog
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=logging.INFO)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.EventRenamer("msg"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )

    # Bind service name globally so it appears in every log line
    structlog.contextvars.bind_contextvars(service=service_name)

