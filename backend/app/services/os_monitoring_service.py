import time
import threading
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import ctypes
from ctypes import wintypes

import psutil
import win32gui
import win32process
import win32api

from app.core.session_watcher import SessionState, SessionWatcher

from app.models.os_minute_window import OSMinuteWindowPayload
from app.services.os_minute_window_service import OSMinuteWindowService

POLL_SEC = 1.0
WINDOW_SEC = 60
IDLE_THRESHOLD_MS = 60_000
USER_ID = os.getenv("USER_ID", "demo_user")

class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

GetTickCount64 = ctypes.windll.kernel32.GetTickCount64
GetTickCount64.restype = ctypes.c_ulonglong

def get_idle_ms() -> int:
    lii = LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
        return 0
    return int(GetTickCount64() - lii.dwTime)

def get_foreground_pid() -> int | None:
    hwnd = win32gui.GetForegroundWindow()
    if not hwnd: return None
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    return pid or None

def get_process_name(pid: int) -> str | None:
    try:
        return psutil.Process(pid).name()
    except Exception:
        return None

def get_process_exe(pid: int) -> str | None:
    try:
        return psutil.Process(pid).exe()
    except Exception:
        return None

def get_file_version_field(exe_path: str, field_name: str) -> str | None:
    try:
        info = win32api.GetFileVersionInfo(exe_path, "\\")
        trans = win32api.VerQueryValue(info, r"\VarFileInfo\Translation")
        if not trans: return None
        lang, codepage = trans[0]
        str_path = fr"\StringFileInfo\{lang:04x}{codepage:04x}\{field_name}"
        val = win32api.VerQueryValue(info, str_path)
        return val.strip() if isinstance(val, str) else None
    except Exception:
        return None

def get_foreground_context() -> dict:
    pid = get_foreground_pid()
    if not pid: return {}
    proc_name = get_process_name(pid)
    exe_path = get_process_exe(pid)
    company = product = description = None
    if exe_path:
        company = get_file_version_field(exe_path, "CompanyName")
        product = get_file_version_field(exe_path, "ProductName")
        description = get_file_version_field(exe_path, "FileDescription")
    return {"pid": pid, "procName": proc_name, "exePath": exe_path, "company": company, "product": product, "description": description}

def now_epoch() -> float: return time.time()
def iso_colombo(ts) -> str: return datetime.fromtimestamp(ts, tz=ZoneInfo("Asia/Colombo")).replace(microsecond=0).isoformat()

def heuristics_category_from_text(t: str) -> str | None:
    t = t.lower()
    if any(x in t for x in ["chrome", "msedge", "edge", "firefox", "brave", "opera"]): return "browser"
    if any(x in t for x in ["code", "pycharm", "idea", "vscode"]): return "ide"
    if any(x in t for x in ["whatsapp", "slack", "discord", "outlook"]): return "communication"
    if any(x in t for x in ["zoom", "teams", "skype", "meet"]): return "meeting"
    if any(x in t for x in ["winword", "excel", "powerpnt", "pdf"]): return "docs"
    if any(x in t for x in ["terminal", "powershell", "cmd", "bash"]): return "terminal"
    if any(x in t for x in ["explorer", "taskmgr", "systemsettings"]): return "system"
    return None

def classify_context(ctx: dict) -> tuple[str, str]:
    proc = ctx.get("procName")
    if not proc: return "unknown", "default"
    proc_l = proc.lower()
    cat = heuristics_category_from_text(proc_l)
    if cat: return cat, "heuristics_name"
    meta_text = " ".join([str(ctx.get("company") or ""), str(ctx.get("product") or ""), str(ctx.get("description") or "")]).strip()
    if meta_text:
        cat2 = heuristics_category_from_text(meta_text)
        if cat2: return cat2, "heuristics_meta"
    return "other", "default"

