import time
import threading
import win32con
import win32gui
import win32ts
import pythoncom

WM_WTSSESSION_CHANGE = 0x02B1  # message id

# Event codes for WM_WTSSESSION_CHANGE (wParam values)
WTS_SESSION_LOGON  = 0x5
WTS_SESSION_LOGOFF = 0x6
WTS_SESSION_LOCK   = 0x7
WTS_SESSION_UNLOCK = 0x8


class SessionState:
    def __init__(self):
        self._lock = threading.Lock()
        self.is_locked = False
        self.last_event = None
        self.last_event_time = None

    def set(self, *, is_locked=None, last_event=None, last_event_time=None):
        with self._lock:
            if is_locked is not None:
                self.is_locked = is_locked
            if last_event is not None:
                self.last_event = last_event
            if last_event_time is not None:
                self.last_event_time = last_event_time

    def snapshot(self):
        with self._lock:
            return {
                "is_locked": self.is_locked,
                "last_event": self.last_event,
                "last_event_time": self.last_event_time,
            }


class SessionWatcher(threading.Thread):
    def __init__(self, state: SessionState):
        super().__init__(daemon=True)
        self.state = state
        self._stop = threading.Event()
        self.hwnd = None

    def stop(self):
        self._stop.set()
        if self.hwnd:
            try:
                win32gui.PostMessage(self.hwnd, win32con.WM_CLOSE, 0, 0)
            except Exception:
                pass

    def run(self):
        pythoncom.CoInitialize()
        class_name = "SmartDeskSessionWatcher"

        def wndproc(hwnd, msg, wparam, lparam):
            if msg == WM_WTSSESSION_CHANGE:
                if wparam == WTS_SESSION_LOCK:
                    self.state.set(is_locked=True, last_event="lock", last_event_time=time.time())
                elif wparam == WTS_SESSION_UNLOCK:
                    self.state.set(is_locked=False, last_event="unlock", last_event_time=time.time())
                elif wparam == WTS_SESSION_LOGON:
                    self.state.set(last_event="logon", last_event_time=time.time())
                elif wparam == WTS_SESSION_LOGOFF:
                    self.state.set(last_event="logoff", last_event_time=time.time())
                return 0

            if msg == win32con.WM_CLOSE:
                win32gui.DestroyWindow(hwnd)
                return 0

            if msg == win32con.WM_DESTROY:
                win32gui.PostQuitMessage(0)
                return 0

            return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

        wc = win32gui.WNDCLASS()
        wc.lpfnWndProc = wndproc
        wc.lpszClassName = class_name
        wc.hInstance = win32gui.GetModuleHandle(None)
        win32gui.RegisterClass(wc)

        self.hwnd = win32gui.CreateWindowEx(
            0, class_name, "SmartDesk Hidden Window",
            0, 0, 0, 0, 0, 0, 0, wc.hInstance, None
        )

        win32ts.WTSRegisterSessionNotification(self.hwnd, win32ts.NOTIFY_FOR_THIS_SESSION)

        try:
            while not self._stop.is_set():
                pythoncom.PumpWaitingMessages()
                time.sleep(0.05)
        finally:
            try:
                win32ts.WTSUnRegisterSessionNotification(self.hwnd)
            except Exception:
                pass
            try:
                win32gui.DestroyWindow(self.hwnd)
            except Exception:
                pass
            pythoncom.CoUninitialize()
