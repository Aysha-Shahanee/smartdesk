from __future__ import annotations

import os
from typing import Any

from storage.local_storage import LocalEmotionStorage


class SupabaseEmotionSync:
    def __init__(
        self,
        storage: LocalEmotionStorage,
        table_name: str = "emotion_blocks",
        supabase_url: str | None = None,
        supabase_key: str | None = None,
    ) -> None:
        self.storage = storage
        self.table_name = table_name
        self.supabase_url = supabase_url or os.getenv("SUPABASE_URL")
        self.supabase_key = supabase_key or os.getenv("SUPABASE_ANON_KEY")
        self.client = None
        self.disabled_reason = ""

        if not self.supabase_url or not self.supabase_key:
            self.disabled_reason = "SUPABASE_URL or SUPABASE_ANON_KEY is not set"
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

    def upload_record(self, record: dict[str, Any]) -> bool:
        if not self.client:
            return False

        try:
            self.client.table(self.table_name).upsert(self._to_supabase_row(record)).execute()
        except Exception as exc:
            self.storage.update_sync_status(record["id"], synced=False, error=str(exc))
            return False

        self.storage.mark_synced(record["id"])
        return True

    def retry_unsynced(self) -> int:
        if not self.client:
            return 0

        uploaded_count = 0
        for record in self.storage.get_unsynced_records():
            if self.upload_record(record):
                uploaded_count += 1
        return uploaded_count

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

