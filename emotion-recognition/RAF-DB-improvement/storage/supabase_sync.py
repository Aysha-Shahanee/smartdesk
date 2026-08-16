"""NOT WIRED INTO THE RUNNING APP.

Retained from the standalone research prototype. Nothing in SmartDesk imports
this module: EmotionRecognitionService persists through storage.local_database
into the backend's own SQLite database, and no emotion data leaves the machine.

Kept for reference only. Before importing any of it, note that it uploads
webcam-derived emotion data to a third-party service, so it must not be wired
up without a consent gate equivalent to the one on /api/v1/emotion/start.
"""

from __future__ import annotations

import os
from typing import Any

from storage.pending_queue import PendingQueue


class SupabaseEmotionSync:
    def __init__(
        self,
        pending_queue: PendingQueue,
        table_name: str = "emotion_blocks",
        supabase_url: str | None = None,
        supabase_key: str | None = None,
    ) -> None:
        self.pending_queue = pending_queue
        self.table_name = table_name
        self.supabase_url = supabase_url or os.getenv("SUPABASE_URL")
        self.supabase_key = supabase_key or os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_ANON_KEY")
        self.client = None
        self.disabled_reason = ""
        self.last_error = ""

        if not self.supabase_url or not self.supabase_key:
            self.disabled_reason = "SUPABASE_URL or SUPABASE_KEY is not set"
            return

        try:
            from supabase import create_client
        except ImportError:
            self.disabled_reason = "supabase package is not installed"
            return

        self.client = create_client(self.supabase_url, self.supabase_key)

    @property
    def is_configured(self) -> bool:
        return self.client is not None

    def queue_block(self, record: dict[str, Any]) -> dict[str, Any]:
        self.pending_queue.upsert(record)
        return record

    def upload_record(self, record: dict[str, Any]) -> bool:
        if not self.client:
            self.last_error = self.disabled_reason or "Supabase client is not configured"
            return False

        try:
            self.client.table(self.table_name).upsert(self._to_supabase_row(record)).execute()
        except Exception as exc:
            self.last_error = str(exc)
            return False

        self.last_error = ""
        self.pending_queue.remove(record["id"])
        return True

    def retry_pending_blocks(self) -> int:
        if not self.client:
            self.last_error = self.disabled_reason or "Supabase client is not configured"
            return 0

        uploaded_count = 0
        for record in self.pending_queue.read_all():
            if self.upload_record(record):
                uploaded_count += 1
        return uploaded_count

    def query_records(self, start_time: str, end_time: str, user_id: str | None = None) -> list[dict[str, Any]]:
        if not self.client:
            self.last_error = self.disabled_reason or "Supabase client is not configured"
            return []

        try:
            query = (
                self.client.table(self.table_name)
                .select("*")
                .gte("block_start_time", start_time)
                .lt("block_start_time", end_time)
                .order("block_start_time")
            )
            if user_id:
                query = query.eq("user_id", user_id)
            response = query.execute()
        except Exception as exc:
            self.last_error = str(exc)
            return []

        self.last_error = ""
        return list(response.data or [])

    def query_session_records(self, session_id: str, user_id: str | None = None) -> list[dict[str, Any]]:
        if not self.client:
            self.last_error = self.disabled_reason or "Supabase client is not configured"
            return []

        try:
            query = (
                self.client.table(self.table_name)
                .select("*")
                .eq("session_id", session_id)
                .order("block_start_time")
            )
            if user_id:
                query = query.eq("user_id", user_id)
            response = query.execute()
        except Exception as exc:
            self.last_error = str(exc)
            return []

        self.last_error = ""
        return list(response.data or [])

    def _to_supabase_row(self, record: dict[str, Any]) -> dict[str, Any]:
        scores = record.get("emotion_scores", {})
        return {
            "id": record["id"],
            "user_id": record["user_id"],
            "session_id": record["session_id"],
            "session_start_time": record["session_start_time"],
            "block_start_time": record["block_start_time"],
            "block_end_time": record["block_end_time"],
            "block_type": record["block_type"],
            "duration_minutes": record["duration_minutes"],
            "dominant_emotion": record["dominant_emotion"],
            "happy_score": scores.get("Happy", 0.0),
            "neutral_score": scores.get("Neutral", 0.0),
            "angry_score": scores.get("Angry", 0.0),
            "surprise_score": scores.get("Surprise", 0.0),
            "emotion_scores": scores,
            "processed_frame_count": record["processed_frame_count"],
            "created_at": record["created_at"],
        }
