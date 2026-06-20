"""OS foreground monitor — Phase 10.

This script runs as a standalone background process alongside the FastAPI
backend.  It monitors the foreground window using Windows APIs (via
``pygetwindow`` / ``psutil``) and POSTs session events to the ingest API.

Events emitted:
  - ``focused``    — a new foreground window (different app or PID) gained focus
  - ``blurred``    — (not sent — coordinator ignores blur-only events)
  - ``idle_start`` — system has been idle for IDLE_THRESHOLD_SEC
  - ``idle_end``   — system activity resumed after idle
  - ``suspend``    — system is about to suspend
  - ``shutdown``   — system is about to shut down

Usage::

    cd backend
    python -m app.services.os_collector

Dependencies (install once):
    pip install pygetwindow psutil requests

The script runs a polling loop with a configurable POLL_INTERVAL_SEC.
For production use, consider a tighter interval (0.5–1.0 s) to reduce
session boundary jitter.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import threading
import time
from typing import Any

from app.core.time import local_now_iso

logger = logging.getLogger("smartdesk.os_collector")

# ------------------------------------------------------------------ #
# Configuration                                                        #
# ------------------------------------------------------------------ #

BACKEND_URL: str = os.environ.get("SMARTDESK_BACKEND_URL", "http://127.0.0.1:8000")
USER_ID: str = os.environ.get("SMARTDESK_USER_ID", "local_user")
POLL_INTERVAL_SEC: float = float(os.environ.get("SMARTDESK_POLL_INTERVAL", "1.0"))
IDLE_THRESHOLD_SEC: int = int(os.environ.get("SMARTDESK_IDLE_THRESHOLD", "120"))

INGEST_URL = f"{BACKEND_URL}/api/v1/ingest/os/event"

# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #

def _now_iso() -> str:
    return local_now_iso()


def _classify_app(app_name: str) -> str:
    """Return a broad category for a given app name."""
    name_lower = app_name.lower()
    if any(k in name_lower for k in (
        "code",         # VS Code (Code.exe)
        "antigravity",  # Antigravity IDE
        "cursor",       # Cursor AI editor
        "windsurf",     # Windsurf editor
        "zed",          # Zed editor
        "pycharm", "idea", "clion", "goland", "webstorm", "datagrip", "rider",  # JetBrains
        "vim", "nvim", "neovim",
        "sublime", "atom",
        "emacs", "helix",
        "xcode",
    )):
        return "IDE"
    if any(k in name_lower for k in (
        "chrome", "firefox", "edge", "safari", "brave", "opera",
        "comet", "arc", "vivaldi",
    )):
        return "Browser"
    if any(k in name_lower for k in ("slack", "teams", "discord", "zoom", "meet", "outlook", "mail")):
        return "Communication"
    if any(k in name_lower for k in ("terminal", "cmd", "powershell", "bash", "wt", "iterm")):
        return "Terminal"
    return "Other"


def _post_event(payload: dict[str, Any]) -> bool:
    """POST a single event payload.  Returns True on success."""
    try:
        import requests  # type: ignore[import]
        resp = requests.post(INGEST_URL, json=payload, timeout=5)
        resp.raise_for_status()
        return True
    except Exception as exc:
        logger.warning("Failed to POST event: %s", exc)
        return False


# ------------------------------------------------------------------ #
# Platform-specific foreground window detection                        #
# ------------------------------------------------------------------ #

def _get_foreground_info() -> dict[str, Any] | None:
    """Return info about the current foreground window, or None on error.

    Returns a dict with keys: app_name, window_title, process_id.
    """
    try:
        import ctypes
        import ctypes.wintypes

        # Get foreground window handle
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None

        # Get window title
        length = user32.GetWindowTextLengthW(hwnd) + 1
        buf = ctypes.create_unicode_buffer(length)
        user32.GetWindowTextW(hwnd, buf, length)
        window_title = buf.value.strip()

        # Get PID
        pid = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        process_id = pid.value

        # Get process name from PID via psutil
        import psutil  # type: ignore[import]
        try:
            proc = psutil.Process(process_id)
            app_name = proc.name().replace(".exe", "")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            app_name = "Unknown"

        return {
            "app_name": app_name,
            "window_title": window_title or None,
            "process_id": process_id,
        }
    except Exception as exc:
        logger.warning("Could not read foreground window: %s", exc)
        return None


def _get_idle_seconds() -> float:
    """Return seconds since last user input (Windows only)."""
    try:
        import ctypes

        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(lii)
        ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii))
        millis = ctypes.windll.kernel32.GetTickCount() - lii.dwTime
        return millis / 1000.0
    except Exception:
        return 0.0


def _is_screen_locked() -> bool:
    """Return True if the Windows workstation is locked."""
    try:
        import ctypes
        # OpenInputDesktop returns NULL when no interactive desktop is available (locked)
        h = ctypes.windll.user32.OpenInputDesktop(0, False, 0x0001)
        if h:
            ctypes.windll.user32.CloseDesktop(h)
            return False
        return True
    except Exception:
        return False


# ------------------------------------------------------------------ #
# Main loop                                                            #
# ------------------------------------------------------------------ #

class OSCollector:
    """Polls the OS for foreground window changes and emits ingest events.

    Can be started in two ways:

    1. **Embedded in the backend** (recommended) — call ``start()`` from the
       FastAPI lifespan.  The loop runs in a daemon thread so the server starts
       immediately without blocking.

    2. **Standalone** — run ``python -m app.services.os_collector``.
       The ``__main__`` block calls ``_run_blocking()`` directly.
    """

    def __init__(self) -> None:
        self._last_app: str | None = None
        self._last_pid: int | None = None
        self._is_idle: bool = False
        self._running: bool = False
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        """Start the OS collector in a background daemon thread (non-blocking)."""
        if self._running:
            logger.warning("OSCollector already running — ignoring start().")
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run_blocking,
            name="smartdesk-os-collector",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "OSCollector started in background thread. Backend: %s  User: %s  Poll: %.1fs",
            BACKEND_URL, USER_ID, POLL_INTERVAL_SEC,
        )

    def stop(self) -> None:
        """Signal the polling loop to exit.

        Deliberately does NOT emit a "shutdown" event: the backend stopping
        (e.g. a --reload restart) does not mean the user stopped working,
        and the shutdown event would force-close every open IDE/browser
        session. Genuinely abandoned sessions are closed by the timeout job.
        """
        self._running = False
        logger.info("OSCollector stopped.")

    def _run_blocking(self) -> None:
        """Inner polling loop — runs inside a thread (or directly in __main__)."""
        logger.info(
            "OSCollector polling loop active. Backend: %s  User: %s  Poll: %.1fs",
            BACKEND_URL, USER_ID, POLL_INTERVAL_SEC,
        )
        while self._running:
            try:
                self._tick()
            except Exception:
                logger.exception("Error during OS collector tick.")
            time.sleep(POLL_INTERVAL_SEC)

    def _tick(self) -> None:
        idle_sec = _get_idle_seconds()
        is_idle = idle_sec >= IDLE_THRESHOLD_SEC

        # ── Idle / active ─────────────────────────────────────────────
        if is_idle and not self._is_idle:
            self._is_idle = True
            payload = self._build("idle_start")
            # Include actual idle duration for accurate session splitting
            payload["extra_data"] = (payload.get("extra_data") or {}) | {"idle_sec": idle_sec}
            _post_event(payload)
        elif not is_idle and self._is_idle:
            self._is_idle = False
            payload = self._build("idle_end")
            # Include actual idle duration for accurate session splitting
            payload["extra_data"] = (payload.get("extra_data") or {}) | {"idle_sec": idle_sec}
            _post_event(payload)

        # ── Foreground window ─────────────────────────────────────────
        info = _get_foreground_info()
        if info is None:
            return

        app_name = info["app_name"]
        pid = info["process_id"]

        if app_name != self._last_app or pid != self._last_pid:
            self._last_app = app_name
            self._last_pid = pid
            payload = self._build("focused")
            payload.update({
                "app_name": app_name,
                "app_category": _classify_app(app_name),
                "window_title": info["window_title"],
                "process_id": pid,
            })
            _post_event(payload)

    def _build(self, event: str) -> dict[str, Any]:
        return {
            "user_id": USER_ID,
            "event": event,
            "timestamp": _now_iso(),
            "app_name": self._last_app,
            "app_category": _classify_app(self._last_app) if self._last_app else None,
            "window_title": None,
            "process_id": self._last_pid,
        }


# ------------------------------------------------------------------ #
# Entry point (standalone mode)                                        #
# ------------------------------------------------------------------ #

def _handle_signal(signum, _frame):
    logger.info("Received signal %d — sending shutdown event.", signum)
    _post_event({
        "user_id": USER_ID,
        "event": "shutdown",
        "timestamp": _now_iso(),
    })
    sys.exit(0)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    collector = OSCollector()
    collector._running = True  # set flag before calling blocking loop directly
    collector._run_blocking()
