"""Emotion detection routes.

These endpoints control the local webcam emotion service. The service itself
keeps webcam/model/session state in memory, so every route uses the same shared
instance for the lifetime of the backend process.
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi import HTTPException

from app.core.config import settings

logger = logging.getLogger("smartdesk.emotion_routes")
router = APIRouter()

EMOTION_PROJECT_DIR = (
    Path(__file__).resolve().parents[3]
    / "emotion-recognition"
    / "RAF-DB-improvement"
)

if str(EMOTION_PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(EMOTION_PROJECT_DIR))

try:
    from emotion_service import EmotionRecognitionService
except Exception as exc:  # pragma: no cover - exercised only when local deps are missing
    EmotionRecognitionService = None  # type: ignore[assignment]
    _IMPORT_ERROR: Exception | None = exc
else:
    _IMPORT_ERROR = None

_emotion_service: Any | None = None


def _get_emotion_service() -> Any:
    """Return the single emotion service instance for this backend process."""
    global _emotion_service

    if _IMPORT_ERROR is not None or EmotionRecognitionService is None:
        raise HTTPException(
            status_code=503,
            detail={
                "ok": False,
                "stage": "module_import",
                "message": f"Emotion recognition module is unavailable: {_IMPORT_ERROR}",
            },
        )

    if _emotion_service is None:
        _emotion_service = EmotionRecognitionService(
            project_dir=EMOTION_PROJECT_DIR,
            user_id=settings.DEFAULT_USER_ID,
        )

    return _emotion_service


def _wait_for_startup_status(service: Any, timeout_seconds: float = 30.0) -> dict[str, Any]:
    """Wait briefly for start() to reach camera-ready or an error state."""
    deadline = time.monotonic() + timeout_seconds
    status = service.get_status()

    while time.monotonic() < deadline:
        status = service.get_status()
        if status.get("camera_ready") or status.get("last_error") or not status.get("running"):
            break
        time.sleep(0.25)

    return service.get_status()


@router.post("/start")
def start_emotion_detection() -> dict[str, Any]:
    service = _get_emotion_service()

    try:
        result = service.start(show_window=False)
        status = _wait_for_startup_status(service)
    except Exception as exc:
        logger.exception("Failed to start emotion recognition.")
        raise HTTPException(
            status_code=500,
            detail={
                "ok": False,
                "stage": "start",
                "message": str(exc),
                "status": service.get_status(),
            },
        ) from exc

    ok = not bool(status.get("last_error"))
    message = result.get("message", "Emotion recognition started.")
    if not ok:
        message = status.get("last_error") or "Emotion recognition failed to start."

    return {
        "ok": ok,
        "message": message,
        "status": status,
    }


@router.post("/stop")
def stop_emotion_detection() -> dict[str, Any]:
    service = _get_emotion_service()

    try:
        result = service.stop(wait=True)
    except Exception as exc:
        logger.exception("Failed to stop emotion recognition.")
        raise HTTPException(
            status_code=500,
            detail={
                "ok": False,
                "stage": "stop",
                "message": str(exc),
                "status": service.get_status(),
            },
        ) from exc

    history = service.get_session_history()
    return {
        "ok": True,
        "message": result.get("message", "Emotion recognition stopped."),
        "status": result.get("status", service.get_status()),
        "session_history": history,
    }


@router.get("/status")
def get_emotion_status() -> dict[str, Any]:
    service = _get_emotion_service()
    return service.get_status()


@router.get("/sessions/current")
def get_current_emotion_session() -> dict[str, Any]:
    service = _get_emotion_service()
    return service.get_session_history()


def stop_emotion_service_if_running() -> None:
    """Stop the emotion service during backend shutdown if it is active."""
    if _emotion_service is None:
        return

    status = _emotion_service.get_status()
    if not status.get("running"):
        return

    try:
        _emotion_service.stop(wait=True)
    except Exception:
        logger.exception("Failed to stop emotion recognition during shutdown.")
