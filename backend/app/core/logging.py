"""
Logging infrastructure for SmartDesk backend.
Replaces all print() calls with structured logging.
"""

import logging
import sys


# Paths in this list are silently dropped from the uvicorn access log.
# Use this for deprecated/legacy endpoints that are noisy but expected.
_SUPPRESSED_PATHS: tuple[str, ...] = (
    "/api/v1/ide/minute-window",
    "/api/v1/vscode/minute-window",
    "/api/v1/browser/minute-window",
    "/api/v1/os/minute-window",
)


class _SuppressPathFilter(logging.Filter):
    """Drop uvicorn access-log records whose URL matches a blocklist."""

    def filter(self, record: logging.LogRecord) -> bool:
        # uvicorn access records: args[2] is the path+query string, e.g. "GET /api/... HTTP/1.1"
        try:
            message = record.getMessage()
            return not any(path in message for path in _SUPPRESSED_PATHS)
        except Exception:
            return True  # never crash the logging system


_access_filter = _SuppressPathFilter()


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

    # Suppress access-log spam from the old VS Code / browser extension
    # hitting the deprecated minute-window endpoints.
    uvicorn_access = logging.getLogger("uvicorn.access")
    # Avoid adding the filter twice on hot-reload
    if not any(isinstance(f, _SuppressPathFilter) for f in uvicorn_access.filters):
        uvicorn_access.addFilter(_access_filter)
