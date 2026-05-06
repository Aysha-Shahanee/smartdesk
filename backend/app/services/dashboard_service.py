"""
Dashboard business logic — aggregation layer for all panels.
Routes call this service; this service calls repositories.
"""

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.db_models import (
    OSMinuteWindowRecord,
    IDEMinuteWindowRecord,
    BrowserMinuteWindowRecord,
    ActivityTimelineIndex,
)
from app.models.dashboard import (
    AppUsage,
    CategoryUsage,
    OSDashboardResponse,
    IDEDashboardResponse,
    BrowserDashboardResponse,
    SessionEntry,
    SessionsResponse,
)

logger = logging.getLogger("smartdesk.service.dashboard")


class DashboardService:
    def __init__(self, db: Session | None = None):
        self.db = db
        self._owns_session = db is None

    def _get_db(self) -> Session:
        return self.db or SessionLocal()

    def get_os_summary(self, user_id: str, from_dt: str, to_dt: str) -> OSDashboardResponse:
        db = self._get_db()
        try:
            rows = (
                db.query(OSMinuteWindowRecord)
                .filter(
                    OSMinuteWindowRecord.user_id == user_id,
                    OSMinuteWindowRecord.window_start >= from_dt,
                    OSMinuteWindowRecord.window_end <= to_dt,
                )
                .all()
            )

            active_time = sum(r.active_time_sec or 0 for r in rows)
            idle_time = sum(r.idle_time_sec or 0 for r in rows)
            locked_time = sum(r.locked_time_sec or 0 for r in rows)

            # Aggregate app durations from JSON data
            app_totals = defaultdict(int)
            category_totals = defaultdict(int)

            for r in rows:
                if r.active_app_durations_json:
                    try:
                        durations = json.loads(r.active_app_durations_json)
                        for app, secs in durations.items():
                            app_totals[app] += int(float(secs))
                    except (json.JSONDecodeError, ValueError):
                        pass

                if r.category_durations_json:
                    try:
                        categories = json.loads(r.category_durations_json)
                        for cat, secs in categories.items():
                            category_totals[cat] += int(float(secs))
                    except (json.JSONDecodeError, ValueError):
                        pass

            top_apps = sorted(
                [AppUsage(name=k, seconds=v) for k, v in app_totals.items()],
                key=lambda x: x.seconds,
                reverse=True,
            )[:10]

            category_breakdown = sorted(
                [CategoryUsage(category=k, seconds=v) for k, v in category_totals.items()],
                key=lambda x: x.seconds,
                reverse=True,
            )

            return OSDashboardResponse(
                active_time_sec=active_time,
                idle_time_sec=idle_time,
                locked_time_sec=locked_time,
                top_apps=top_apps,
                category_breakdown=category_breakdown,
            )
        finally:
            if self._owns_session:
                db.close()

    def get_ide_summary(self, user_id: str, from_dt: str, to_dt: str) -> IDEDashboardResponse:
        db = self._get_db()
        try:
            rows = (
                db.query(IDEMinuteWindowRecord)
                .filter(
                    IDEMinuteWindowRecord.user_id == user_id,
                    IDEMinuteWindowRecord.window_start >= from_dt,
                    IDEMinuteWindowRecord.window_end <= to_dt,
                )
                .all()
            )

            coding_time = sum(r.active_editor_sec or 0 for r in rows)
            idle_sec = sum(r.idle_sec or 0 for r in rows)
            edits = sum(r.edit_count or 0 for r in rows)
            saves = sum(r.save_count or 0 for r in rows)
            terminal_commands = sum(r.terminal_command_count or 0 for r in rows)
            debug_runs = sum(r.debug_run_count or 0 for r in rows)
            lines_added = sum(r.lines_added or 0 for r in rows)
            lines_deleted = sum(r.lines_deleted or 0 for r in rows)

            # Aggregate by language
            lang_totals = defaultdict(int)
            for r in rows:
                if r.active_language:
                    lang_totals[r.active_language] += (r.active_editor_sec or 0)

            top_languages = sorted(
                [AppUsage(name=k, seconds=v) for k, v in lang_totals.items()],
                key=lambda x: x.seconds,
                reverse=True,
            )[:10]

            # Aggregate by workspace/project
            project_totals = defaultdict(int)
            for r in rows:
                name = r.workspace_name or "unknown"
                project_totals[name] += (r.active_editor_sec or 0)

            top_projects = sorted(
                [AppUsage(name=k, seconds=v) for k, v in project_totals.items()],
                key=lambda x: x.seconds,
                reverse=True,
            )[:10]

            return IDEDashboardResponse(
                coding_time_sec=coding_time,
                idle_sec=idle_sec,
                edits=edits,
                saves=saves,
                terminal_commands=terminal_commands,
                debug_runs=debug_runs,
                lines_added=lines_added,
                lines_deleted=lines_deleted,
                top_languages=top_languages,
                top_projects=top_projects,
            )
        finally:
            if self._owns_session:
                db.close()

    def get_browser_summary(self, user_id: str, from_dt: str, to_dt: str) -> BrowserDashboardResponse:
        db = self._get_db()
        try:
            rows = (
                db.query(BrowserMinuteWindowRecord)
                .filter(
                    BrowserMinuteWindowRecord.user_id == user_id,
                    BrowserMinuteWindowRecord.window_start >= from_dt,
                    BrowserMinuteWindowRecord.window_end <= to_dt,
                )
                .all()
            )

            browser_active = sum(r.browser_active_time_sec or 0 for r in rows)
            productive = sum(r.productive_time_sec or 0 for r in rows)
            distracting = sum(r.distracting_time_sec or 0 for r in rows)
            neutral = sum(r.neutral_time_sec or 0 for r in rows)

            # Aggregate by domain
            domain_totals = defaultdict(int)
            for r in rows:
                if r.active_tab_domain:
                    domain_totals[r.active_tab_domain] += (r.browser_active_time_sec or 0)

            top_domains = sorted(
                [AppUsage(name=k, seconds=v) for k, v in domain_totals.items()],
                key=lambda x: x.seconds,
                reverse=True,
            )[:10]

            return BrowserDashboardResponse(
                browser_active_time_sec=browser_active,
                productive_time_sec=productive,
                distracting_time_sec=distracting,
                neutral_time_sec=neutral,
                top_domains=top_domains,
            )
        finally:
            if self._owns_session:
                db.close()

    def get_sessions(self, user_id: str, from_dt: str, to_dt: str) -> SessionsResponse:
        db = self._get_db()
        try:
            rows = (
                db.query(ActivityTimelineIndex)
                .filter(
                    ActivityTimelineIndex.user_id == user_id,
                    ActivityTimelineIndex.window_start >= from_dt,
                    ActivityTimelineIndex.window_end <= to_dt,
                )
                .order_by(ActivityTimelineIndex.window_start)
                .all()
            )

            sessions = [
                SessionEntry(
                    window_start=r.window_start,
                    window_end=r.window_end,
                    foreground_source=r.foreground_source,
                    foreground_app=r.foreground_app,
                    foreground_category=r.foreground_category,
                    has_os=r.has_os_data or False,
                    has_ide=r.has_ide_data or False,
                    has_browser=r.has_browser_data or False,
                )
                for r in rows
            ]

            return SessionsResponse(sessions=sessions)
        finally:
            if self._owns_session:
                db.close()
