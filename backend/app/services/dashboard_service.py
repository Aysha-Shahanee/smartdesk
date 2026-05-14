"""Dashboard aggregation service — Phase 9.

Implements the query and aggregation logic for all five dashboard panels:
  - OS summary   → OSDashboardResponse
  - IDE summary  → IDEDashboardResponse
  - Browser summary → BrowserDashboardResponse
  - Timeline     → TimelineDashboardResponse
  - Sessions     → SessionsDashboardResponse

Each method receives a SQLAlchemy ``db`` session and ISO 8601 ``from_iso``/
``to_iso`` boundary strings so the same service works for day, week, and
custom date-range queries.
"""

from collections import defaultdict
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.db import BrowserSessionRecord
from app.models.db import OSSessionRecord
from app.models.db import VSCodeSessionRecord
from app.models.db import WorkPeriodRecord
from app.models.schemas.dashboard import (
    AppDuration,
    BrowserDashboardResponse,
    CategoryDuration,
    IDEDashboardResponse,
    NamedDuration,
    OSDashboardResponse,
    SessionsDashboardResponse,
    SessionSummary,
    TimelineDashboardResponse,
    WorkPeriodSummary,
)
from app.repositories.browser_session_repository import BrowserSessionRepository
from app.repositories.os_session_repository import OSSessionRepository
from app.repositories.vscode_session_repository import VSCodeSessionRepository
from app.repositories.work_period_repository import WorkPeriodRepository

_os_repo = OSSessionRepository()
_vscode_repo = VSCodeSessionRepository()
_browser_repo = BrowserSessionRepository()
_work_repo = WorkPeriodRepository()

# How many items to return in "top N" lists.
TOP_N = 10


