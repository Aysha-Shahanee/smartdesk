"""Task-specific human active time derived from persisted SmartDesk activity."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from app.core.time import ensure_aware, parse_iso
from app.models.db import ActivitySegmentRecord, IDESessionRecord


# Real UTC offsets run from -12:00 to +14:00. Padding the SQL window by more
# than the widest of them guarantees no candidate segment is filtered out by a
# zone the stored value has already forgotten.
_ZONE_PADDING = timedelta(hours=15)


@dataclass(frozen=True)
class TaskTimeSpentResult:
    task_active_seconds: int | None
    time_spent_hours: float | None
    time_attribution_status: str
    calculated_through: str
    data_status: str

    def to_dict(self) -> dict:
        return asdict(self)


class GitHubTaskTimeSpentService:
    """Aggregate non-overlapping human-active IDE intervals for a lifecycle."""

    _BRANCH_ISSUE_PATTERNS = (
        re.compile(r"(?:^|/)issue[-/](\d+)(?=$|[-/])", re.IGNORECASE),
        re.compile(r"(?:^|/)gh[-/](\d+)(?=$|[-/])", re.IGNORECASE),
    )

    def __init__(self, db: Session, now_provider=None):
        self.db = db
        self.now_provider = now_provider or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def normalize_repository(value: str | None) -> str | None:
        if not value or "/" not in value:
            return None
        owner, repository = value.strip().strip("/").split("/", 1)
        if not owner or not repository or "/" in repository:
            return None
        return f"{owner}/{repository.removesuffix('.git')}".lower()

    @classmethod
    def extract_issue_number_from_branch_name(cls, branch_name: str | None) -> int | None:
        if not branch_name:
            return None
        for pattern in cls._BRANCH_ISSUE_PATTERNS:
            match = pattern.search(branch_name.strip())
            if match:
                return int(match.group(1))
        return None

    @staticmethod
    def merge_intervals(intervals: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
        if not intervals:
            return []
        ordered = sorted(intervals, key=lambda interval: interval[0])
        merged = [ordered[0]]
        for start, end in ordered[1:]:
            previous_start, previous_end = merged[-1]
            if start <= previous_end:
                merged[-1] = (previous_start, max(previous_end, end))
            else:
                merged.append((start, end))
        return merged

    @staticmethod
    def stored_segment_time_utc(value: datetime, timezone_name: str | None) -> datetime:
        """Restore the zone SQLite drops from activity-segment datetimes."""
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc)
        try:
            stored_timezone = ZoneInfo(timezone_name) if timezone_name else timezone.utc
        except ZoneInfoNotFoundError:
            stored_timezone = timezone.utc
        return value.replace(tzinfo=stored_timezone).astimezone(timezone.utc)

    def calculate(self, lifecycle: dict, active_lifecycles: list[dict]) -> TaskTimeSpentResult:
        now = ensure_aware(self.now_provider()).astimezone(timezone.utc)
        calculated_through = now.isoformat().replace("+00:00", "Z")
        repository = self.normalize_repository(lifecycle.get("repository"))
        if repository is None:
            return self._unknown("no_match", calculated_through, "unavailable")

        same_repository = [
            task for task in active_lifecycles
            if self.normalize_repository(task.get("repository")) == repository
        ]
        lifecycle_id = lifecycle.get("collector_lifecycle_id")
        if not any(task.get("collector_lifecycle_id") == lifecycle_id for task in same_repository):
            same_repository.append(lifecycle)
        lifecycle_start = parse_iso(lifecycle["started_at"]).astimezone(timezone.utc)
        completed_at = lifecycle.get("completed_at")
        lifecycle_end = parse_iso(completed_at).astimezone(timezone.utc) if completed_at else now
        if lifecycle_end <= lifecycle_start:
            return TaskTimeSpentResult(0, 0.0, "repository_match", calculated_through, "complete")

        rows = (
            self.db.query(ActivitySegmentRecord, IDESessionRecord)
            .join(IDESessionRecord, ActivitySegmentRecord.ide_session_id == IDESessionRecord.id)
            .filter(
                ActivitySegmentRecord.user_id == lifecycle.get("smartdesk_user_id", lifecycle.get("user_id")),
                # Segment times come back from SQLite without their zone, which
                # is why stored_segment_time_utc has to reconstruct it below. So
                # the window can only be narrowed here, not decided: pad by the
                # widest real UTC offset and let the exact comparison stay in
                # Python. That still drops everything outside the lifecycle,
                # which is the whole table on any account older than a day.
                ActivitySegmentRecord.end_time_utc >= lifecycle_start - _ZONE_PADDING,
                ActivitySegmentRecord.start_time_utc <= lifecycle_end + _ZONE_PADDING,
            )
            .all()
        )

        saw_repository_context = False
        saw_matching_repository = False
        saw_missing_repository = False
        saw_resolved_branch = False
        saw_ambiguous_branch = False
        used_repository_match = False
        used_branch_match = False
        intervals: list[tuple[datetime, datetime]] = []
        for segment, ide in rows:
            segment_start = self.stored_segment_time_utc(
                segment.start_time_utc, segment.timezone_name
            )
            segment_end = self.stored_segment_time_utc(
                segment.end_time_utc, segment.timezone_name
            )
            if segment_end <= lifecycle_start or segment_start >= lifecycle_end:
                continue
            ide_repository = self.normalize_repository(ide.repository)
            if ide_repository is None:
                saw_missing_repository = True
                continue
            saw_repository_context = True
            if ide_repository != repository:
                continue
            saw_matching_repository = True
            if (
                segment.state != "active"
                or not bool(ide.is_foreground)
                or ide.collection_reason == "background_ai"
            ):
                continue
            start = max(segment_start, lifecycle_start)
            end = min(segment_end, lifecycle_end)
            if end <= start:
                continue

            boundaries = {start, end}
            for task in same_repository:
                task_start = parse_iso(task["started_at"]).astimezone(timezone.utc)
                task_completed_at = task.get("completed_at")
                task_end = (
                    parse_iso(task_completed_at).astimezone(timezone.utc)
                    if task_completed_at else None
                )
                if start < task_start < end:
                    boundaries.add(task_start)
                if task_end is not None and start < task_end < end:
                    boundaries.add(task_end)

            ordered_boundaries = sorted(boundaries)
            for piece_start, piece_end in zip(ordered_boundaries, ordered_boundaries[1:]):
                active_for_piece = []
                for task in same_repository:
                    task_start = parse_iso(task["started_at"]).astimezone(timezone.utc)
                    task_completed_at = task.get("completed_at")
                    task_end = (
                        parse_iso(task_completed_at).astimezone(timezone.utc)
                        if task_completed_at else None
                    )
                    if task_start <= piece_start and (task_end is None or task_end > piece_start):
                        active_for_piece.append(task)

                if len(active_for_piece) == 1:
                    if active_for_piece[0].get("collector_lifecycle_id") == lifecycle.get("collector_lifecycle_id"):
                        intervals.append((piece_start, piece_end))
                        used_repository_match = True
                    continue

                branch_issue_number = self.extract_issue_number_from_branch_name(ide.git_branch)
                matching_lifecycles = [
                    task for task in active_for_piece
                    if task.get("issue_number") is not None
                    and task.get("issue_number") == branch_issue_number
                ]
                if branch_issue_number is None or len(matching_lifecycles) != 1:
                    saw_ambiguous_branch = True
                    continue
                saw_resolved_branch = True
                if matching_lifecycles[0].get("collector_lifecycle_id") == lifecycle.get("collector_lifecycle_id"):
                    intervals.append((piece_start, piece_end))
                    used_branch_match = True

        if not saw_matching_repository:
            data_status = "partial" if saw_missing_repository or saw_repository_context else "unavailable"
            return self._unknown("no_match", calculated_through, data_status)

        if not intervals and saw_ambiguous_branch and not saw_resolved_branch:
            return self._unknown("ambiguous", calculated_through, "unavailable")

        seconds = int(sum((end - start).total_seconds() for start, end in self.merge_intervals(intervals)))
        return TaskTimeSpentResult(
            seconds,
            seconds / 3600,
            "branch_match" if used_branch_match or (saw_resolved_branch and not used_repository_match)
            else "repository_match",
            calculated_through,
            "complete",
        )

    @staticmethod
    def _unknown(status: str, calculated_through: str, data_status: str) -> TaskTimeSpentResult:
        return TaskTimeSpentResult(None, None, status, calculated_through, data_status)
