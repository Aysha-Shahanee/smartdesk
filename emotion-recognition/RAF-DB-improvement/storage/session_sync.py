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


class SupabaseSessionSync:
    def __init__(
        self,
        pending_queue: PendingQueue,
        table_name: str = "emotion_sessions",
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

    def queue_session(self, record: dict[str, Any]) -> dict[str, Any]:
        self.pending_queue.upsert(record)
        return record

    def upload_session(self, record: dict[str, Any]) -> bool:
        if not self.client:
            self.last_error = self.disabled_reason or "Supabase client is not configured"
            return False

        try:
            self.client.table(self.table_name).upsert(record).execute()
        except Exception as exc:
            self.last_error = str(exc)
            return False

        self.last_error = ""
        self.pending_queue.remove(record["id"])
        return True

    def retry_pending_sessions(self) -> int:
        if not self.client:
            self.last_error = self.disabled_reason or "Supabase client is not configured"
            return 0

        uploaded_count = 0
        for record in self.pending_queue.read_all():
            if self.upload_session(record):
                uploaded_count += 1
        return uploaded_count

    def query_current_session(self, session_id: str) -> dict[str, Any] | None:
        if not self.client:
            self.last_error = self.disabled_reason or "Supabase client is not configured"
            return None

        try:
            response = self.client.table(self.table_name).select("*").eq("id", session_id).limit(1).execute()
        except Exception as exc:
            self.last_error = str(exc)
            return None

        self.last_error = ""
        rows = response.data or []
        return rows[0] if rows else None
