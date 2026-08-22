"""Personal baseline values for landmark-derived head pose features."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


DEFAULT_BASELINE_PATH = Path("data") / "calibration" / "landmark_baseline.json"


@dataclass(frozen=True)
class HeadPoseBaseline:
    """Normal screen-facing head pose for one user/camera setup."""

    yaw: float
    pitch: float
    ear: float | None = None
    saved_at: str | None = None

    @classmethod
    def from_file(cls, path: str | Path = DEFAULT_BASELINE_PATH) -> "HeadPoseBaseline":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            yaw=float(payload["yaw"]),
            pitch=float(payload["pitch"]),
            ear=None if payload.get("ear") is None else float(payload["ear"]),
            saved_at=payload.get("saved_at"),
        )

    def save(self, path: str | Path = DEFAULT_BASELINE_PATH) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(self)
        payload["saved_at"] = datetime.now(UTC).isoformat()
        target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
