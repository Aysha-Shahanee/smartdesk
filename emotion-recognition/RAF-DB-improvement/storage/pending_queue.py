from __future__ import annotations

import json
from pathlib import Path


class PendingQueue:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def append(self, record: dict) -> dict:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record) + "\n")
        return record

    def upsert(self, record: dict) -> dict:
        record_id = record["id"]
        records = [item for item in self.read_all() if item.get("id") != record_id]
        records.append(record)
        self._rewrite(records)
        return record

    def read_all(self) -> list[dict]:
        if not self.path.exists():
            return []

        records = []
        with self.path.open("r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return records

    def remove(self, record_id: str) -> None:
        records = [record for record in self.read_all() if record.get("id") != record_id]
        self._rewrite(records)

    def remove_many(self, record_ids: set[str]) -> None:
        if not record_ids:
            return
        records = [record for record in self.read_all() if record.get("id") not in record_ids]
        self._rewrite(records)

    def _rewrite(self, records: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not records:
            if self.path.exists():
                self.path.unlink()
            return

        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        with temp_path.open("w", encoding="utf-8") as file:
            for record in records:
                file.write(json.dumps(record) + "\n")
        temp_path.replace(self.path)

