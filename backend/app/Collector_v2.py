"""
LEGACY/ARCHIVED: Standalone OS collector script. Not used by the current FastAPI runtime.

Collector_v2_1.py — Smart Desk OS Signals (Windows)
Option 1 polling + Lock/Unlock + Categories + Local Auto-Categorisation (NO Stage 2)

Category set (Option B):
  ide, browser, communication, meeting, docs, terminal, system, other

Fallback categorisation (when not in JSON):
  - Process-name heuristics
  - Optional Windows file metadata (Company/Product/Description) heuristics
"""

import time
import os
import json
from collections import defaultdict
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import ctypes
from ctypes import wintypes

import psutil
import win32gui
import win32process
import win32api  # for file version info (pywin32)

from session_watcher import SessionState, SessionWatcher


# ======================
# CONFIG
# ======================
POLL_SEC = 1.0
WINDOW_SEC = 60
IDLE_THRESHOLD_MS = 60_000
DEBUG_SWITCH_PRINTS = True

CATEGORIES_FILE = "app_categories.json"

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "smartdesk")
USER_ID = os.getenv("USER_ID", "demo_user")
OUTBOX_FILE = "os_outbox.jsonl"

# Allowed label set (Option B)
ALLOWED_CATEGORIES = {"ide", "browser", "communication", "meeting", "docs", "terminal", "system", "other", "unknown"}


# ======================
# WINDOWS IDLE HELPERS
# ======================
class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


GetTickCount64 = ctypes.windll.kernel32.GetTickCount64
GetTickCount64.restype = ctypes.c_ulonglong


def get_idle_ms() -> int:
    """Milliseconds since last keyboard/mouse input (metadata-only)."""
    lii = LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
    ok = ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii))
    if not ok:
        return 0
    now_ms = int(GetTickCount64())
    return int(now_ms - lii.dwTime)


# ======================
# FOREGROUND PROCESS INFO
# ======================
def get_foreground_pid() -> int | None:
    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        return None
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    return pid or None


def get_process_name(pid: int) -> str | None:
    try:
        return psutil.Process(pid).name()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


def get_process_exe(pid: int) -> str | None:
    try:
        return psutil.Process(pid).exe()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


def get_file_version_field(exe_path: str, field_name: str) -> str | None:
    """
    Read version resource string fields from exe (CompanyName, ProductName, FileDescription, etc.).
    If not available, return None.
    """
    try:
        info = win32api.GetFileVersionInfo(exe_path, "\\")
        trans = win32api.VerQueryValue(info, r"\VarFileInfo\Translation")
        if not trans:
            return None
        lang, codepage = trans[0]
        str_path = fr"\StringFileInfo\{lang:04x}{codepage:04x}\{field_name}"
        val = win32api.VerQueryValue(info, str_path)
        if isinstance(val, str) and val.strip():
            return val.strip()
        return None
    except Exception:
        return None


def get_foreground_context() -> dict:
    """
    Returns minimal foreground context:
      { pid, procName, exePath, company, product, description }
    All metadata-only.
    """
    pid = get_foreground_pid()
    if not pid:
        return {"pid": None, "procName": None, "exePath": None, "company": None, "product": None, "description": None}

    proc_name = get_process_name(pid)
    exe_path = get_process_exe(pid)

    company = product = description = None
    if exe_path:
        company = get_file_version_field(exe_path, "CompanyName")
        product = get_file_version_field(exe_path, "ProductName")
        description = get_file_version_field(exe_path, "FileDescription")

    return {
        "pid": pid,
        "procName": proc_name,
        "exePath": exe_path,
        "company": company,
        "product": product,
        "description": description,
    }


def now_epoch() -> float:
    return time.time()


COLOMBO_TZ = ZoneInfo("Asia/Colombo")


def iso_colombo(ts_epoch: float) -> str:
    return datetime.fromtimestamp(ts_epoch, tz=COLOMBO_TZ).replace(microsecond=0).isoformat()


# ======================
# CATEGORIES
# ======================
def load_categories(path: str) -> dict:
    """
    Loads app_categories.json -> mapping process_name_lower -> category
    """
    if not os.path.exists(path):
        print(f"[WARN] {path} not found. JSON mapping disabled.")
        return {}

    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    proc_to_cat = {}
    for cat, procs in raw.items():
        cat_l = str(cat).strip().lower()
        if cat_l not in ALLOWED_CATEGORIES:
            print(f"[WARN] Ignoring unknown category in JSON: {cat}")
            continue
        for p in procs:
            proc_to_cat[str(p).strip().lower()] = cat_l

    return proc_to_cat


