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

import json
from collections import defaultdict
from datetime import timedelta
from typing import Callable

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.time import local_now
from app.core.time import local_now_iso
from app.core.time import parse_iso
from app.models.db import CalendarEventRecord
from app.models.db import BrowserSessionRecord
from app.models.db import IDESessionRecord
from app.models.db import OSSessionRecord
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
from app.repositories.ide_session_repository import IDESessionRepository
from app.repositories.os_session_repository import OSSessionRepository
from app.repositories.work_period_repository import WorkPeriodRepository

_os_repo = OSSessionRepository()
_ide_repo = IDESessionRepository()
_browser_repo = BrowserSessionRepository()
_work_repo = WorkPeriodRepository()

# How many items to return in "top N" lists.
TOP_N = 10

# A collection layer is "ok" when its newest row was updated within this window.
HEALTH_WINDOW_SEC = 15 * 60
# How many recent rows the monitoring overview shows per layer.
RECENT_N = 5


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

        return OSDashboardResponse(
            active_time_sec=self._sum_duration(active),
            idle_time_sec=self._sum_duration(idle),
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
        rows = _ide_repo.get_foreground_sessions_db(db, user_id, from_iso, to_iso)

        return IDEDashboardResponse(
            coding_time_sec=sum(self._ide_active_sec(r) for r in rows),
            idle_sec=sum(r.idle_sec or 0 for r in rows),
            edits=sum(r.edit_count or 0 for r in rows),
            saves=sum(r.save_count or 0 for r in rows),
            lines_added=sum(r.lines_added or 0 for r in rows),
            lines_deleted=sum(r.lines_deleted or 0 for r in rows),
            files_modified=self._distinct_edited_files(
                # Background sessions included on purpose: an AI agent editing
                # while the IDE window is blurred still modifies files, and the
                # foreground-only list would undercount them.
                _ide_repo.get_all_sessions_db(db, user_id, from_iso, to_iso)
            ),
            # Weighted by active coding time, not by raw session duration, so
            # these lists add up to ``coding_time_sec`` above.
            #
            # They used to sum ``duration_sec``, which counts every second the
            # editor was the foreground window — including the ones the IDE
            # itself recorded as idle. An IDE session left open across a
            # suspend is emitted as one row with ``idle_sec == duration_sec``:
            # on 2026-08-10 a single 00:52–04:45 row contributed 14026 s of
            # "python" while the machine was asleep, so the language breakdown
            # read 5.97 h under a Coding Time tile reading 1.25 h.
            top_languages=self._top_by_field(
                rows, "active_language", weight=self._ide_active_sec
            ),
            top_projects=self._top_by_field(
                rows, "workspace_name", weight=self._ide_active_sec
            ),
        )

    @staticmethod
    def _ide_active_sec(row: IDESessionRecord) -> int:
        """Seconds of an IDE session spent actually editing.

        ``duration_sec`` is wall-clock time the editor held focus; ``idle_sec``
        is the part of it the extension saw no editor activity for. Only the
        difference is coding time.
        """
        return max(0, (row.duration_sec or 0) - (row.idle_sec or 0))

    @staticmethod
    def _distinct_edited_files(rows: list[IDESessionRecord]) -> int:
        """Count unique file paths across every session's ``edited_files_json``.

        Summing ``edited_file_count`` instead would multiply-count any file
        touched in more than one session, which is the common case for a file
        edited across a lunch break.
        """
        paths: set[str] = set()
        for row in rows:
            if not row.edited_files_json:
                continue
            try:
                entries = json.loads(row.edited_files_json)
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(entries, list):
                continue
            for entry in entries:
                path = entry.get("path") if isinstance(entry, dict) else None
                if path:
                    paths.add(path)
        return len(paths)

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
                period_start=parse_iso(p.period_start),
                period_end=(
                    parse_iso(p.period_end) if p.period_end else None
                ),
                duration_sec=p.duration_sec,
                primary_source=p.primary_source,
                has_os_data=bool(p.has_os_data),
                has_ide_data=bool(p.has_ide_data),
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
                    started_at=parse_iso(row.session_start),
                    ended_at=(
                        parse_iso(row.session_end)
                        if row.session_end
                        else None
                    ),
                    duration_sec=row.duration_sec,
                    is_foreground=None,
                )
            )

        for row in _ide_repo.get_all_sessions_db(db, user_id, from_iso, to_iso):
            results.append(
                SessionSummary(
                    id=row.id,
                    source="ide",
                    title=row.active_file_name or row.workspace_name,
                    started_at=parse_iso(row.session_start),
                    ended_at=(
                        parse_iso(row.session_end)
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
                    started_at=parse_iso(row.session_start),
                    ended_at=(
                        parse_iso(row.session_end)
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

    def get_overview(self, db: Session, user_id: str) -> dict:
        """Monitoring overview: per-layer health, totals, and recent rows.

        Used by the small health-check dashboard at /dashboard/ui to verify
        all four collection layers are actually receiving data.
        """
        from app.services.calendar_service import CalendarService

        def layer(Model, recent_fields) -> dict:
            total = db.query(Model).filter(Model.user_id == user_id).count()
            open_count = (
                db.query(Model)
                .filter(Model.user_id == user_id, Model.session_end.is_(None))
                .count()
            )
            # Newest N rows, displayed in ascending time order.
            rows = (
                db.query(Model)
                .filter(Model.user_id == user_id)
                .order_by(Model.updated_at.desc())
                .limit(RECENT_N)
                .all()
            )
            last_at = rows[0].updated_at if rows else None
            rows.sort(key=lambda r: r.session_start or "")
            return {
                "total": total,
                "open": open_count,
                "last_event_at": last_at,
                "status": self._health(last_at),
                "recent": [
                    {field: getattr(r, field, None) for field in recent_fields}
                    for r in rows
                ],
            }

        os_layer = layer(
            OSSessionRecord,
            ("app_name", "app_category", "window_title", "state",
             "session_start", "session_end", "duration_sec"),
        )
        ide_layer = layer(
            IDESessionRecord,
            ("ide_name", "workspace_name", "active_file_name", "active_language",
             "is_foreground", "collection_reason", "edit_count",
             "session_start", "session_end", "duration_sec"),
        )
        browser_layer = layer(
            BrowserSessionRecord,
            ("browser_name", "domain", "title", "category", "is_foreground",
             "session_start", "session_end", "duration_sec"),
        )

        calendar_service = CalendarService()
        cal_status = calendar_service.status(user_id, db)
        # Upcoming/nearest events first: newest-synced window, ascending start.
        cal_rows = (
            db.query(CalendarEventRecord)
            .filter(CalendarEventRecord.user_id == user_id)
            .order_by(CalendarEventRecord.start_time.desc())
            .limit(RECENT_N)
            .all()
        )
        cal_rows.reverse()
        calendar_layer = {
            "total": cal_status["event_count"],
            "configured": cal_status["configured"],
            "connected": cal_status["connected"],
            "last_sync": cal_status["last_sync"],
            "needs_reconnect": cal_status.get("needs_reconnect", False),
            "last_error": cal_status.get("last_error"),
            # A token that Google no longer honours must not read as "ok" just
            # because a successful sync happened before it expired — that is
            # precisely how the last outage stayed invisible on this page.
            "status": (
                "needs_reconnect" if cal_status.get("needs_reconnect")
                else "ok" if cal_status["connected"] and cal_status["last_sync"]
                else "not_connected" if not cal_status["connected"]
                else "no_data"
            ),
            "recent": [
                {
                    "title": r.title,
                    "start_time": r.start_time,
                    "end_time": r.end_time,
                    "status": r.status,
                    "is_all_day": bool(r.is_all_day),
                }
                for r in cal_rows
            ],
        }

        return {
            "generated_at": local_now_iso(),
            "timezone": settings.TIMEZONE,
            "device_id": settings.DEVICE_ID,
            "user_id": user_id,
            "layers": {
                "os": os_layer,
                "ide": ide_layer,
                "browser": browser_layer,
                "calendar": calendar_layer,
            },
        }

    def _health(self, last_iso: str | None) -> str:
        if not last_iso:
            return "no_data"
        cutoff = local_now() - timedelta(seconds=HEALTH_WINDOW_SEC)
        return "ok" if parse_iso(last_iso) >= cutoff else "stale"

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

    def _top_by_field(
        self,
        rows: list,
        field: str,
        weight: Callable[[object], int] | None = None,
    ) -> list[NamedDuration]:
        """Top-N values of ``field``, ranked by time.

        ``weight`` chooses what "time" means for a row; it defaults to the
        session's whole duration. Sources that distinguish active from idle
        time pass their own so the breakdown reconciles with the headline
        figure shown above it.
        """
        totals: dict[str, int] = defaultdict(int)
        for r in rows:
            value = getattr(r, field, None)
            if value:
                totals[value] += weight(r) if weight else (r.duration_sec or 0)
        return [
            NamedDuration(name=name, seconds=sec)
            # A value can collect only idle sessions and weigh nothing; charting
            # it draws an empty bar with a "0s" label.
            for name, sec in sorted(totals.items(), key=lambda x: x[1], reverse=True)
            if sec > 0
        ][:TOP_N]
