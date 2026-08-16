"""NOT WIRED INTO THE RUNNING APP.

Retained from the standalone research prototype. Nothing in SmartDesk imports
this module: EmotionRecognitionService persists through storage.local_database
into the backend's own SQLite database, and no emotion data leaves the machine.

Kept for reference only. Before importing any of it, note that it uploads
webcam-derived emotion data to a third-party service, so it must not be wired
up without a consent gate equivalent to the one on /api/v1/emotion/start.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4


def parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class LocalEmotionStorage:
    def __init__(self, output_path: Path, retention_hours: int = 24) -> None:
        self.output_path = Path(output_path)
        self.retention = timedelta(hours=retention_hours)

    def append_record(self, record: dict) -> dict:
        stored_record = dict(record)
        stored_record.setdefault("id", str(uuid4()))
        stored_record.setdefault("synced", False)
        stored_record.setdefault("created_at", datetime.now().astimezone().isoformat())

        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        with self.output_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(stored_record) + "\n")
        return stored_record

    def read_records(self) -> list[dict]:
        if not self.output_path.exists():
            return []

        records = []
        with self.output_path.open("r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return records

    def get_unsynced_records(self) -> list[dict]:
        return [record for record in self.read_records() if not record.get("synced", False)]

    def mark_synced(self, record_id: str) -> None:
        self.update_sync_status(record_id, synced=True)

    def update_sync_status(self, record_id: str, synced: bool, error: str | None = None) -> None:
        records = self.read_records()
        changed = False

        for record in records:
            if record.get("id") == record_id:
                record["synced"] = synced
                record["synced_at"] = datetime.now().astimezone().isoformat() if synced else None
                if error:
                    record["sync_error"] = error
                elif synced:
                    record.pop("sync_error", None)
                changed = True

        if changed:
            self._rewrite_records(records)

    def cleanup_old_records(self, now: datetime | None = None) -> int:
        now = now or datetime.now().astimezone()
        cutoff = now - self.retention
        records = self.read_records()
        kept_records = []

        for record in records:
            timestamp_value = record.get("block_end_time") or record.get("created_at")
            if not timestamp_value:
                kept_records.append(record)
                continue

            try:
                timestamp = parse_datetime(timestamp_value)
            except ValueError:
                kept_records.append(record)
                continue

            if timestamp >= cutoff:
                kept_records.append(record)

        removed_count = len(records) - len(kept_records)
        if removed_count:
            self._rewrite_records(kept_records)
        return removed_count

    def _rewrite_records(self, records: list[dict]) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        if not records:
            if self.output_path.exists():
                self.output_path.unlink()
            return

        temp_path = self.output_path.with_suffix(self.output_path.suffix + ".tmp")
        with temp_path.open("w", encoding="utf-8") as file:
            for record in records:
                file.write(json.dumps(record) + "\n")
        temp_path.replace(self.output_path)