def heuristics_category_from_text(text: str) -> str | None:
    """
    Pure string heuristics. Returns a category or None.
    """
    t = text.lower()

    # Browser
    if any(x in t for x in ["chrome", "msedge", "edge", "firefox", "brave", "opera"]):
        return "browser"

    # IDE / editors
    if any(x in t for x in ["code", "pycharm", "idea", "intellij", "clion", "webstorm", "phpstorm", "rider", "sublime", "atom", "vscode"]):
        return "ide"

    # Communication
    if any(x in t for x in ["whatsapp", "slack", "discord", "telegram", "signal", "messenger", "outlook", "thunderbird"]):
        return "communication"

    # Meetings
    if any(x in t for x in ["zoom", "teams", "skype", "webex", "meet"]):
        return "meeting"

    # Docs/notes/PDF
    if any(x in t for x in ["winword", "excel", "powerpnt", "onenote", "notion", "acrobat", "acrord32", "sumatrapdf", "foxit", "pdf"]):
        return "docs"

    # Terminal shells
    if any(x in t for x in ["windowsterminal", "powershell", "pwsh", "cmd", "bash", "git-bash", "mintty"]):
        return "terminal"

    # System utilities
    if any(x in t for x in ["explorer", "taskmgr", "systemsettings", "searchhost", "control", "settings"]):
        return "system"

    return None


def classify_context(ctx: dict, proc_to_cat: dict) -> tuple[str, str]:
    """
    Returns (category, method):
      category: one of ALLOWED_CATEGORIES (except unknown used for None proc)
      method: 'json' | 'heuristics_name' | 'heuristics_meta' | 'default'
    """
    proc = ctx.get("procName")
    if not proc:
        return "unknown", "default"

    proc_l = proc.lower()

    # 1) JSON mapping
    if proc_l in proc_to_cat:
        return proc_to_cat[proc_l], "json"

    # 2) Name heuristics
    cat = heuristics_category_from_text(proc_l)
    if cat:
        return cat, "heuristics_name"

    # 3) Metadata heuristics (company/product/description)
    meta_text = " ".join([
        str(ctx.get("company") or ""),
        str(ctx.get("product") or ""),
        str(ctx.get("description") or ""),
    ]).strip()

    if meta_text:
        cat2 = heuristics_category_from_text(meta_text)
        if cat2:
            return cat2, "heuristics_meta"

    # 4) Default
    return "other", "default"


# ======================
# DB SEND (OPTIONAL)
# ======================
def append_outbox(payload: dict) -> None:
    # Need to make a copy to remove _id inserted by pymongo
    payload_copy = payload.copy()
    payload_copy.pop("_id", None)
    with open(OUTBOX_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload_copy) + "\n")


def try_send(payload: dict, collection) -> bool:
    """
    Insert payload into MongoDB.
    If not connected, store to OUTBOX_FILE (local-only mode).
    """
    if collection is None:
        append_outbox(payload)
        return False

    try:
        collection.insert_one(payload)
        return True
    except Exception as e:
        print(f"[ERROR] Failed writing to MongoDB: {e}")
        return False


