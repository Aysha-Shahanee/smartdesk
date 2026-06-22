from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from dotenv import load_dotenv

from emotion_block_aggregator import EmotionBlockAggregator
from emotion_detector import WebcamEmotionDetector
from storage.pending_queue import PendingQueue
from storage.session_sync import SupabaseSessionSync
from storage.session_manager import SessionManager
from storage.supabase_sync import SupabaseEmotionSync


SYNC_RETRY_SECONDS = 300


class EmotionRecognitionService:
    def __init__(
        self,
        project_dir: Path | None = None,
        user_id: str = "local_user",
        output_path: Path | None = None,
    ) -> None:
        self.project_dir = Path(project_dir or Path(__file__).parent)
        load_dotenv(self.project_dir.parent / ".env")

        self.user_id = user_id
        self.output_path = Path(output_path or self.project_dir / "pending_emotion_blocks.jsonl")
        self.session_queue = PendingQueue(self.project_dir / "pending_emotion_sessions.jsonl")
        self.block_queue = PendingQueue(self.output_path)
        self.session_sync = SupabaseSessionSync(self.session_queue)
        self.sync_client = SupabaseEmotionSync(self.block_queue)
        self.completed_blocks_memory: list[dict[str, Any]] = []
        self.current_session_record: dict[str, Any] | None = None

        self.session_manager: SessionManager | None = None
        self.aggregator: EmotionBlockAggregator | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._detector: WebcamEmotionDetector | None = None

        self._status: dict[str, Any] = {
            "running": False,
            "latest_emotion": "Unknown",
            "session_id": None,
            "session_start_time": None,
            "current_block_start": None,
            "processed_frame_count": 0,
            "model_ready": False,
            "camera_ready": False,
            "supabase_configured": self.sync_client.is_configured,
            "last_error": None,
            "last_error_stage": None,
            "last_upload_error": None,
            "last_saved_block_time": None,
            "last_synced_block_time": None,
        }

    def start(self, show_window: bool = False) -> dict[str, Any]:
        with self._lock:
            if self._status["running"]:
                return {"ok": True, "message": "Emotion recognition is already running.", "status": dict(self._status)}

            self.session_manager = SessionManager(user_id=self.user_id)
            self.aggregator = EmotionBlockAggregator(
                output_path=self.output_path,
                session_manager=self.session_manager,
            )
            self.completed_blocks_memory = []
            self.current_session_record = self._build_session_record(status="running")
            self.session_sync.queue_session(self.current_session_record)
            self._stop_event.clear()
            self._status.update(
                {
                    "running": True,
                    "latest_emotion": "Unknown",
                    "session_id": self.session_manager.session_id,
                    "session_start_time": self.session_manager.session_start_time.isoformat(),
                    "current_block_start": self.aggregator.block_start.isoformat() if self.aggregator.block_start else None,
                    "processed_frame_count": 0,
                    "model_ready": False,
                    "camera_ready": False,
                    "supabase_configured": self.sync_client.is_configured,
                    "last_error": None,
                    "last_error_stage": None,
                    "last_upload_error": None,
                }
            )

        self._retry_pending_sync()
        self._thread = threading.Thread(target=self._run_loop, args=(show_window,), daemon=True)
        self._thread.start()
        return {"ok": True, "message": "Emotion recognition started.", "status": self.get_status()}

    def stop(self, wait: bool = True) -> dict[str, Any]:
        self._stop_event.set()
        if wait and self._thread and self._thread.is_alive():
            self._thread.join()
        return {"ok": True, "message": "Emotion recognition stopped.", "status": self.get_status()}

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            status = dict(self._status)
        if self.aggregator:
            status["current_block_start"] = (
                self.aggregator.block_start.isoformat() if self.aggregator.block_start else None
            )
            status["processed_frame_count"] = self.aggregator.processed_frame_count
        return status

    def get_session_history(self) -> dict[str, Any]:
        status = self.get_status()
        session_id = status.get("session_id")
        completed_blocks = []
        if session_id and self.sync_client.is_configured:
            completed_blocks = self.sync_client.query_session_records(session_id, user_id=self.user_id)
            if self.sync_client.last_error:
                self._set_error("supabase_query", self.sync_client.last_error)
        if not completed_blocks:
            completed_blocks = [block for block in self.completed_blocks_memory if block.get("session_id") == session_id]

        current_block = None
        if self.aggregator:
            current_block = {
                "block_start_time": self.aggregator.block_start.isoformat() if self.aggregator.block_start else None,
                "emotion_scores": dict(self.aggregator.emotion_scores),
                "processed_frame_count": self.aggregator.processed_frame_count,
            }

        return {
            "ok": True,
            "status": status,
            "session": self.current_session_record,
            "current_block": current_block,
            "completed_blocks": completed_blocks,
        }

    def get_history(self, period: str) -> dict[str, Any]:
        return {"ok": False, "stage": "history_removed", "message": "Use get_session_history() for current session data.", "records": []}

    def _run_loop(self, show_window: bool) -> None:
        try:
            detector = self._prepare_runtime()
            if not detector.open_camera(0):
                self._set_error("camera_open", "Could not open webcam.")
                return
            self._set_status(camera_ready=True)

            frame_count = 0
            face_box = None
            last_processed_at = 0.0
            last_sync_retry_at = time.monotonic()

            while not self._stop_event.is_set():
                ret, frame = detector.read_frame()
                if not ret:
                    self._set_error("frame_capture", "Could not read frame from webcam.")
                    break

                frame_count += 1
                self._save_and_sync_blocks(self.aggregator.complete_expired_blocks())

                now_monotonic = time.monotonic()
                if now_monotonic - last_sync_retry_at >= SYNC_RETRY_SECONDS:
                    last_sync_retry_at = now_monotonic
                    self._retry_pending_sync()

                try:
                    face_box = detector.update_face_box(frame, frame_count, face_box)
                except Exception as exc:
                    self._set_error("face_detection", str(exc))

                if face_box is not None:
                    face = detector.crop_face(frame, face_box)
                    should_process_frame = now_monotonic - last_processed_at >= 1.0

                    if face.size != 0 and should_process_frame:
                        last_processed_at = now_monotonic
                        self._predict_frame(detector, face)

                    if show_window:
                        detector.draw_prediction(frame, face_box, self.get_status()["latest_emotion"])

                if show_window:
                    if detector.show_frame("Emotion Detector (Stable)", frame):
                        self._stop_event.set()
        finally:
            self._finish_run(show_window)

    def _prepare_runtime(self):
        detector = WebcamEmotionDetector(self.project_dir)
        self._detector = detector

        self._set_stage("model_download")
        model_path = detector.ensure_model_file()

        self._set_stage("model_load")
        detector.load_model(model_path)

        self._set_status(model_ready=True)
        return detector

    def _predict_frame(self, detector: WebcamEmotionDetector, face) -> None:
        self._set_stage("prediction")
        try:
            emotion_probabilities = detector.predict_face(face)
        except Exception as exc:
            self._set_error("prediction", str(exc))
            return

        latest_emotion = max(emotion_probabilities, key=emotion_probabilities.get)
        completed_blocks = self.aggregator.add_frame(emotion_probabilities)
        self._set_status(latest_emotion=latest_emotion)
        self._save_and_sync_blocks(completed_blocks)

    def _finish_run(self, show_window: bool) -> None:
        final_block = None
        if self.aggregator:
            try:
                self._set_stage("stop_flush")
                final_block = self.aggregator.flush()
            except Exception as exc:
                self._set_error("stop_flush", str(exc))

        if final_block is not None:
            self._save_and_sync_blocks([final_block])

        if self._detector is not None:
            self._detector.release()

        if show_window:
            try:
                if self._detector is not None:
                    self._detector.close_windows()
            except Exception:
                pass

        if self.current_session_record:
            self.current_session_record = {
                **self.current_session_record,
                "ended_at": datetime.now().astimezone().isoformat(),
                "status": "stopped" if not self._status.get("last_error") else "failed",
                "updated_at": datetime.now().astimezone().isoformat(),
            }
            self.session_sync.queue_session(self.current_session_record)
        self._retry_pending_sync()
        self._set_status(running=False, camera_ready=False)

    def _save_and_sync_blocks(self, blocks: list[dict]) -> None:
        if not blocks:
            return

        self._set_stage("local_storage")
        for block in blocks:
            self.sync_client.queue_block(block)
            self.completed_blocks_memory.append(block)
            self._set_status(last_saved_block_time=block.get("block_end_time"))

        self._retry_pending_sync()

    def _retry_pending_sync(self) -> None:
        if self.session_sync.is_configured:
            self._set_stage("supabase_upload")
            self.session_sync.retry_pending_sessions()
            if self.session_sync.last_error:
                self._set_status(last_upload_error=self.session_sync.last_error)
                self._set_error("supabase_upload", self.session_sync.last_error)
        elif self.session_sync.disabled_reason:
            self._set_status(last_upload_error=self.session_sync.disabled_reason)

        if not self.sync_client.is_configured:
            if self.sync_client.disabled_reason:
                self._set_status(last_upload_error=self.sync_client.disabled_reason)
            return

        self._set_stage("supabase_upload")
        uploaded_count = self.sync_client.retry_pending_blocks()
        if uploaded_count:
            self._set_status(last_upload_error=None)
        elif self.sync_client.last_error:
            self._set_status(last_upload_error=self.sync_client.last_error)
            self._set_error("supabase_upload", self.sync_client.last_error)

    def _build_session_record(self, status: str) -> dict[str, Any]:
        if not self.session_manager:
            raise RuntimeError("No active session manager.")

        now = datetime.now().astimezone().isoformat()
        return {
            "id": self.session_manager.session_id,
            "user_id": self.session_manager.user_id,
            "session_number": None,
            "started_at": self.session_manager.session_start_time.isoformat(),
            "ended_at": None,
            "status": status,
            "created_at": now,
            "updated_at": now,
        }

    def _set_stage(self, stage: str) -> None:
        self._set_status(last_error_stage=stage)

    def _set_error(self, stage: str, message: str) -> None:
        self._set_status(last_error_stage=stage, last_error=message)

    def _set_status(self, **updates: Any) -> None:
        with self._lock:
            self._status.update(updates)
