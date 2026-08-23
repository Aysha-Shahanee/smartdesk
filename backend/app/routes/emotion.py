"""SmartDesk detection routes.

These endpoints control the local webcam SmartDesk detection service. The service itself
keeps webcam/model/session state in memory, so every route uses the same shared
instance for the lifetime of the backend process.
"""

from __future__ import annotations

import logging
import sys
import time
from datetime import timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.database import get_db
from app.core.time import local_day_start, parse_iso
from app.repositories.preference_repository import PreferenceRepository
from app.repositories.preference_repository import WEBCAM_EMOTION_CONSENT
from app.services import smartdesk_detection_endpoint_service
from app.services import smartdesk_detection_response_builder
from app.services.smartdesk_detection_sql_store import SmartDeskSqlBlockStore

logger = logging.getLogger("smartdesk.emotion_routes")
router = APIRouter()


class EmotionConsentUpdate(BaseModel):
    webcam_enabled: bool

SMARTDESK_V2_DIR = (
    Path(__file__).resolve().parents[3]
    / "emotion-recognition"
    / "smartdesk_v2"
)

if str(SMARTDESK_V2_DIR) not in sys.path:
    sys.path.insert(0, str(SMARTDESK_V2_DIR))

try:
    from src.service import SmartDeskEmotionService
except Exception as exc:  # pragma: no cover - exercised only when local deps are missing
    SmartDeskEmotionService = None  # type: ignore[assignment]
    _IMPORT_ERROR: Exception | None = exc
else:
    _IMPORT_ERROR = None

_emotion_service: Any | None = None


def _get_emotion_service() -> Any:
    """Return the single SmartDesk v2 service instance for this backend process."""
    global _emotion_service

    if _IMPORT_ERROR is not None or SmartDeskEmotionService is None:
        raise HTTPException(
            status_code=503,
            detail={
                "ok": False,
                "stage": "module_import",
                "message": f"SmartDesk v2 detection module is unavailable: {_IMPORT_ERROR}",
            },
        )

    if _emotion_service is None:
        store = SmartDeskSqlBlockStore(
            user_id=settings.DEFAULT_USER_ID,
            session_factory=SessionLocal,
        )
        _emotion_service = SmartDeskEmotionService(store=store)

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


@router.get("/stress")
def get_stress(
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    user_id: str | None = Query(None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Workload risk derived from SmartDesk v2 reporting blocks over a window.

    Defaults to today in the application timezone. `summary.workload_risk_score` is null when
    the window holds no observed blocks — the caller should say so rather than
    render a zero.
    """
    try:
        start = parse_iso(from_) if from_ else local_day_start()
        end = parse_iso(to) if to else start + timedelta(days=1)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=400,
            detail={"ok": False, "message": "from and to must be ISO 8601 timestamps"},
        )

    if end < start:
        raise HTTPException(
            status_code=400,
            detail={"ok": False, "message": "to must not be earlier than from"},
        )

    return smartdesk_detection_endpoint_service.workload_risk_response(
        db,
        user_id=user_id or settings.DEFAULT_USER_ID,
        start=start,
        end=end,
    )


@router.get("/consent")
def get_emotion_consent(db: Session = Depends(get_db)) -> dict[str, Any]:
    granted = PreferenceRepository(db).get_bool(
        settings.DEFAULT_USER_ID, WEBCAM_EMOTION_CONSENT, default=False
    )
    return {"webcam_enabled": granted}


@router.put("/consent")
def set_emotion_consent(
    payload: EmotionConsentUpdate, db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Record the Settings webcam toggle, and stop capture when it is revoked."""
    granted = PreferenceRepository(db).set_bool(
        settings.DEFAULT_USER_ID, WEBCAM_EMOTION_CONSENT, payload.webcam_enabled
    )
    if not granted:
        stop_emotion_service_if_running()
    return {"webcam_enabled": granted}


def _require_webcam_consent(db: Session) -> None:
    """Refuse to open the camera unless the user has said yes.

    The check belongs here rather than in the renderer: the capture loop runs in
    this process, so this is the only place that can actually enforce it.
    """
    granted = PreferenceRepository(db).get_bool(
        settings.DEFAULT_USER_ID, WEBCAM_EMOTION_CONSENT, default=False
    )
    if not granted:
        raise HTTPException(
            status_code=403,
            detail={
                "ok": False,
                "stage": "consent",
                "message": (
                    "Webcam emotion detection is turned off. Enable it under "
                    "Settings > Privacy Controls to start."
                ),
            },
        )


@router.post("/start")
def start_emotion_detection(db: Session = Depends(get_db)) -> dict[str, Any]:
    _require_webcam_consent(db)
    service = _get_emotion_service()

    try:
        service.start(show_window=False)
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

    ok = not bool(status.get("last_error")) and bool(status.get("running", True))
    message = "SmartDesk detection started."
    if not ok:
        message = status.get("last_error") or "SmartDesk detection failed to start."

    return {
        "ok": ok,
        "message": message,
        "status": smartdesk_detection_response_builder.status_to_api_status(status),
    }


@router.post("/stop")
def stop_emotion_detection() -> dict[str, Any]:
    service = _get_emotion_service()

    try:
        status = service.stop(wait=True)
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
    normalized_status = smartdesk_detection_response_builder.status_to_api_status(status)
    return {
        # A timed-out join leaves the capture thread alive; say so rather than
        # reporting a stop that did not happen.
        "ok": not bool(status.get("running", False)),
        "message": "SmartDesk detection stopped.",
        "status": normalized_status,
        "session_history": history,
    }


@router.get("/status")
def get_emotion_status() -> dict[str, Any]:
    service = _get_emotion_service()
    return smartdesk_detection_response_builder.status_to_api_status(service.get_status())


@router.get("/sessions/current")
def get_current_emotion_session(
    user_id: str | None = Query(None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    service = _get_emotion_service()
    return smartdesk_detection_endpoint_service.current_session_response(
        db,
        user_id=user_id or settings.DEFAULT_USER_ID,
        status=service.get_status(),
    )


def stop_emotion_service_if_running() -> None:
    """Stop the emotion service during backend shutdown if it is active."""
    if _emotion_service is None:
        return

    status = _emotion_service.get_status()
    if not status.get("running"):
        return

    try:
        # Bounded so a stalled webcam cannot keep the backend from exiting.
        result = _emotion_service.stop(wait=True, timeout_seconds=5.0)
        if not result.get("ok"):
            logger.warning("Emotion capture thread still running at shutdown.")
    except Exception:
        logger.exception("Failed to stop emotion recognition during shutdown.")

