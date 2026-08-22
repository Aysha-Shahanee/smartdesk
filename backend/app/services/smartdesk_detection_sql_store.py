"""SQL-backed block store for the SmartDesk v2 runtime.

The standalone SmartDesk runtime writes to a small store interface. This adapter
keeps that runtime independent from SQLAlchemy while letting the old backend
persist the same completed session/block summaries into smartdesk_* tables.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from typing import Any, Callable, TypeVar
from uuid import uuid4

from app.repositories.smartdesk_detection_repository import SmartDeskDetectionRepository

T = TypeVar("T")


def _load_smartdesk_types():
    """Import copied SmartDesk v2 types after its package path is configured."""
    from src.drowsiness.classifier import classify_drowsiness
    from src.engagement.classifier import classify_engagement
    from src.temporal.block_store import SessionRecord, StoredBlock

    return {
        "classify_drowsiness": classify_drowsiness,
        "classify_engagement": classify_engagement,
        "SessionRecord": SessionRecord,
        "StoredBlock": StoredBlock,
    }


class SmartDeskSqlBlockStore:
    """Persist SmartDesk v2 completed blocks through the backend repository."""

    def __init__(
        self,
        repository: SmartDeskDetectionRepository | None = None,
        *,
        user_id: str,
        session_id: str | None = None,
        session_factory: Callable[[], Any] | None = None,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        if not user_id:
            raise ValueError("user_id is required for SmartDesk SQL storage")
        if repository is None and session_factory is None:
            raise ValueError("repository or session_factory is required for SmartDesk SQL storage")
        self.repository = repository
        self.session_factory = session_factory
        self.user_id = user_id
        self.session_id = session_id or str(uuid4())
        self.now_factory = now_factory or (lambda: datetime.now(UTC).astimezone())

    def append_emotion(self, summary: Any) -> None:
        self._append_signal_block("emotion", summary)

    def append_engagement(self, summary: Any) -> None:
        label = None
        try:
            types = _load_smartdesk_types()
            label = types["classify_engagement"](summary).label.value
        except Exception:
            label = None
        self._append_signal_block("engagement", summary, engagement_label=label)

    def append_sleepiness(self, summary: Any) -> None:
        label = None
        try:
            types = _load_smartdesk_types()
            label = types["classify_drowsiness"](summary).label.value
        except Exception:
            label = None
        self._append_signal_block("sleepiness", summary, sleepiness_label=label)

    def append_final_state(self, summary: Any) -> None:
        record = {
            "id": str(uuid4()),
            "user_id": self.user_id,
            "session_id": self.session_id,
            "summary": _to_dict(summary),
            "created_at": self._now_iso(),
        }
        self._with_repository(lambda repo: repo.upsert_final_state_block(record))

    def append_reporting(self, summary: Any) -> None:
        record = {
            "id": str(uuid4()),
            "user_id": self.user_id,
            "session_id": self.session_id,
            "summary": _to_dict(summary),
            "created_at": self._now_iso(),
        }
        self._with_repository(lambda repo: repo.upsert_reporting_block(record))

    def append_session(self, record: Any) -> None:
        data = _to_dict(record)
        now = self._now_iso()
        self.session_id = data.get("session_id") or self.session_id
        session_record = {
            "id": self.session_id,
            "user_id": self.user_id,
            "status": "completed",
            "program_start_time": data["program_start_time"],
            "warmup_end_time": data.get("warmup_end_time"),
            "real_start_time": data.get("real_start_time"),
            "actual_camera_end_time": data.get("actual_camera_end_time"),
            "usable_block_end_time": data.get("usable_block_end_time"),
            "discarded_tail_seconds": data.get("discarded_tail_seconds", 0.0),
            "startup_wait_seconds_after_warmup": data.get(
                "startup_wait_seconds_after_warmup", 0.0
            ),
            "official_seconds_requested": data.get("official_seconds_requested", 0.0),
            "sample_fps": data.get("sample_fps", 0.0),
            "frames_read": data.get("frames_read", 0),
            "samples_processed": data.get("samples_processed", 0),
            "face_detected_samples": data.get("face_detected_samples", 0),
            "completed_counts": data.get("completed_counts", {}),
            "created_at": data.get("saved_at") or now,
            "updated_at": now,
        }
        self._with_repository(lambda repo: repo.upsert_session(session_record))

    def read_blocks(self, block_type: str) -> list[Any]:
        types = _load_smartdesk_types()
        StoredBlock = types["StoredBlock"]
        rows = self._read_rows(block_type)
        return [
            StoredBlock(
                block_type=block_type,
                saved_at=row.get("created_at") or self._now_iso(),
                summary=row.get("summary") or row,
            )
            for row in rows
        ]

    def read_sessions(self) -> list[Any]:
        types = _load_smartdesk_types()
        SessionRecord = types["SessionRecord"]
        row = self._with_repository(lambda repo: repo.session_by_id(self.session_id))
        if row is None:
            return []
        return [
            SessionRecord(
                session_id=row["id"],
                saved_at=row.get("updated_at") or row.get("created_at") or self._now_iso(),
                program_start_time=row["program_start_time"],
                warmup_end_time=row.get("warmup_end_time"),
                real_start_time=row.get("real_start_time"),
                actual_camera_end_time=row.get("actual_camera_end_time"),
                usable_block_end_time=row.get("usable_block_end_time"),
                discarded_tail_seconds=row.get("discarded_tail_seconds") or 0.0,
                startup_wait_seconds_after_warmup=row.get(
                    "startup_wait_seconds_after_warmup"
                )
                or 0.0,
                official_seconds_requested=row.get("official_seconds_requested") or 0.0,
                sample_fps=row.get("sample_fps") or 0.0,
                frames_read=row.get("frames_read") or 0,
                samples_processed=row.get("samples_processed") or 0,
                face_detected_samples=row.get("face_detected_samples") or 0,
                completed_counts=row.get("completed_counts") or {},
                storage_dir="sql",
            )
        ]

    def _append_signal_block(
        self,
        block_type: str,
        summary: Any,
        *,
        engagement_label: str | None = None,
        sleepiness_label: str | None = None,
    ) -> None:
        record = {
            "id": str(uuid4()),
            "user_id": self.user_id,
            "session_id": self.session_id,
            "block_type": block_type,
            "summary": _to_dict(summary),
            "engagement_label": engagement_label,
            "sleepiness_label": sleepiness_label,
            "created_at": self._now_iso(),
        }
        self._with_repository(lambda repo: repo.upsert_signal_block(record))

    def _read_rows(self, block_type: str) -> list[dict[str, Any]]:
        if block_type in {"emotion", "engagement", "sleepiness"}:
            rows = self._with_repository(
                lambda repo: repo.signal_blocks_for_session(self.session_id, user_id=self.user_id)
            )
            return [row for row in rows if row.get("block_type") == block_type]
        if block_type == "final_state":
            return self._with_repository(
                lambda repo: repo.final_state_blocks_for_session(
                    self.session_id,
                    user_id=self.user_id,
                )
            )
        if block_type == "reporting":
            return self._with_repository(
                lambda repo: repo.reporting_blocks_for_session(
                    self.session_id,
                    user_id=self.user_id,
                )
            )
        raise ValueError(f"Unknown SmartDesk block type: {block_type}")

    def _with_repository(self, action: Callable[[SmartDeskDetectionRepository], T]) -> T:
        if self.repository is not None:
            return action(self.repository)
        if self.session_factory is None:
            raise RuntimeError("SmartDesk SQL storage has no repository or session factory")
        db = self.session_factory()
        try:
            return action(SmartDeskDetectionRepository(db))
        finally:
            db.close()

    def _now_iso(self) -> str:
        return self.now_factory().isoformat()


def _to_dict(value: Any) -> dict[str, Any]:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return dict(value)
    raise TypeError(f"Unsupported SmartDesk summary type: {type(value)!r}")