class OSMonitorTask:
    def __init__(self):
        self.stop_event = threading.Event()

        self.minute_window_service = OSMinuteWindowService()
        self.sess_state = SessionState()
        self.watcher = SessionWatcher(self.sess_state)

    def start(self):
        self.watcher.start()
        threading.Thread(target=self._run_loop, daemon=True).start()

    def stop(self):
        self.stop_event.set()
        self.watcher.stop()

    def _run_loop(self):
        window_start = now_epoch()
        durations = defaultdict(float)
        category_durations = defaultdict(float)
        idle_time = active_time = locked_time = 0.0
        switch_count = 0
        last_proc = last_cat = None
        last_change_t = now_epoch()
        was_idle = was_locked = False
        last_tick_t = now_epoch()

        while not self.stop_event.is_set():
            t = now_epoch()
            dt = t - last_tick_t
            last_tick_t = t
            
            locked = self.sess_state.snapshot()["is_locked"]
            ctx = get_foreground_context()
            if (ctx.get("procName") or "").lower() == "lockapp.exe":
                locked = True

            if locked:
                locked_time += dt
                if not was_locked and last_proc is not None:
                    durations[last_proc] += (t - last_change_t)
                    if last_cat: category_durations[last_cat] += (t - last_change_t)
                    last_proc = last_cat = None
                    last_change_t = t
                was_locked = True
                time.sleep(POLL_SEC)
                continue

            if was_locked and not locked:
                cat, _ = classify_context(ctx)
                last_proc = ctx.get("procName")
                last_cat = cat
                last_change_t = t
                was_idle = was_locked = False

            proc = ctx.get("procName")
            cat, _ = classify_context(ctx)
            is_idle = get_idle_ms() >= IDLE_THRESHOLD_MS

            if is_idle:
                idle_time += dt
                if not was_idle and last_proc is not None:
                    seg = t - last_change_t
                    durations[last_proc] += seg
                    if last_cat: category_durations[last_cat] += seg
                    last_proc = last_cat = None
                    last_change_t = t
            else:
                active_time += dt
                if was_idle:
                    last_proc = proc
                    last_cat = cat
                    last_change_t = t
                else:
                    if proc is not None and proc != last_proc:
                        if last_proc is not None:
                            seg = t - last_change_t
                            durations[last_proc] += seg
                            if last_cat: category_durations[last_cat] += seg
                            switch_count += 1
                        last_proc = proc
                        last_cat = cat
                        last_change_t = t
            was_idle = is_idle

            if (t - window_start) >= WINDOW_SEC:
                if not was_idle and not was_locked and last_proc is not None:
                    seg = t - last_change_t
                    durations[last_proc] += seg
                    if last_cat: category_durations[last_cat] += seg
                    last_change_t = t

                payload_data = {
                    "window_start": iso_colombo(window_start),
                    "window_end": iso_colombo(t),
                    "active_app_durations_sec": {k: round(v, 2) for k, v in durations.items()},
                    "category_durations_sec": {k: round(v, 2) for k, v in category_durations.items()},
                    "context_switch_count": int(switch_count),
                    "idle_time_sec": round(idle_time, 2),
                    "active_time_sec": round(active_time, 2),
                    "locked_time_sec": round(locked_time, 2)
                }

                top_app = None
                top_app_sec = None
                if durations:
                    top_app, top_app_sec = max(durations.items(), key=lambda kv: kv[1])

                dominant_app_category = None
                dominant_app_category_sec = None
                if category_durations:
                    dominant_app_category, dominant_app_category_sec = max(
                        category_durations.items(), key=lambda kv: kv[1]
                    )


                minute_payload = OSMinuteWindowPayload(
                    user_id=USER_ID,
                    window_start=payload_data["window_start"],
                    window_end=payload_data["window_end"],
                    timezone="Asia/Colombo",
                    active_time_sec=int(payload_data.get("active_time_sec") or 0),
                    idle_time_sec=int(payload_data.get("idle_time_sec") or 0),
                    locked_time_sec=int(payload_data.get("locked_time_sec") or 0),
                    context_switch_count=int(payload_data.get("context_switch_count") or 0),
                    top_app=top_app,
                    top_app_sec=int(top_app_sec) if top_app_sec is not None else None,
                    dominant_app_category=dominant_app_category,
                    dominant_app_category_sec=int(dominant_app_category_sec) if dominant_app_category_sec is not None else None,
                    active_app_durations_json=json.dumps(payload_data.get("active_app_durations_sec") or {}),
                    category_durations_json=json.dumps(payload_data.get("category_durations_sec") or {}),
                    source="os_collector",
                    schema_version="1.0",
                    created_at=iso_colombo(t),
                    updated_at=iso_colombo(t),
                )
                
                # Push directly to the backend abstraction
                try:
                    self.minute_window_service.process_and_save(minute_payload)
                    print(f"[OS Collector] Minute window saved successfully")
                except Exception as e:
                    print(f"Failed to save OS minute window: {e}")

                window_start = t
                durations.clear()
                category_durations.clear()
                switch_count = 0
                idle_time = active_time = locked_time = 0.0

            time.sleep(POLL_SEC)

os_monitor = OSMonitorTask()
