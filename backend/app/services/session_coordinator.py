import json
import threading
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.config import SCHEMA_VERSION
from app.core.config import settings
from app.core.time import ensure_aware
from app.core.time import parse_iso
from app.core.time import to_local_iso
from app.models.db import BrowserSessionRecord
from app.models.db import IDESessionRecord
from app.models.db import OSSessionRecord
from app.models.schemas import BrowserEventPayload
from app.models.schemas import BrowserEventType
from app.models.schemas import IDEEventPayload
from app.models.schemas import IDEEventType
from app.models.schemas import IngestEventResponse
from app.models.schemas import OSEventPayload
from app.models.schemas import OSEventType

import logging

logger = logging.getLogger("smartdesk.session_coordinator")

# Process names / window-title fragments that identify an IDE. Used as a
# fallback when PID matching fails (extension host PID != window owner PID).
IDE_NAME_KEYWORDS = (
    "code",            # VS Code (Code.exe)
    "visual studio code",
    "antigravity",     # Antigravity IDE
    "cursor",
    "windsurf",
    "zed",
    "pycharm", "intellij", "idea", "clion", "goland", "webstorm", "datagrip", "rider",
    "sublime",
)

BROWSER_NAME_KEYWORDS = (
    "chrome", "firefox", "edge", "msedge", "safari", "brave", "opera",
    "comet", "arc", "vivaldi",
)

# IDE focus flicker (VS Code emits redundant/rapid window-state events) opens
# 0–2s sessions with no edits. Like the browser layer's <3s rule, drop these
# empty slivers on close so the timeline reads one row per real focus period.
MIN_IDE_SESSION_SEC = 3


def _looks_like_ide(value: str) -> bool:
    value = (value or "").lower()
    return any(k in value for k in IDE_NAME_KEYWORDS)


def _looks_like_browser(value: str, browser_name: str | None = None) -> bool:
    value = (value or "").lower()
    if browser_name and browser_name.lower() in value:
        return True
    return any(k in value for k in BROWSER_NAME_KEYWORDS)