class DashboardService:

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def get_os_summary(
        self,
        db: Session,
        user_id: str,
        from_iso: str,
        to_iso: str,
    ) -> OSDashboardResponse:
        rows = _os_repo.get_completed_sessions_db(db, user_id, from_iso, to_iso)

        active = [r for r in rows if r.state == "active"]
        idle = [r for r in rows if r.state == "idle"]
        locked = [r for r in rows if r.state == "locked"]

        return OSDashboardResponse(
            active_time_sec=self._sum_duration(active),
            idle_time_sec=self._sum_duration(idle),
            locked_time_sec=self._sum_duration(locked),
            top_apps=self._top_apps(active),
            category_breakdown=self._category_breakdown(active),
        )

    def get_ide_summary(
        self,
        db: Session,
        user_id: str,
        from_iso: str,
        to_iso: str,
    ) -> IDEDashboardResponse:
        rows = _vscode_repo.get_foreground_sessions_db(db, user_id, from_iso, to_iso)

        return IDEDashboardResponse(
            coding_time_sec=sum(
                max(0, (r.duration_sec or 0) - (r.idle_sec or 0)) for r in rows
            ),
            idle_sec=sum(r.idle_sec or 0 for r in rows),
            edits=sum(r.edit_count or 0 for r in rows),
            saves=sum(r.save_count or 0 for r in rows),
            lines_added=sum(r.lines_added or 0 for r in rows),
            lines_deleted=sum(r.lines_deleted or 0 for r in rows),
            terminal_commands=sum(r.terminal_command_count or 0 for r in rows),
            debug_runs=sum(r.debug_run_count or 0 for r in rows),
            top_languages=self._top_by_field(rows, "active_language"),
            top_projects=self._top_by_field(rows, "workspace_name"),
        )

    def get_browser_summary(
        self,
        db: Session,
        user_id: str,
        from_iso: str,
        to_iso: str,
    ) -> BrowserDashboardResponse:
        rows = _browser_repo.get_foreground_sessions_db(
            db, user_id, from_iso, to_iso, min_duration_sec=3
        )

        return BrowserDashboardResponse(
            browser_active_time_sec=self._sum_duration(rows),
            productive_time_sec=self._sum_duration(
                [r for r in rows if r.category == "Focused"]
            ),
            distracting_time_sec=self._sum_duration(
                [r for r in rows if r.category == "Distracted"]
            ),
            neutral_time_sec=self._sum_duration(
                [r for r in rows if r.category == "Neutral"]
            ),
            communication_time_sec=self._sum_duration(
                [r for r in rows if r.category == "Communication"]
            ),
            top_domains=self._top_by_field(rows, "domain"),
        )

    def get_timeline(
        self,
        db: Session,
        user_id: str,
        from_iso: str,
        to_iso: str,
    ) -> TimelineDashboardResponse:
        periods = _work_repo.get_periods_db(db, user_id, from_iso, to_iso)

        summaries = [
            WorkPeriodSummary(
                id=p.id,
                period_start=datetime.fromisoformat(p.period_start),
                period_end=(
                    datetime.fromisoformat(p.period_end) if p.period_end else None
                ),
                duration_sec=p.duration_sec,
                primary_source=p.primary_source,
                has_os_data=bool(p.has_os_data),
                has_vscode_data=bool(p.has_vscode_data),
                has_browser_data=bool(p.has_browser_data),
                has_calendar_data=bool(p.has_calendar_data),
            )
            for p in periods
        ]

        return TimelineDashboardResponse(work_periods=summaries)

    def get_sessions(
        self,
        db: Session,
        user_id: str,
        from_iso: str,
        to_iso: str,
    ) -> SessionsDashboardResponse:
        """Return a flat list of all sessions across all three sources."""
        results: list[SessionSummary] = []

        for row in _os_repo.get_completed_sessions_db(db, user_id, from_iso, to_iso):
            results.append(
                SessionSummary(
                    id=row.id,
                    source="os",
                    title=row.window_title or row.app_name,
                    started_at=datetime.fromisoformat(row.session_start),
                    ended_at=(
                        datetime.fromisoformat(row.session_end)
                        if row.session_end
                        else None
                    ),
                    duration_sec=row.duration_sec,
                    is_foreground=None,
                )
            )

        for row in _vscode_repo.get_all_sessions_db(db, user_id, from_iso, to_iso):
            results.append(
                SessionSummary(
                    id=row.id,
                    source="vscode",
                    title=row.active_file_name or row.workspace_name,
                    started_at=datetime.fromisoformat(row.session_start),
                    ended_at=(
                        datetime.fromisoformat(row.session_end)
                        if row.session_end
                        else None
                    ),
                    duration_sec=row.duration_sec,
                    is_foreground=bool(row.is_foreground),
                )
            )

        for row in _browser_repo.get_all_sessions_db(db, user_id, from_iso, to_iso):
            results.append(
                SessionSummary(
                    id=row.id,
                    source="browser",
                    title=row.title or row.domain,
                    started_at=datetime.fromisoformat(row.session_start),
                    ended_at=(
                        datetime.fromisoformat(row.session_end)
                        if row.session_end
                        else None
                    ),
                    duration_sec=row.duration_sec,
                    is_foreground=bool(row.is_foreground),
                )
            )

        # Sort chronologically
        results.sort(key=lambda s: s.started_at)
        return SessionsDashboardResponse(sessions=results)

    # ------------------------------------------------------------------ #
    # Aggregation helpers                                                  #
    # ------------------------------------------------------------------ #

    def _sum_duration(self, rows: list) -> int:
        return sum(r.duration_sec or 0 for r in rows)

    def _top_apps(self, rows: list[OSSessionRecord]) -> list[AppDuration]:
        totals: dict[str, dict] = defaultdict(lambda: {"seconds": 0, "category": None})
        for r in rows:
            key = r.app_name or "Unknown"
            totals[key]["seconds"] += r.duration_sec or 0
            totals[key]["category"] = r.app_category
        return [
            AppDuration(name=name, seconds=data["seconds"], category=data["category"])
            for name, data in sorted(
                totals.items(), key=lambda x: x[1]["seconds"], reverse=True
            )
        ][:TOP_N]

    def _category_breakdown(
        self, rows: list[OSSessionRecord]
    ) -> list[CategoryDuration]:
        totals: dict[str, int] = defaultdict(int)
        for r in rows:
            cat = r.app_category or "Other"
            totals[cat] += r.duration_sec or 0
        return [
            CategoryDuration(category=cat, seconds=sec)
            for cat, sec in sorted(totals.items(), key=lambda x: x[1], reverse=True)
        ]

    def _top_by_field(self, rows: list, field: str) -> list[NamedDuration]:
        totals: dict[str, int] = defaultdict(int)
        for r in rows:
            value = getattr(r, field, None)
            if value:
                totals[value] += r.duration_sec or 0
        return [
            NamedDuration(name=name, seconds=sec)
            for name, sec in sorted(totals.items(), key=lambda x: x[1], reverse=True)
        ][:TOP_N]