# ======================
# MAIN
# ======================
if __name__ == "__main__":
    PROC_TO_CAT = load_categories(CATEGORIES_FILE)

    # Initialize MongoDB Client
    mongo_client = None
    mongo_collection = None
    try:
        mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=2000)
        # Force a connection check
        mongo_client.admin.command('ping')
        db = mongo_client[MONGO_DB_NAME]
        mongo_collection = db["raw_os_signals"]
    except Exception as e:
        print(f"[WARN] Could not connect to MongoDB at {MONGO_URI}: {e}")
        mongo_collection = None

    sess_state = SessionState()
    watcher = SessionWatcher(sess_state)
    watcher.start()

    print("Running OS signals (polling + lock/unlock + categories + local heuristics). Ctrl+C to stop.")
    print(f"Poll={POLL_SEC}s | Window={WINDOW_SEC}s | IdleThreshold={IDLE_THRESHOLD_MS}ms")
    if mongo_collection is not None:
        print(f"Database: MongoDB connected at {MONGO_URI} (Collection: raw_os_signals)")
    else:
        print(f"Database: (not connected) -> saving payloads to {OUTBOX_FILE}")
    print(f"Categories file: {CATEGORIES_FILE} ({'loaded' if PROC_TO_CAT else 'missing/empty'})")
    print("Category set:", sorted(ALLOWED_CATEGORIES - {"unknown"}), "+ unknown")

    window_start = now_epoch()

    # ACTIVE-only durations
    durations = defaultdict(float)           # proc -> seconds
    category_durations = defaultdict(float)  # category -> seconds

    # Time accounting
    idle_time = 0.0
    active_time = 0.0
    locked_time = 0.0

    # Switch count
    switch_count = 0

    # Segment tracking
    last_proc = None
    last_cat = None
    last_change_t = now_epoch()
    was_idle = False
    was_locked = False

    # Accurate dt
    last_tick_t = now_epoch()

    try:
        while True:
            t = now_epoch()
            dt = t - last_tick_t
            last_tick_t = t

            # Lock state
            locked = sess_state.snapshot()["is_locked"]

            # Extra fallback: treat lock screen as locked
            fg_ctx_for_lock = get_foreground_context()
            if (fg_ctx_for_lock.get("procName") or "").lower() == "lockapp.exe":
                locked = True

            # -------- LOCKED HANDLING --------
            if locked:
                locked_time += dt

                # entering lock: close active segment immediately
                if not was_locked and last_proc is not None:
                    durations[last_proc] += (t - last_change_t)
                    if last_cat:
                        category_durations[last_cat] += (t - last_change_t)

                    last_proc = None
                    last_cat = None
                    last_change_t = t

                was_locked = True
                time.sleep(POLL_SEC)
                continue

            # just unlocked: restart segment (no switch)
            if was_locked and not locked:
                ctx = get_foreground_context()
                cat, _method = classify_context(ctx, PROC_TO_CAT)
                last_proc = ctx.get("procName")
                last_cat = cat
                last_change_t = t
                was_idle = False
                was_locked = False

            # -------- ACTIVE/IDLE LOGIC --------
            ctx = get_foreground_context()
            proc = ctx.get("procName")
            cat, cat_method = classify_context(ctx, PROC_TO_CAT)

            idle_ms = get_idle_ms()
            is_idle = idle_ms >= IDLE_THRESHOLD_MS

            if is_idle:
                idle_time += dt

                # entering idle: close active segment so idle isn't attributed to apps
                if not was_idle and last_proc is not None:
                    seg = (t - last_change_t)
                    durations[last_proc] += seg
                    if last_cat:
                        category_durations[last_cat] += seg

                    last_proc = None
                    last_cat = None
                    last_change_t = t

            else:
                active_time += dt

                # coming back from idle: start fresh segment (no switch)
                if was_idle:
                    last_proc = proc
                    last_cat = cat
                    last_change_t = t

                else:
                    # normal switching
                    if proc is not None and proc != last_proc:
                        if last_proc is not None:
                            seg = (t - last_change_t)
                            durations[last_proc] += seg
                            if last_cat:
                                category_durations[last_cat] += seg
                            switch_count += 1

                        last_proc = proc
                        last_cat = cat
                        last_change_t = t

                        if DEBUG_SWITCH_PRINTS:
                            print(f"SWITCH -> {proc}  [cat={cat} via {cat_method}]")

            was_idle = is_idle

            # -------- WINDOW FLUSH --------
            if (t - window_start) >= WINDOW_SEC:
                # close current active segment
                if (not was_idle) and (not was_locked) and last_proc is not None:
                    seg = (t - last_change_t)
                    durations[last_proc] += seg
                    if last_cat:
                        category_durations[last_cat] += seg
                    last_change_t = t

                top_app = None
                if durations:
                    top_app = max(durations.items(), key=lambda kv: kv[1])[0]

                # focus ratio = ide / (ide + browser + communication)
                ide_sec = category_durations.get("ide", 0.0)
                browser_sec = category_durations.get("browser", 0.0)
                comm_sec = category_durations.get("communication", 0.0)
                denom = max(0.001, ide_sec + browser_sec + comm_sec)
                focus_ratio = ide_sec / denom

                payload = {
                    "user_id": USER_ID,

                    "window_start": iso_colombo(window_start),
                    "window_end": iso_colombo(t),

                    "active_app_durations_sec": {k: round(v, 2) for k, v in durations.items()},
                    "category_durations_sec": {k: round(v, 2) for k, v in category_durations.items()},

                    "context_switch_count": int(switch_count),

                    "idle_time_sec": round(idle_time, 2),
                    "active_time_sec": round(active_time, 2),
                    "locked_time_sec": round(locked_time, 2),

                    "top_app": top_app,
                    "focus_ratio": round(focus_ratio, 3),

                    "idle_threshold_ms": int(IDLE_THRESHOLD_MS),
                    "poll_sec": float(POLL_SEC),
                    "categories_file": CATEGORIES_FILE,

                    "source": "os_signals",
                    "schema_version": 1
                }

                # Copy payload since MongoDB insert_one alters it by adding _id
                print_payload = payload.copy()

                print("\n=== WINDOW SUMMARY ===")
                print(print_payload)
                print("======================\n")

                sent = try_send(payload, mongo_collection)
                if mongo_collection is not None and not sent:
                    append_outbox(payload)
                    print(f"[WARN] Backend send failed. Saved to {OUTBOX_FILE}\n")

                # reset window state
                window_start = t
                durations = defaultdict(float)
                category_durations = defaultdict(float)
                switch_count = 0
                idle_time = 0.0
                active_time = 0.0
                locked_time = 0.0

            time.sleep(POLL_SEC)

    except KeyboardInterrupt:
        pass
    finally:
        watcher.stop()