class SessionCoordinator:
    def __init__(self) -> None:
        # The IDE extension fires "ended" + "started" as two separate async
        # POSTs at every focus change, and FastAPI runs the sync ingest
        # endpoints on a threadpool — so two events for one instance_id can be
        # processed concurrently, each with its own DB connection. Without
        # serialization, two "started" events both pass the
        # close-then-open check and insert overlapping duplicate rows (the
        # same wall-clock span counted N times). One lock per coordinator
        # (the router holds a single instance) makes IDE handling atomic.
        self._ide_lock = threading.Lock()
        # Track ongoing idle periods for time accumulation
        self._idle_start_timestamp: datetime | None = None

    def handle_os_event(self, payload: OSEventPayload, db: Session) -> IngestEventResponse:
        with db.begin():
            if payload.event == OSEventType.FOCUSED:
                self._require(payload.app_name, "app_name is required for focused OS events")
                self._close_current_os_session(payload.user_id, payload.timestamp, "next_event", db)
                session = self._open_os_session(payload, db)
                self._update_foreground_flags(payload, db)
                return IngestEventResponse(status="opened", session_id=session.id)

            if payload.event == OSEventType.BLURRED:
                return IngestEventResponse(status="ignored", accepted=True)

            if payload.event in {
                OSEventType.IDLE_START,
                OSEventType.IDLE_END,
            }:
                # Log event received
                logger.info(
                    "Coordinator_IDLE_Event_Received: event=%s user_id=%s timestamp=%s extra_data=%s",
                    payload.event.value,
                    payload.user_id,
                    payload.timestamp,
                    payload.extra_data,
                )

                # Log current open OS session ID
                current_session = (
                    db.query(OSSessionRecord)
                    .filter(OSSessionRecord.user_id == payload.user_id, OSSessionRecord.session_end.is_(None))
                    .order_by(OSSessionRecord.session_start.desc())
                    .first()
                )
                logger.info(
                    "Coordinator_IDLE_CurrentSession: user_id=%s session_id=%s state=%s",
                    payload.user_id,
                    current_session.id if current_session else "None",
                    current_session.state if current_session else "None",
                )

                session = self._mark_current_os_state(payload, db)

                # Log commit completed
                logger.info(
                    "Coordinator_IDLE_Event_Committed: event=%s session_id=%s",
                    payload.event.value,
                    session.id if session else None,
                )

                return IngestEventResponse(
                    status="state_updated",
                    session_id=session.id if session else None,
                )

            if payload.event in {OSEventType.SUSPEND, OSEventType.SHUTDOWN}:
                closed_by = payload.event.value
                session = self._close_current_os_session(payload.user_id, payload.timestamp, closed_by, db)
                self._close_all_open_extension_sessions(payload.user_id, payload.timestamp, closed_by, db)
                return IngestEventResponse(
                    status="closed_by_os_signal",
                    session_id=session.id if session else None,
                )

            return IngestEventResponse(status="ignored", accepted=True)

    def handle_ide_event(
        self, payload: IDEEventPayload, db: Session
    ) -> IngestEventResponse:
        with self._ide_lock:
            with db.begin():
                return self._handle_ide_event_locked(payload, db)

    def _handle_ide_event_locked(
        self, payload: IDEEventPayload, db: Session
    ) -> IngestEventResponse:
        if payload.event == IDEEventType.STARTED:
            # Close any orphaned open session, but do NOT adopt this started
            # event's counters into it: a "started" payload carries freshly
            # reset counters (idle_sec=0, edit_count=0, ...) that belong to the
            # NEW session. Applying them clobbered the closing row's accrued
            # idle/edits — e.g. a 5-minute idle period closed by the next
            # started event was wiped to idle_sec=0. Keep the row's own
            # last-heartbeat values instead.
            self._close_ide_session(
                payload,
                "next_session",
                db,
                apply_payload=False,
            )
            is_foreground = self._is_foreground(payload, db)
            session = self._open_ide_session(payload, is_foreground, db)
            db.commit()
            return IngestEventResponse(
                status="opened",
                session_id=session.id,
                is_foreground=is_foreground,
            )

        if payload.event == IDEEventType.STATE:
            session = self._update_ide_session(payload, db)
            if session is None:
                # The extension thinks its session is alive but the backend
                # closed it (server restart, timeout). Re-open instead of
                # silently dropping the data until the next started event.
                is_foreground = self._is_foreground(payload, db)
                session = self._open_ide_session(payload, is_foreground, db)
                db.commit()
                return IngestEventResponse(
                    status="reopened",
                    session_id=session.id,
                    is_foreground=is_foreground,
                )
            db.commit()
            return IngestEventResponse(
                status="state_updated",
                session_id=session.id,
                is_foreground=bool(session.is_foreground),
            )

        if payload.event == IDEEventType.ENDED:
            session = self._close_ide_session(
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
            if session is None:
                # Same desync healing as the IDE layer: heartbeat for a
                # session the backend already closed — re-open it.
                is_foreground = self._is_foreground(payload, db)
                session = self._open_browser_session(payload, is_foreground, db)
                db.commit()
                return IngestEventResponse(
                    status="reopened",
                    session_id=session.id,
                    is_foreground=is_foreground,
                )
            db.commit()
            return IngestEventResponse(
                status="state_accepted",
                session_id=session.id,
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
        timestamp = self._iso(payload.timestamp)
        session = OSSessionRecord(
            id=self._new_id(),
            user_id=payload.user_id,
            device_id=payload.device_id or settings.DEVICE_ID,
            schema_version=SCHEMA_VERSION,
            app_name=payload.app_name or "Unknown",
            app_category=payload.app_category,
            window_title=payload.window_title,
            process_id=payload.process_id,
            state="active",
            idle_time=0,
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
        # Get the current open session for this user
        session = (
            db.query(OSSessionRecord)
            .filter(OSSessionRecord.user_id == payload.user_id, OSSessionRecord.session_end.is_(None))
            .order_by(OSSessionRecord.session_start.desc())
            .first()
        )
        if session is None:
            return None

        # Keep timestamp as datetime for calculations, convert to string only for storage
        event_timestamp_dt = payload.timestamp
        event_timestamp_str = self._iso(event_timestamp_dt)
        extra_data = payload.extra_data or {}

        if payload.event == OSEventType.IDLE_START:
            # When idle starts, we need to split the session:
            # 1. Close the current active session at the REAL idle start time
            # 2. Open a new idle session starting at the REAL idle start time
            if self._idle_start_timestamp is None:
                # Calculate the real idle start time using the idle_sec from extra_data
                idle_sec = extra_data.get("idle_sec", 0)
                # The idle period began 'idle_sec' seconds ago
                real_idle_start = event_timestamp_dt - timedelta(seconds=idle_sec)
                self._idle_start_timestamp = real_idle_start

                # Log calculated real idle start
                logger.info(
                    "Coordinator_IDLE_START_Calc: idle_sec=%d real_idle_start=%s event_timestamp=%s",
                    idle_sec,
                    real_idle_start.isoformat(),
                    event_timestamp_dt.isoformat(),
                )

                # Close the current active session at the REAL idle start time
                closed_session = self._close_current_os_session(
                    payload.user_id, self._idle_start_timestamp, "idle_start", db
                )

                # Log session closed
                logger.info(
                    "Coordinator_IDLE_START_Closed: session_id=%s",
                    closed_session.id if closed_session else "None",
                )

                # Open a new idle session starting at the REAL idle start time
                # Create minimal payload - OSEventPayload will apply defaults
                idle_payload_dict = {
                    "user_id": payload.user_id,
                    "event": OSEventType.IDLE_START.value,
                    "timestamp": self._idle_start_timestamp,
                    "app_name": session.app_name,
                    "app_category": session.app_category,
                    "window_title": session.window_title,
                    "process_id": session.process_id,
                    "device_id": payload.device_id,
                    "extra_data": payload.extra_data
                }
                idle_payload = OSEventPayload(**idle_payload_dict)
                session = self._open_os_session(idle_payload, db)
                session.state = "idle"

                # Log idle session opened
                logger.info(
                    "Coordinator_IDLE_START_Opened: session_id=%s state=%s",
                    session.id,
                    session.state,
                )
            # If _idle_start_timestamp is already set, we're already in an idle period
            # and should not create duplicate sessions

        elif payload.event == OSEventType.IDLE_END:
            # When idle ends, close the idle session and open a new active session
            if self._idle_start_timestamp is not None:
                # Close the current idle session at current time
                closed_session = self._close_current_os_session(
                    payload.user_id, event_timestamp_dt, "idle_end", db
                )

                # Log session closed
                logger.info(
                    "Coordinator_IDLE_END_Closed: session_id=%s",
                    closed_session.id if closed_session else "None",
                )

                # Open a new active session starting at current time
                # Create minimal payload - OSEventPayload will apply defaults
                active_payload_dict = {
                    "user_id": payload.user_id,
                    "event": OSEventType.FOCUSED.value,
                    "timestamp": event_timestamp_dt,
                    "app_name": session.app_name,
                    "app_category": session.app_category,
                    "window_title": session.window_title,
                    "process_id": session.process_id,
                    "device_id": payload.device_id,
                    "extra_data": payload.extra_data
                }
                active_payload = OSEventPayload(**active_payload_dict)
                session = self._open_os_session(active_payload, db)
                session.state = "active"

                # Log active session opened
                logger.info(
                    "Coordinator_IDLE_END_Opened: session_id=%s state=%s",
                    session.id,
                    session.state,
                )

                # Clear the idle start timestamp
                self._idle_start_timestamp = None
            # If _idle_start_timestamp is None, we weren't tracking an idle period

        session.updated_at = event_timestamp_str
        db.flush()
        return session

    def _open_ide_session(
        self, payload: IDEEventPayload, is_foreground: bool, db: Session
    ) -> IDESessionRecord:
        timestamp = self._iso(payload.timestamp)
        session = IDESessionRecord(
            id=self._new_id(),
            user_id=payload.user_id,
            device_id=payload.device_id or settings.DEVICE_ID,
            schema_version=SCHEMA_VERSION,
            instance_id=payload.instance_id,
            session_start=timestamp,
            idle_sec=0,
            is_foreground=1 if is_foreground else 0,
            confirmed_by_os=1 if is_foreground else 0,
            collection_reason="foreground" if is_foreground else "background_ai",
            trigger=payload.trigger,
            created_at=timestamp,
            updated_at=timestamp,
        )
        self._apply_ide_payload_update(session, payload)
        db.add(session)
        db.flush()
        return session

    def _update_ide_session(
        self, payload: IDEEventPayload, db: Session
    ) -> IDESessionRecord | None:
        session = self._get_open_ide_session(payload.user_id, payload.instance_id, db)
        if session is None:
            return None

        self._apply_ide_payload_update(session, payload)
        session.updated_at = self._iso(payload.timestamp)
        db.flush()
        return session

    def _close_ide_session(
        self,
        payload: IDEEventPayload,
        closed_by: str,
        db: Session,
        apply_payload: bool = True,
    ) -> IDESessionRecord | None:
        sessions = self._get_open_ide_sessions(payload.user_id, payload.instance_id, db)
        if not sessions:
            return None

        # Only an ENDED event carries the session's real final counters; a
        # STARTED-path close must not overwrite them with the new session's
        # zeros (see the STARTED handler).
        if apply_payload:
            self._apply_ide_payload_update(sessions[0], payload)
        survivor: IDESessionRecord | None = None
        for open_session in sessions:
            self._close_timed_session(open_session, payload.timestamp, closed_by)
            # Drop rows that captured nothing worth keeping:
            #  - empty background_ai: a blurred IDE produced no edits, so per
            #    policy "blurred + idle -> collect nothing".
            #  - empty sliver: a sub-3s foreground row from focus flicker.
            if self._is_empty_background(open_session) or self._is_empty_sliver(open_session):
                db.delete(open_session)
            elif survivor is None:
                survivor = open_session
        db.flush()
        return survivor

    @staticmethod
    def _is_empty_background(session: IDESessionRecord) -> bool:
        return (
            session.collection_reason == "background_ai"
            and not session.edit_count
            and not session.save_count
        )

    @staticmethod
    def _is_empty_sliver(session: IDESessionRecord) -> bool:
        return (
            (session.duration_sec or 0) < MIN_IDE_SESSION_SEC
            and not session.edit_count
            and not session.save_count
        )

    def _get_open_ide_sessions(
        self, user_id: str, instance_id: str, db: Session
    ) -> list[IDESessionRecord]:
        return (
            db.query(IDESessionRecord)
            .filter(
                IDESessionRecord.user_id == user_id,
                IDESessionRecord.instance_id == instance_id,
                IDESessionRecord.session_end.is_(None),
            )
            .order_by(IDESessionRecord.session_start.desc())
            .all()
        )

    def _get_open_ide_session(
        self, user_id: str, instance_id: str, db: Session
    ) -> IDESessionRecord | None:
        sessions = self._get_open_ide_sessions(user_id, instance_id, db)
        return sessions[0] if sessions else None

    def _apply_ide_payload_update(
        self, session: IDESessionRecord, payload: IDEEventPayload
    ) -> None:
        # Context fields keep their last-known value: heartbeats fired while
        # focus is on a non-editor panel arrive without them, and overwriting
        # with NULL would erase what we already know about the session.
        session.ide_name = payload.ide_name or session.ide_name
        session.process_id = payload.process_id or session.process_id
        session.parent_process_id = payload.parent_process_id or session.parent_process_id
        session.workspace_name = payload.workspace_name or session.workspace_name
        session.project_path = payload.project_path or session.project_path
        session.repo_id = payload.repo_id or session.repo_id
        session.git_branch = payload.git_branch or session.git_branch
        session.active_file_path = payload.active_file_path or session.active_file_path
        session.active_file_name = payload.active_file_name or session.active_file_name
        session.active_language = payload.active_language or session.active_language
        if payload.extra_data is not None:
            session.extra_data = self._json(payload.extra_data)

        if payload.edited_file_count is not None:
            session.edited_file_count = payload.edited_file_count
        if payload.changed_file_count is not None:
            session.changed_file_count = payload.changed_file_count
        if payload.dominant_language is not None:
            session.dominant_language = payload.dominant_language
        if payload.languages_json is not None:
            session.languages_json = self._json(payload.languages_json)
        if payload.edited_files_json is not None:
            session.edited_files_json = json.dumps(
                payload.edited_files_json, separators=(",", ":")
            )

        if payload.counters is not None:
            session.edit_count = payload.counters.edit_count
            session.save_count = payload.counters.save_count
            session.lines_added = payload.counters.lines_added
            session.lines_deleted = payload.counters.lines_deleted
            session.file_switch_count = payload.counters.file_switch_count
            session.idle_sec = payload.counters.idle_sec

    def _open_browser_session(
        self, payload: BrowserEventPayload, is_foreground: bool, db: Session
    ) -> BrowserSessionRecord:
        timestamp = self._iso(payload.timestamp)
        session = BrowserSessionRecord(
            id=self._new_id(),
            user_id=payload.user_id,
            device_id=payload.device_id or settings.DEVICE_ID,
            schema_version=SCHEMA_VERSION,
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

        session = query.order_by(BrowserSessionRecord.session_start.desc()).first()
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

        session = query.order_by(BrowserSessionRecord.session_start.desc()).first()
        if session is None:
            return None

        session.updated_at = self._iso(payload.timestamp)
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
            db.query(IDESessionRecord)
            .filter(
                IDESessionRecord.user_id == user_id,
                IDESessionRecord.session_end.is_(None),
            )
            .all()
        ):
            self._close_timed_session(session, timestamp, closed_by)

        for session in (
            db.query(BrowserSessionRecord)
            .filter(
                BrowserSessionRecord.user_id == user_id,
                BrowserSessionRecord.session_end.is_(None),
            )
            .all()
        ):
            self._close_timed_session(session, timestamp, closed_by)

        db.flush()

    # ------------------------------------------------------------------ #
    # Foreground detection                                                 #
    # ------------------------------------------------------------------ #
    #
    # The OS collector is the ground truth: it reports the PID of the
    # window that owns the foreground window. Extension host processes
    # (IDE extensions) report their own PID *and* their parent PID, since
    # the extension host's PID never matches the window-owner PID. If
    # neither PID matches, fall back to name/category matching.

    def _is_foreground(
        self, payload: IDEEventPayload | BrowserEventPayload, db: Session
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

        os_pid = active_os_session.process_id
        if os_pid is not None:
            candidate_pids = {payload.process_id}
            if isinstance(payload, IDEEventPayload):
                candidate_pids.add(payload.parent_process_id)
            candidate_pids.discard(None)
            if os_pid in candidate_pids:
                return True

        if isinstance(payload, IDEEventPayload):
            # The extension itself knows whether its window has focus;
            # require OS agreement that *some* IDE is foreground.
            if payload.is_window_focused is False:
                return False
            return self._is_ide_os_session(active_os_session)

        # Browser extensions cannot report a useful PID — match by app
        # name/category against the OS foreground session instead.
        return (
            (active_os_session.app_category or "").lower() == "browser"
            and _looks_like_browser(active_os_session.app_name, payload.browser_name)
        )

    def _update_foreground_flags(self, payload: OSEventPayload, db: Session) -> None:
        # Promote-only. We never blank open sessions to is_foreground=0 here:
        # the extensions open a fresh row at every focus/blur boundary (one row
        # is a clean foreground OR background period), so demotion is the
        # extension's job — it closes the foreground row on blur and opens a
        # new background row if work continues. Blanking here used to race the
        # extension's blur event: when focus moved to a non-IDE/non-browser app
        # (terminal, explorer), the still-open IDE row was reset to 0 and never
        # re-promoted, then closed by blur — persisting is_foreground=0 with
        # collection_reason='foreground'. This method now only *confirms*
        # foreground sessions the OS can positively identify.
        if payload.process_id is not None:
            # Match the IDE session whose extension-host PID *or* parent
            # PID equals the OS foreground window PID.
            db.query(IDESessionRecord).filter(
                IDESessionRecord.session_end.is_(None),
                (IDESessionRecord.process_id == payload.process_id)
                | (IDESessionRecord.parent_process_id == payload.process_id),
            ).update(
                {
                    "is_foreground": 1,
                    "confirmed_by_os": 1,
                    "collection_reason": "foreground",
                },
                synchronize_session=False,
            )
            db.query(BrowserSessionRecord).filter(
                BrowserSessionRecord.session_end.is_(None),
                BrowserSessionRecord.process_id == payload.process_id,
            ).update(
                {"is_foreground": 1, "confirmed_by_os": 1},
                synchronize_session=False,
            )

        if self._is_ide_os_payload(payload):
            # Promote open IDE sessions — except background_ai rows, which
            # belong to a blurred window doing AI work; the extension closes
            # them itself and opens a fresh foreground row on refocus.
            db.query(IDESessionRecord).filter(
                IDESessionRecord.user_id == payload.user_id,
                IDESessionRecord.session_end.is_(None),
                (IDESessionRecord.collection_reason.is_(None))
                | (IDESessionRecord.collection_reason != "background_ai"),
            ).update(
                {
                    "is_foreground": 1,
                    "confirmed_by_os": 1,
                    "collection_reason": "foreground",
                },
                synchronize_session=False,
            )

        if self._is_browser_os_payload(payload):
            db.query(BrowserSessionRecord).filter(
                BrowserSessionRecord.user_id == payload.user_id,
                BrowserSessionRecord.session_end.is_(None),
            ).update(
                {"is_foreground": 1, "confirmed_by_os": 1},
                synchronize_session=False,
            )

        db.flush()

    def _is_ide_os_payload(self, payload: OSEventPayload) -> bool:
        if payload.app_category:
            return payload.app_category.lower() == "ide"
        return _looks_like_ide(payload.app_name) or _looks_like_ide(payload.window_title)

    def _is_ide_os_session(self, session: OSSessionRecord) -> bool:
        if session.app_category:
            return session.app_category.lower() == "ide"
        return _looks_like_ide(session.app_name) or _looks_like_ide(session.window_title)

    def _is_browser_os_payload(self, payload: OSEventPayload) -> bool:
        return (
            (payload.app_category or "").lower() == "browser"
            or _looks_like_browser(payload.app_name)
        )

    def _close_timed_session(self, session, timestamp: datetime, closed_by: str) -> None:
        start_dt = ensure_aware(parse_iso(session.session_start))
        end_dt = ensure_aware(timestamp)
        # Never stamp an end before the start. The extension fires ended +
        # started as two async POSTs, so a close can arrive carrying an
        # out-of-order (earlier) timestamp; the old max(0, ...) clamped the
        # duration to 0 but still wrote end<start, silently dropping the row's
        # real time. Pin the end to the start in that case (0-length close).
        if end_dt < start_dt:
            end_dt = start_dt
        duration_sec = int((end_dt - start_dt).total_seconds())

        end_time = to_local_iso(end_dt)
        session.session_end = end_time
        session.duration_sec = duration_sec
        session.closed_by = closed_by
        session.updated_at = end_time

        # Idle can never exceed the session's wall-clock span. The extension's
        # idle counter is wall-clock based and can drift past the backend's
        # event-timestamp duration, so clamp it as a safety net (otherwise the
        # dashboard reports idle_sec > duration_sec).
        idle = getattr(session, "idle_time", None)
        if idle is not None and idle > duration_sec:
            session.idle_time = duration_sec

        # Accumulate ongoing idle time if session ends while in that state,
        # and move the start timestamp forward so the next session can continue
        # counting from this point (avoiding double counting on IDLE_END).
        if self._idle_start_timestamp is not None:
            ongoing_idle = (timestamp - self._idle_start_timestamp).total_seconds()
            session.idle_time += int(ongoing_idle)
            self._idle_start_timestamp = timestamp

    def _json(self, value: dict | None) -> str | None:
        if value is None:
            return None
        return json.dumps(value, separators=(",", ":"), sort_keys=True)

    def _iso(self, value: datetime) -> str:
        return to_local_iso(value)

    def _new_id(self) -> str:
        return str(uuid4())

    def _require(self, value, message: str) -> None:
        if value is None or value == "":
            raise ValueError(message)
