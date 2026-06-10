import json
from datetime import datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.time import ensure_aware, to_utc
from app.models.db import BrowserSessionRecord
from app.models.db import OSSessionRecord
from app.models.db import VSCodeSessionRecord
from app.models.schemas import BrowserEventPayload
from app.models.schemas import BrowserEventType
from app.models.schemas import IngestEventResponse
from app.models.schemas import OSEventPayload
from app.models.schemas import OSEventType
from app.models.schemas import VSCodeEventPayload
from app.models.schemas import VSCodeEventType


class SessionCoordinator:
    def handle_os_event(self, payload: OSEventPayload, db: Session) -> IngestEventResponse:
        if payload.event == OSEventType.FOCUSED:
            self._require(payload.app_name, "app_name is required for focused OS events")
            self._close_current_os_session(payload.user_id, payload.timestamp, "next_event", db)
            session = self._open_os_session(payload, db)
            self._update_foreground_flags(payload, db)
            db.commit()
            return IngestEventResponse(status="opened", session_id=session.id)

        if payload.event == OSEventType.BLURRED:
            return IngestEventResponse(status="ignored", accepted=True)

        if payload.event in {
            OSEventType.IDLE_START,
            OSEventType.IDLE_END,
            OSEventType.LOCKED,
            OSEventType.UNLOCKED,
        }:
            session = self._mark_current_os_state(payload, db)
            db.commit()
            return IngestEventResponse(
                status="state_updated",
                session_id=session.id if session else None,
            )

        if payload.event in {OSEventType.SUSPEND, OSEventType.SHUTDOWN}:
            closed_by = payload.event.value
            session = self._close_current_os_session(payload.user_id, payload.timestamp, closed_by, db)
            self._close_all_open_extension_sessions(payload.user_id, payload.timestamp, closed_by, db)
            db.commit()
            return IngestEventResponse(
                status="closed_by_os_signal",
                session_id=session.id if session else None,
            )

        return IngestEventResponse(status="ignored", accepted=True)

    def handle_vscode_event(
        self, payload: VSCodeEventPayload, db: Session
    ) -> IngestEventResponse:
        if payload.event == VSCodeEventType.STARTED:
            self._close_vscode_session(
                payload,
                "next_session",
                db,
            )
            is_foreground = self._is_foreground(payload, db)
            session = self._open_vscode_session(payload, is_foreground, db)
            db.commit()
            return IngestEventResponse(
                status="opened",
                session_id=session.id,
                is_foreground=is_foreground,
            )

        if payload.event == VSCodeEventType.STATE:
            session = self._update_vscode_session(payload, db)
            db.commit()
            return IngestEventResponse(
                status="state_updated",
                session_id=session.id if session else None,
                is_foreground=bool(session.is_foreground) if session else None,
            )

        if payload.event == VSCodeEventType.ENDED:
            session = self._close_vscode_session(
                payload,
                payload.trigger or "ended",
                db,
            )
            db.commit()
            return IngestEventResponse(
                status="closed",
                session_id=session.id if session else None,
            )

        return IngestEventResponse(status="ignored", accepted=True)

    def handle_browser_event(
        self, payload: BrowserEventPayload, db: Session
    ) -> IngestEventResponse:
        if payload.event == BrowserEventType.STATE:
            session = self._mark_browser_state(payload, db)
            db.commit()
            return IngestEventResponse(
                status="state_accepted",
                session_id=session.id if session else None,
            )

        if payload.event == BrowserEventType.STARTED:
            self._close_browser_session(
                payload.user_id,
                payload.browser_name,
                payload.browser_window_id,
                None,
                payload.timestamp,
                "next_session",
                db,
            )
            is_foreground = self._is_foreground(payload, db)
            session = self._open_browser_session(payload, is_foreground, db)
            db.commit()
            return IngestEventResponse(
                status="opened",
                session_id=session.id,
                is_foreground=is_foreground,
            )

        if payload.event == BrowserEventType.ENDED:
            session = self._close_browser_session(
                payload.user_id,
                payload.browser_name,
                payload.browser_window_id,
                payload.tab_id,
                payload.timestamp,
                payload.trigger or "ended",
                db,
            )
            db.commit()
            return IngestEventResponse(
                status="closed",
                session_id=session.id if session else None,
            )

        return IngestEventResponse(status="ignored", accepted=True)

    def _open_os_session(self, payload: OSEventPayload, db: Session) -> OSSessionRecord:
        timestamp = self._dt(payload.timestamp)
        session = OSSessionRecord(
            id=self._new_id(),
            user_id=payload.user_id,
            app_name=payload.app_name or "Unknown",
            app_category=payload.app_category,
            window_title=payload.window_title,
            process_id=payload.process_id,
            state="active",
            is_idle=0,
            is_locked=0,
            session_start=timestamp,
            trigger=payload.event.value,
            extra_data=self._json(payload.extra_data),
            created_at=timestamp,
            updated_at=timestamp,
        )
        db.add(session)
        db.flush()
        return session

    def _close_current_os_session(
        self, user_id: str, timestamp: datetime, closed_by: str, db: Session
    ) -> OSSessionRecord | None:
        session = (
            db.query(OSSessionRecord)
            .filter(OSSessionRecord.user_id == user_id, OSSessionRecord.session_end.is_(None))
            .order_by(OSSessionRecord.session_start.desc())
            .with_for_update()
            .first()
        )
        if session is None:
            return None
        self._close_timed_session(session, timestamp, closed_by)
        db.flush()
        return session

    def _mark_current_os_state(
        self, payload: OSEventPayload, db: Session
    ) -> OSSessionRecord | None:
        session = (
            db.query(OSSessionRecord)
            .filter(OSSessionRecord.user_id == payload.user_id, OSSessionRecord.session_end.is_(None))
            .order_by(OSSessionRecord.session_start.desc())
            .with_for_update()
            .first()
        )
        if session is None:
            return None

        if payload.event == OSEventType.IDLE_START:
            session.state = "idle"
            session.is_idle = 1
        elif payload.event == OSEventType.IDLE_END:
            session.state = "active"
            session.is_idle = 0
        elif payload.event == OSEventType.LOCKED:
            session.state = "locked"
            session.is_locked = 1
        elif payload.event == OSEventType.UNLOCKED:
            session.state = "active"
            session.is_locked = 0

        session.updated_at = self._dt(payload.timestamp)
        db.flush()
        return session

    def _open_vscode_session(
        self, payload: VSCodeEventPayload, is_foreground: bool, db: Session
    ) -> VSCodeSessionRecord:
        timestamp = self._dt(payload.timestamp)
        session = VSCodeSessionRecord(
            id=self._new_id(),
            user_id=payload.user_id,
            instance_id=payload.instance_id,
            session_start=timestamp,
            idle_sec=0,
            is_foreground=1 if is_foreground else 0,
            foreground_sec=0,
            confirmed_by_os=1 if is_foreground else 0,
            trigger=payload.trigger,
            created_at=timestamp,
            updated_at=timestamp,
        )
        self._apply_vscode_payload_update(session, payload)
        db.add(session)
        db.flush()
        return session

    def _update_vscode_session(
        self, payload: VSCodeEventPayload, db: Session
    ) -> VSCodeSessionRecord | None:
        session = self._get_open_vscode_session(payload.user_id, payload.instance_id, db)
        if session is None:
            return None

        self._apply_vscode_payload_update(session, payload)
        session.updated_at = self._dt(payload.timestamp)
        db.flush()
        return session

    def _close_vscode_session(
        self,
        payload: VSCodeEventPayload,
        closed_by: str,
        db: Session,
    ) -> VSCodeSessionRecord | None:
        sessions = self._get_open_vscode_sessions(payload.user_id, payload.instance_id, db)
        if not sessions:
            return None

        session = sessions[0]
        self._apply_vscode_payload_update(session, payload)
        for open_session in sessions:
            self._close_timed_session(open_session, payload.timestamp, closed_by)
        db.flush()
        return session

    def _get_open_vscode_sessions(
        self, user_id: str, instance_id: str, db: Session
    ) -> list[VSCodeSessionRecord]:
        return (
            db.query(VSCodeSessionRecord)
            .filter(
                VSCodeSessionRecord.user_id == user_id,
                VSCodeSessionRecord.instance_id == instance_id,
                VSCodeSessionRecord.session_end.is_(None),
            )
            .order_by(VSCodeSessionRecord.session_start.desc())
            .with_for_update()
            .all()
        )

    def _get_open_vscode_session(
        self, user_id: str, instance_id: str, db: Session
    ) -> VSCodeSessionRecord | None:
        sessions = self._get_open_vscode_sessions(user_id, instance_id, db)
        return sessions[0] if sessions else None

    def _apply_vscode_payload_update(
        self, session: VSCodeSessionRecord, payload: VSCodeEventPayload
    ) -> None:
        session.process_id = payload.process_id
        session.workspace_name = payload.workspace_name
        session.project_path = payload.project_path
        session.repo_id = payload.repo_id
        session.git_branch = payload.git_branch
        session.active_file_path = payload.active_file_path
        session.active_file_name = payload.active_file_name
        session.active_language = payload.active_language
        session.extra_data = self._json(payload.extra_data)

        # Map new tracking fields
        session.edited_file_count = payload.edited_file_count or 0
        session.changed_file_count = payload.changed_file_count or 0
        session.total_edit_count = payload.total_edit_count or 0
        session.total_save_count = payload.total_save_count or 0
        session.total_lines_added = payload.total_lines_added or 0
        session.total_lines_deleted = payload.total_lines_deleted or 0
        session.dominant_language = payload.dominant_language
        session.languages_json = self._json(payload.languages_json)
        session.edited_files_json = self._json(payload.edited_files_json)

        if payload.counters is not None:
            session.edit_count = payload.counters.edit_count
            session.save_count = payload.counters.save_count
            session.lines_added = payload.counters.lines_added
            session.lines_deleted = payload.counters.lines_deleted
            session.file_switch_count = payload.counters.file_switch_count
            session.terminal_command_count = payload.counters.terminal_command_count
            session.debug_run_count = payload.counters.debug_run_count
            session.idle_sec = payload.counters.idle_sec

    def _open_browser_session(
        self, payload: BrowserEventPayload, is_foreground: bool, db: Session
    ) -> BrowserSessionRecord:
        timestamp = self._dt(payload.timestamp)
        session = BrowserSessionRecord(
            id=self._new_id(),
            user_id=payload.user_id,
            browser_name=payload.browser_name,
            browser_window_id=payload.browser_window_id,
            tab_id=payload.tab_id,
            process_id=payload.process_id,
            domain=payload.domain,
            url=payload.url,
            title=payload.title,
            category=payload.category.value if payload.category else None,
            session_start=timestamp,
            is_foreground=1 if is_foreground else 0,
            confirmed_by_os=1 if is_foreground else 0,
            trigger=payload.trigger,
            extra_data=self._json(payload.extra_data),
            created_at=timestamp,
            updated_at=timestamp,
        )
        db.add(session)
        db.flush()
        return session

    def _close_browser_session(
        self,
        user_id: str,
        browser_name: str,
        browser_window_id: int | None,
        tab_id: int | None,
        timestamp: datetime,
        closed_by: str,
        db: Session,
    ) -> BrowserSessionRecord | None:
        query = db.query(BrowserSessionRecord).filter(
            BrowserSessionRecord.user_id == user_id,
            BrowserSessionRecord.browser_name == browser_name,
            BrowserSessionRecord.session_end.is_(None),
        )
        if browser_window_id is not None:
            query = query.filter(BrowserSessionRecord.browser_window_id == browser_window_id)
        if tab_id is not None:
            query = query.filter(BrowserSessionRecord.tab_id == tab_id)

        session = query.order_by(BrowserSessionRecord.session_start.desc()).with_for_update().first()
        if session is None:
            return None

        self._close_timed_session(session, timestamp, closed_by)
        db.flush()
        return session

    def _mark_browser_state(
        self, payload: BrowserEventPayload, db: Session
    ) -> BrowserSessionRecord | None:
        query = db.query(BrowserSessionRecord).filter(
            BrowserSessionRecord.user_id == payload.user_id,
            BrowserSessionRecord.browser_name == payload.browser_name,
            BrowserSessionRecord.session_end.is_(None),
        )
        if payload.browser_window_id is not None:
            query = query.filter(
                BrowserSessionRecord.browser_window_id == payload.browser_window_id
            )
        if payload.tab_id is not None:
            query = query.filter(BrowserSessionRecord.tab_id == payload.tab_id)

        session = query.order_by(BrowserSessionRecord.session_start.desc()).with_for_update().first()
        if session is None:
            return None

        session.updated_at = self._dt(payload.timestamp)
        if payload.title is not None:
            session.title = payload.title
        if payload.url is not None:
            session.url = payload.url
        if payload.domain is not None:
            session.domain = payload.domain
        if payload.category is not None:
            session.category = payload.category.value
        db.flush()
        return session

    def _close_all_open_extension_sessions(
        self, user_id: str, timestamp: datetime, closed_by: str, db: Session
    ) -> None:
        for session in (
            db.query(VSCodeSessionRecord)
            .filter(
                VSCodeSessionRecord.user_id == user_id,
                VSCodeSessionRecord.session_end.is_(None),
            )
            .with_for_update()
            .all()
        ):
            self._close_timed_session(session, timestamp, closed_by)

        for session in (
            db.query(BrowserSessionRecord)
            .filter(
                BrowserSessionRecord.user_id == user_id,
                BrowserSessionRecord.session_end.is_(None),
            )
            .with_for_update()
            .all()
        ):
            self._close_timed_session(session, timestamp, closed_by)

        db.flush()

    def _is_foreground(
        self, payload: VSCodeEventPayload | BrowserEventPayload, db: Session
    ) -> bool:
        active_os_session = (
            db.query(OSSessionRecord)
            .filter(
                OSSessionRecord.session_end.is_(None),
                OSSessionRecord.state == "active",
            )
            .order_by(OSSessionRecord.session_start.desc())
            .first()
        )
        if active_os_session is None:
            return False

        if payload.process_id is not None and active_os_session.process_id == payload.process_id:
            return True

        if isinstance(payload, VSCodeEventPayload):
            return self._is_vscode_os_session(active_os_session)

        return False

    def _update_foreground_flags(self, payload: OSEventPayload, db: Session) -> None:
        db.query(VSCodeSessionRecord).filter(
            VSCodeSessionRecord.session_end.is_(None)
        ).update(
            {"is_foreground": 0, "confirmed_by_os": 0}, synchronize_session=False
        )
        db.query(BrowserSessionRecord).filter(
            BrowserSessionRecord.session_end.is_(None)
        ).update(
            {"is_foreground": 0, "confirmed_by_os": 0}, synchronize_session=False
        )

        if payload.process_id is not None:
            db.query(VSCodeSessionRecord).filter(
                VSCodeSessionRecord.session_end.is_(None),
                VSCodeSessionRecord.process_id == payload.process_id,
            ).update(
                {"is_foreground": 1, "confirmed_by_os": 1},
                synchronize_session=False,
            )
            db.query(BrowserSessionRecord).filter(
                BrowserSessionRecord.session_end.is_(None),
                BrowserSessionRecord.process_id == payload.process_id,
            ).update(
                {"is_foreground": 1, "confirmed_by_os": 1},
                synchronize_session=False,
            )

        if self._is_vscode_os_payload(payload):
            db.query(VSCodeSessionRecord).filter(
                VSCodeSessionRecord.user_id == payload.user_id,
                VSCodeSessionRecord.session_end.is_(None),
            ).update(
                {"is_foreground": 1, "confirmed_by_os": 1},
                synchronize_session=False,
            )

        db.flush()

    def _is_vscode_os_payload(self, payload: OSEventPayload) -> bool:
        app_name = (payload.app_name or "").lower()
        window_title = (payload.window_title or "").lower()
        return self._looks_like_vscode(app_name) or self._looks_like_vscode(window_title)

    def _is_vscode_os_session(self, session: OSSessionRecord) -> bool:
        app_name = (session.app_name or "").lower()
        window_title = (session.window_title or "").lower()
        return self._looks_like_vscode(app_name) or self._looks_like_vscode(window_title)

    def _looks_like_vscode(self, value: str) -> bool:
        return (
            value == "code"
            or "visual studio code" in value
            or value.endswith(" - code")
            or " - visual studio code" in value
        )

    def _close_timed_session(self, session, timestamp: datetime, closed_by: str) -> None:
        end_time = self._dt(timestamp)
        duration_sec = max(
            0,
            int((ensure_aware(timestamp) - ensure_aware(session.session_start)).total_seconds()),
        )

        session.session_end = end_time
        session.duration_sec = duration_sec
        session.closed_by = closed_by
        session.updated_at = end_time

    def _json(self, value: dict | list | None) -> str | None:
        if value is None:
            return None
        return json.dumps(value, separators=(",", ":"), sort_keys=True)

    def _dt(self, value: datetime) -> datetime:
        return to_utc(value)

    def _new_id(self) -> str:
        return str(uuid4())

    def _require(self, value, message: str) -> None:
        if value is None or value == "":
            raise ValueError(message)
