import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.services.activity_session_summary_service import ActivitySessionSummaryService

SCHEDULER_ENABLED = True
SCHEDULER_INTERVAL_SECONDS = 60
SCHEDULER_USER_ID = "demo_user"
SCHEDULER_WINDOW_MINUTES = 30

COLOMBO_TZ = ZoneInfo("Asia/Colombo")


def _to_colombo_iso(dt: datetime) -> str:
    return dt.astimezone(COLOMBO_TZ).replace(microsecond=0).isoformat()


def _latest_window(now: datetime) -> tuple[datetime, datetime]:
    local_now = now.astimezone(COLOMBO_TZ)
    window_end = local_now.replace(second=0, microsecond=0)
    window_start = window_end - timedelta(minutes=SCHEDULER_WINDOW_MINUTES)
    return window_start, window_end


class ActivitySessionSummaryScheduler:
    def __init__(self):
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._service = ActivitySessionSummaryService()

    def start(self) -> None:
        if not SCHEDULER_ENABLED:
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        print("[Activity Session Scheduler] Started")

    def stop(self) -> None:
        self._stop_event.set()
        print("[Activity Session Scheduler] Stopped")

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._build_latest_window()
            except Exception as exc:
                print(f"[Activity Session Scheduler] Error: {exc}")

            for _ in range(SCHEDULER_INTERVAL_SECONDS):
                if self._stop_event.is_set():
                    break
                time.sleep(1)

    def _build_latest_window(self) -> None:
        now = datetime.now(COLOMBO_TZ)
        window_start, window_end = _latest_window(now)
        start_iso = _to_colombo_iso(window_start)
        end_iso = _to_colombo_iso(window_end)
        print(f"[Activity Session Scheduler] Building {start_iso} to {end_iso}")
        self._service.build(SCHEDULER_USER_ID, start_iso, end_iso)


activity_session_scheduler = ActivitySessionSummaryScheduler()
