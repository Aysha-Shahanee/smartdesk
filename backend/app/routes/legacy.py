"""Legacy endpoint shim — Phase 10 compatibility.

The old VS Code extension (pre-session-architecture) POSTed minute-window
data to these endpoints.  They no longer exist in the new architecture, but
the old extension may still be installed on the user's machine and will keep
hitting them until the extension is updated.

Instead of returning 404 (which pollutes the server log), return 410 Gone
with a clear migration message and suppress INFO logging for these paths.
"""

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()
logger = logging.getLogger("smartdesk.legacy")

_MIGRATION_MSG = (
    "This endpoint is deprecated. "
    "Please update the SmartDesk VS Code / browser extension to the "
    "session-based version that POSTs to /api/v1/ingest/vscode/event."
)


def _gone(source: str):
    logger.debug("Legacy %s minute-window request received (extension not yet updated).", source)
    return JSONResponse(
        status_code=410,
        content={"detail": _MIGRATION_MSG, "deprecated_endpoint": True},
    )


# ── Old IDE / VS Code minute-window endpoints ──────────────────────────────
@router.post("/ide/minute-window")
async def legacy_ide_minute_window(request: Request):
    return _gone("ide")


@router.post("/vscode/minute-window")
async def legacy_vscode_minute_window(request: Request):
    return _gone("vscode")


# ── Old browser minute-window endpoint ────────────────────────────────────
@router.post("/browser/minute-window")
async def legacy_browser_minute_window(request: Request):
    return _gone("browser")


# ── Old OS minute-window endpoint ─────────────────────────────────────────
@router.post("/os/minute-window")
async def legacy_os_minute_window(request: Request):
    return _gone("os")
