import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.services.productivity_summary_service import ProductivitySummaryService

SUMMARY_BUILDER_ENABLED = True
SUMMARY_BUILDER_INTERVAL_SECONDS = 60
SUMMARY_BUILDER_USER_ID = "demo_user"

COLOMBO_TZ = ZoneInfo("Asia/Colombo")


def _to_colombo_iso(dt: datetime) -> str:
    return dt.astimezone(COLOMBO_TZ).replace(microsecond=0).isoformat()


def _latest_completed_window(now: datetime) -> tuple[datetime, datetime]:
    local_now = now.astimezone(COLOMBO_TZ)
    end_minute = (local_now.minute // 10) * 10
    window_end = local_now.replace(minute=end_minute, second=0, microsecond=0)
    window_start = window_end - timedelta(minutes=10)
    return window_start, window_end


class ProductivitySummaryScheduler:
    def __init__(self):
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._service = ProductivitySummaryService()
        self._last_built_end: datetime | None = None

    def start(self) -> None:
        if not SUMMARY_BUILDER_ENABLED:
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        print("[Summary Scheduler] Started")

    def stop(self) -> None:
        self._stop_event.set()
        print("[Summary Scheduler] Stopped")

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._build_latest_completed_window()
            except Exception as exc:
                print(f"[Summary Scheduler] Error: {exc}")

            for _ in range(SUMMARY_BUILDER_INTERVAL_SECONDS):
                if self._stop_event.is_set():
                    break
                time.sleep(1)

    def _build_latest_completed_window(self) -> None:
        now = datetime.now(COLOMBO_TZ)
        print("[Summary Scheduler] Checking latest completed 10-minute window")
        window_start, window_end = _latest_completed_window(now)

        if self._last_built_end and window_end <= self._last_built_end:
            return

        start_iso = _to_colombo_iso(window_start)
        end_iso = _to_colombo_iso(window_end)

        print(f"[Summary Scheduler] Building {start_iso} to {end_iso}")
        self._service.build(SUMMARY_BUILDER_USER_ID, start_iso, end_iso)
        self._last_built_end = window_end
        print("[Summary Scheduler] Upsert complete")


summary_scheduler = ProductivitySummaryScheduler()
