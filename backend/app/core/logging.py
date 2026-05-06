"""
Logging infrastructure for SmartDesk backend.
Replaces all print() calls with structured logging.
"""

import logging
import sys


def setup_logging(level: str = "INFO") -> None:
    """Configure root logger with consistent format for all SmartDesk modules."""
    logging.basicConfig(
        stream=sys.stdout,
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    # Quiet noisy third-party loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("googleapiclient").setLevel(logging.WARNING)
