"""Service wrapper for the standalone SmartDesk detection module."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

import cv2

from src.pipeline import SmartDeskPipeline, build_smartdesk_session_schedule
from src.pipeline.session_schedule import choose_real_end_time, first_block_end_offset_seconds
from src.state_fusion.block_fusion import (
    FINAL_STATE_WINDOW_SECONDS,
    build_and_store_final_state_summary,
)
from src.state_fusion.reporting import (
    REPORTING_WINDOW_SECONDS,
    build_and_store_reporting_summary,
)
from src.temporal.block_store import JsonlBlockStore, SessionRecord


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SERVICE_STORAGE_DIR = PROJECT_ROOT / "data" / "temporal"


CaptureFactory = Callable[[int], Any]
PipelineFactory = Callable[..., Any]


@dataclass
class SmartDeskServiceState:
    """Mutable runtime state protected by the service lock."""

    running: bool = False
    camera_ready: bool = False
    last_error: str | None = None
    current_session_id: str | None = None
    program_start_time: str | None = None
    warmup_end_time: str | None = None
    real_start_time: str | None = None
    actual_camera_end_time: str | None = None
    usable_block_end_time: str | None = None
    discarded_tail_seconds: float = 0.0
    startup_wait_seconds_after_warmup: float = 0.0
    sample_fps: float = 2.0
    frames_read: int = 0
    samples_processed: int = 0
    face_detected_samples: int = 0
    latest_engagement: str | None = None
    latest_engagement_confidence: float = 0.0
    latest_engagement_block_start_time: str | None = None
    latest_engagement_block_end_time: str | None = None
    completed_counts: dict[str, int] = field(
        default_factory=lambda: {
            "emotion": 0,
            "engagement": 0,
            "sleepiness": 0,
            "final_state": 0,
            "reporting": 0,
        }
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "camera_ready": self.camera_ready,
            "last_error": self.last_error,
            "current_session_id": self.current_session_id,
            "program_start_time": self.program_start_time,
            "warmup_end_time": self.warmup_end_time,
            "real_start_time": self.real_start_time,
            "actual_camera_end_time": self.actual_camera_end_time,
            "usable_block_end_time": self.usable_block_end_time,
            "discarded_tail_seconds": self.discarded_tail_seconds,
            "startup_wait_seconds_after_warmup": self.startup_wait_seconds_after_warmup,
            "sample_fps": self.sample_fps,
            "frames_read": self.frames_read,
            "samples_processed": self.samples_processed,
            "face_detected_samples": self.face_detected_samples,
            "latest_engagement": self.latest_engagement,
            "latest_engagement_confidence": self.latest_engagement_confidence,
            "latest_engagement_block_start_time": self.latest_engagement_block_start_time,
            "latest_engagement_block_end_time": self.latest_engagement_block_end_time,
            "completed_counts": dict(self.completed_counts),
        }


class SmartDeskEmotionService:
    """Backend-friendly control surface around the SmartDesk webcam pipeline.

    The old app needs simple commands such as start, stop, status, and history.
    This wrapper keeps the CNN, landmark, block timing, fusion, and persistence
    details inside the standalone module.
    """

    def __init__(
        self,
        *,
        camera_index: int = 0,
        storage_dir: str | Path = DEFAULT_SERVICE_STORAGE_DIR,
        sample_fps: float = 2.0,
        warmup_seconds: float = 5.0,
        capture_factory: CaptureFactory | None = None,
        pipeline_factory: PipelineFactory | None = None,
        store: Any | None = None,
    ) -> None:
        if sample_fps <= 0:
            raise ValueError("sample_fps must be positive")
        if warmup_seconds < 0:
            raise ValueError("warmup_seconds cannot be negative")

        self.camera_index = camera_index
        self.storage_dir = Path(storage_dir)
        self.sample_fps = float(sample_fps)
        self.warmup_seconds = float(warmup_seconds)
        self.capture_factory = capture_factory or cv2.VideoCapture
        self.pipeline_factory = pipeline_factory or SmartDeskPipeline
        self.store = store or JsonlBlockStore(self.storage_dir)

        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._state = SmartDeskServiceState(sample_fps=self.sample_fps)

    def start(
        self,
        *,
        show_window: bool = False,
        seconds: float | None = None,
    ) -> dict[str, Any]:
        """Start the webcam service in a background thread."""
        if seconds is not None and seconds <= 0:
            raise ValueError("seconds must be positive when provided")

        with self._lock:
            if self._state.running:
                return self.get_status()

            self._stop_event.clear()
            current_session_id = str(uuid4())
            if hasattr(self.store, "session_id"):
                self.store.session_id = current_session_id
            self._state = SmartDeskServiceState(
                running=True,
                sample_fps=self.sample_fps,
                current_session_id=current_session_id,
            )
            self._thread = threading.Thread(
                target=self._run_session,
                kwargs={"show_window": show_window, "seconds": seconds},
                daemon=True,
                name="SmartDeskEmotionService",
            )
            self._thread.start()
            return self.get_status()

    def stop(self, *, wait: bool = True, timeout_seconds: float = 10.0) -> dict[str, Any]:
        """Request a clean stop and return latest status."""
        self._stop_event.set()
        thread = self._thread
        if wait and thread is not None and thread.is_alive():
            thread.join(timeout=timeout_seconds)
        return self.get_status()

    def get_status(self) -> dict[str, Any]:
        """Return service and current-session status."""
        with self._lock:
            status = self._state.to_dict()
        status["storage_dir"] = str(self.storage_dir)
        return status

    def get_session_history(self, *, limit: int = 20) -> dict[str, Any]:
        """Return recent completed sessions and latest persisted blocks."""
        sessions = self.store.read_sessions()
        recent_sessions = sessions[-max(0, limit) :] if limit else sessions
        return {
            "sessions": [session.__dict__ for session in recent_sessions],
            "latest_blocks": {
                "emotion": [block.summary for block in self.store.read_blocks("emotion")],
                "engagement": [block.summary for block in self.store.read_blocks("engagement")],
                "sleepiness": [block.summary for block in self.store.read_blocks("sleepiness")],
                "final_state": [block.summary for block in self.store.read_blocks("final_state")],
                "reporting": [block.summary for block in self.store.read_blocks("reporting")],
            },
        }

    def _run_session(self, *, show_window: bool, seconds: float | None) -> None:
        capture = None
        pipeline = None
        program_start = datetime.now().astimezone()
        program_start_monotonic = time.monotonic()
        frames_read = 0
        samples_processed = 0
        face_detected_samples = 0
        completed_counts = {
            "emotion": 0,
            "engagement": 0,
            "sleepiness": 0,
            "final_state": 0,
            "reporting": 0,
        }
        session_id = self.get_status().get("current_session_id") or str(uuid4())

        try:
            self._set_state(
                program_start_time=program_start.isoformat(),
                completed_counts=completed_counts,
            )
            capture = self.capture_factory(self.camera_index)
            if not capture.isOpened():
                raise RuntimeError(f"Could not open webcam index {self.camera_index}")
            self._set_state(camera_ready=True)

            warmup_end_monotonic = program_start_monotonic + self.warmup_seconds
            with self.pipeline_factory(storage_dir=self.storage_dir):
                while time.monotonic() < warmup_end_monotonic and not self._stop_event.is_set():
                    ok, frame = capture.read()
                    if not ok:
                        continue
                    frames_read += 1
                    self._set_state(frames_read=frames_read)
                    if show_window:
                        cv2.imshow("SmartDesk session", frame)
                        if cv2.waitKey(1) & 0xFF == ord("q"):
                            self._stop_event.set()
                            break

            warmup_end_time = datetime.now().astimezone()
            warmup_end_monotonic = time.monotonic()
            schedule = build_smartdesk_session_schedule(warmup_end_time)
            real_start_offset = schedule.real_start_offset_seconds
            interval = 1.0 / self.sample_fps
            duration_end_monotonic = (
                warmup_end_monotonic + real_start_offset + seconds
                if seconds is not None
                else None
            )
            next_sample_time = warmup_end_monotonic
            next_final_state_start = real_start_offset
            next_final_state_end = first_block_end_offset_seconds(
                warmup_end_time,
                schedule.landmark_state,
                FINAL_STATE_WINDOW_SECONDS,
            )
            next_reporting_start = real_start_offset
            next_reporting_end = first_block_end_offset_seconds(
                warmup_end_time,
                schedule.full_system,
                REPORTING_WINDOW_SECONDS,
            )

            self._set_state(
                warmup_end_time=warmup_end_time.isoformat(),
                real_start_time=schedule.real_start.isoformat(),
                startup_wait_seconds_after_warmup=real_start_offset,
            )

            pipeline = self.pipeline_factory(
                storage_dir=self.storage_dir,
                store=self.store,
                emotion_official_start_timestamp=real_start_offset,
                landmark_official_start_timestamp=real_start_offset,
                block_time_base=warmup_end_time,
            )
            if hasattr(pipeline, "__enter__"):
                pipeline = pipeline.__enter__()

            while not self._stop_event.is_set():
                if duration_end_monotonic is not None and time.monotonic() >= duration_end_monotonic:
                    break

                ok, frame = capture.read()
                if not ok:
                    continue
                frames_read += 1

                now = time.monotonic()
                if now < next_sample_time:
                    self._set_state(frames_read=frames_read)
                    continue

                timestamp = now - warmup_end_monotonic
                if timestamp < real_start_offset:
                    next_sample_time += interval
                    self._set_state(frames_read=frames_read)
                    continue

                update = pipeline.process_frame(frame, timestamp=timestamp)
                result = update.frame_result
                samples_processed += 1
                if result.detection.face_detected:
                    face_detected_samples += 1

                if update.emotion_block is not None:
                    completed_counts["emotion"] += 1
                if update.engagement_block is not None:
                    completed_counts["engagement"] += 1
                    self._set_state(
                        **_engagement_status(update.engagement_block),
                    )
                if update.sleepiness_block is not None:
                    completed_counts["sleepiness"] += 1

                while timestamp >= next_final_state_end:
                    current_final_end = next_final_state_end
                    next_final_state_end = self._store_final_state_block(
                        warmup_end_time,
                        completed_counts,
                        next_final_state_start,
                        current_final_end,
                    )
                    next_final_state_start = current_final_end

                while timestamp >= next_reporting_end:
                    current_reporting_end = next_reporting_end
                    next_reporting_end = self._store_reporting_block(
                        warmup_end_time,
                        completed_counts,
                        next_reporting_start,
                        current_reporting_end,
                    )
                    next_reporting_start = current_reporting_end

                next_sample_time += interval
                self._set_state(
                    frames_read=frames_read,
                    samples_processed=samples_processed,
                    face_detected_samples=face_detected_samples,
                    completed_counts=completed_counts,
                )

                if show_window:
                    cv2.imshow("SmartDesk session", frame)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        self._stop_event.set()
                        break

            actual_camera_end_time = datetime.now().astimezone()
            raw_usable_block_end_time = choose_real_end_time(actual_camera_end_time)
            usable_end_timestamp = max(
                real_start_offset,
                (raw_usable_block_end_time - warmup_end_time).total_seconds(),
            )
            usable_block_end_time = warmup_end_time + timedelta(seconds=usable_end_timestamp)
            discarded_tail_seconds = max(
                0.0,
                (actual_camera_end_time - usable_block_end_time).total_seconds(),
            )

            flushed = pipeline.flush_until(usable_end_timestamp)
            completed_counts["emotion"] += len(flushed.emotion_blocks)
            completed_counts["engagement"] += len(flushed.engagement_blocks)
            completed_counts["sleepiness"] += len(flushed.sleepiness_blocks)
            if flushed.engagement_blocks:
                self._set_state(
                    **_engagement_status(flushed.engagement_blocks[-1]),
                )

            while usable_end_timestamp >= next_final_state_end:
                current_final_end = next_final_state_end
                next_final_state_end = self._store_final_state_block(
                    warmup_end_time,
                    completed_counts,
                    next_final_state_start,
                    current_final_end,
                )
                next_final_state_start = current_final_end

            while usable_end_timestamp >= next_reporting_end:
                current_reporting_end = next_reporting_end
                next_reporting_end = self._store_reporting_block(
                    warmup_end_time,
                    completed_counts,
                    next_reporting_start,
                    current_reporting_end,
                )
                next_reporting_start = current_reporting_end

            self.store.append_session(
                SessionRecord(
                    session_id=session_id,
                    saved_at=datetime.now().astimezone().isoformat(),
                    program_start_time=program_start.isoformat(),
                    warmup_end_time=warmup_end_time.isoformat(),
                    real_start_time=schedule.real_start.isoformat(),
                    actual_camera_end_time=actual_camera_end_time.isoformat(),
                    usable_block_end_time=usable_block_end_time.isoformat(),
                    discarded_tail_seconds=discarded_tail_seconds,
                    startup_wait_seconds_after_warmup=real_start_offset,
                    official_seconds_requested=float(seconds or 0.0),
                    sample_fps=self.sample_fps,
                    frames_read=frames_read,
                    samples_processed=samples_processed,
                    face_detected_samples=face_detected_samples,
                    completed_counts=dict(completed_counts),
                    storage_dir=str(self.storage_dir),
                )
            )
            self._set_state(
                actual_camera_end_time=actual_camera_end_time.isoformat(),
                usable_block_end_time=usable_block_end_time.isoformat(),
                discarded_tail_seconds=discarded_tail_seconds,
                frames_read=frames_read,
                samples_processed=samples_processed,
                face_detected_samples=face_detected_samples,
                completed_counts=completed_counts,
            )
        except Exception as exc:
            self._set_state(last_error=str(exc))
        finally:
            if pipeline is not None and hasattr(pipeline, "__exit__"):
                pipeline.__exit__(None, None, None)
            elif pipeline is not None and hasattr(pipeline, "close"):
                pipeline.close()
            if capture is not None:
                capture.release()
            if show_window:
                cv2.destroyAllWindows()
            self._set_state(running=False, camera_ready=False)

    def _store_final_state_block(
        self,
        base_time: datetime,
        completed_counts: dict[str, int],
        final_start: float,
        final_end: float,
    ) -> float:
        build_and_store_final_state_summary(
            self.store,
            start_timestamp=final_start,
            end_timestamp=final_end,
            block_start_time=_clock_instant(base_time, final_start),
            block_end_time=_clock_instant(base_time, final_end),
        )
        completed_counts["final_state"] += 1
        return final_end + FINAL_STATE_WINDOW_SECONDS

    def _store_reporting_block(
        self,
        base_time: datetime,
        completed_counts: dict[str, int],
        report_start: float,
        report_end: float,
    ) -> float:
        build_and_store_reporting_summary(
            self.store,
            start_timestamp=report_start,
            end_timestamp=report_end,
            block_start_time=_clock_instant(base_time, report_start),
            block_end_time=_clock_instant(base_time, report_end),
        )
        completed_counts["reporting"] += 1
        return report_end + REPORTING_WINDOW_SECONDS

    def _set_state(self, **updates: Any) -> None:
        with self._lock:
            for key, value in updates.items():
                setattr(self._state, key, value)


def _clock_instant(base_time: datetime, seconds: float) -> str:
    return (base_time + timedelta(seconds=float(seconds))).isoformat()


def _engagement_status(block: Any) -> dict[str, Any]:
    return {
        "latest_engagement": block.classification.label.value,
        "latest_engagement_confidence": block.classification.confidence,
        "latest_engagement_block_start_time": block.summary.block_start_time,
        "latest_engagement_block_end_time": block.summary.block_end_time,
    }


