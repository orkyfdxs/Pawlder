"""
SnapGrab PDF viewer: shows a PDF in its own window using the Edge engine
(WebView2, via pywebview), which brings Edge's built-in PDF viewer — scroll,
zoom, search, print. Runs as its own process because pywebview and tkinter
each need to own the main thread.

Usage:  pythonw snapgrab_pdf.py <file.pdf> [parent_x parent_y parent_w parent_h [parent_pid]]

The first viewer stays alive (hidden) after you close it and serves later
PDFs over a named pipe, so only the first open pays the startup cost. It
quits by itself after 5 idle minutes, or when SnapGrab exits.
"""

import os
import sys
import time

_T0 = time.perf_counter()
_HERE = os.path.dirname(os.path.abspath(__file__))

# Same environment repair as snapgrab_embed.py: WebView2 refuses to start
# without APPDATA/LOCALAPPDATA/TEMP, which some launch methods strip.
_home = os.path.dirname(_HERE)


def _ensure_dir_env(name, path):
    cur = os.environ.get(name, "")
    if not cur or "%" in cur or not os.path.isdir(cur):
        os.environ[name] = path


_ensure_dir_env("USERPROFILE", _home)
_ensure_dir_env("APPDATA", os.path.join(_home, "AppData", "Roaming"))
_ensure_dir_env("LOCALAPPDATA", os.path.join(_home, "AppData", "Local"))
_tmp = os.path.join(_home, "AppData", "Local", "Temp")
_ensure_dir_env("TEMP", _tmp)
_ensure_dir_env("TMP", _tmp)

_libs = os.path.join(_HERE, "snapgrab_libs")
if os.path.isdir(_libs) and _libs not in sys.path:
    sys.path.insert(0, _libs)

BG = "#0e0e10"


def _geometry(argv):
    """72% x 74% of the screen SnapGrab is on, centered on it (matches the
    video players). Falls back to the primary screen."""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
    px = py = pw = ph = None
    if len(argv) >= 6:
        try:
            px, py, pw, ph = (int(v) for v in argv[2:6])
        except ValueError:
            pass

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    pt = wintypes.POINT((px + pw // 2) if px is not None else 0,
                        (py + ph // 2) if px is not None else 0)
    mon = user32.MonitorFromPoint(pt, 2)  # MONITOR_DEFAULTTONEAREST
    mi = MONITORINFO(); mi.cbSize = ctypes.sizeof(mi)
    user32.GetMonitorInfoW(mon, ctypes.byref(mi))
    wa = mi.rcWork
    sw, sh = wa.right - wa.left, wa.bottom - wa.top
    w, h = int(sw * 0.72), int(sh * 0.74)
    return wa.left + (sw - w) // 2, wa.top + (sh - h) // 2, w, h


# NOTE: never touch window.native (the .NET WinForms form) from pywebview's
# event threads. Getting/setting its properties from a non-UI thread goes
# through pythonnet while holding the GIL; if the UI thread meanwhile needs
# Python, both wait forever — the viewer froze "Not Responding" that way
# (light title bar + default icon = it hung right here). Use plain Win32 via
# ctypes instead: ctypes releases the GIL, and PostMessage never blocks.
_ICONS = []                                      # keep icon handles alive


def _find_hwnd(title, timeout=3.0):
    """Our own top-level window with this title (pure Win32)."""
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    me = os.getpid()
    end = time.time() + timeout
    while time.time() < end:
        found = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def cb(h, _):
            pid = wintypes.DWORD()
            u.GetWindowThreadProcessId(h, ctypes.byref(pid))
            if pid.value == me:
                b = ctypes.create_unicode_buffer(512)
                u.GetWindowTextW(h, b, 512)
                if b.value == title:
                    found.append(h)
            return True
        u.EnumWindows(cb, 0)
        if found:
            return found[0]
        time.sleep(0.05)
    return None


def _style_window(hwnd):
    """Dark native title bar + SnapGrab icon, without touching .NET."""
    import ctypes
    if not hwnd:
        return
    try:
        val = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(val),
                                                   ctypes.sizeof(val))
    except Exception:
        pass
    try:
        ico = os.path.join(_HERE, "snapgrab.ico")
        if os.path.isfile(ico):
            u = ctypes.windll.user32
            u.LoadImageW.restype = ctypes.c_void_p
            u.LoadImageW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint,
                                     ctypes.c_int, ctypes.c_int, ctypes.c_uint]
            u.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p,
                                       ctypes.c_void_p]
            for which, size in ((1, 32), (0, 16)):          # ICON_BIG, ICON_SMALL
                h = u.LoadImageW(None, ico, 1, size, size, 0x10)  # LR_LOADFROMFILE
                if h:
                    _ICONS.append(h)
                    u.PostMessageW(hwnd, 0x0080, which, h)     # WM_SETICON (async)
    except Exception:
        pass


# ── reuse: one viewer process serves every PDF ─────────────────────────────
# Starting Python + .NET + the Edge engine is ~0.85 s; doing it once and then
# just loading the next file into the same (hidden) window is far faster.
# SnapGrab talks to us over a Windows named pipe — local only, no network.
PIPE = r"\\.\pipe\snapgrab-pdf-" + "".join(
    c for c in (os.environ.get("USERNAME") or "user") if c.isalnum())
AUTH = b"snapgrab-pdf-v1"
IDLE_QUIT = int(os.environ.get("SNAPGRAB_PDF_IDLE", "300"))   # hidden secs before quitting


def _alive(pid):
    """Is SnapGrab (the process that started us) still running?"""
    import ctypes
    k = ctypes.windll.kernel32
    h = k.OpenProcess(0x1000, False, pid)      # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    try:
        code = ctypes.c_ulong()
        k.GetExitCodeProcess(h, ctypes.byref(code))
        return code.value == 259                # STILL_ACTIVE
    finally:
        k.CloseHandle(h)


def _to_front(hwnd):
    """Bring our window forward — pure Win32 (see the note above)."""
    if not hwnd:
        return
    try:
        import ctypes
        u = ctypes.windll.user32
        u.ShowWindow(hwnd, 9)                   # SW_RESTORE
        u.SetForegroundWindow(hwnd)
    except Exception:
        pass


def main():
    if len(sys.argv) < 2 or not os.path.isfile(sys.argv[1]):
        return
    path = os.path.abspath(sys.argv[1])
    parent_pid = int(sys.argv[6]) if len(sys.argv) > 6 and sys.argv[6].isdigit() else 0
    import threading
    import webview
    from pathlib import Path

    # become the shared viewer — unless another one already is (then this
    # is just a one-off window that quits on close, like before)
    listener = None
    try:
        from multiprocessing.connection import Listener
        listener = Listener(PIPE, family="AF_PIPE", authkey=AUTH)
    except Exception:
        listener = None

    x, y, w, h = _geometry(sys.argv)
    win = webview.create_window(os.path.basename(path), Path(path).as_uri(),
                                x=x, y=y, width=w, height=h,
                                background_color=BG, text_select=True)
    state = {"hidden_since": None, "quitting": False, "hwnd": None}
    loaded = threading.Event()

    def on_shown():
        state["hwnd"] = _find_hwnd(os.path.basename(path))
        _style_window(state["hwnd"])
        if os.environ.get("SNAPGRAB_PDF_TIMING"):
            print(f"shown {time.perf_counter() - _T0:.2f}s", flush=True)

    def on_loaded():
        loaded.set()
        if os.environ.get("SNAPGRAB_PDF_TIMING"):
            print(f"loaded {time.perf_counter() - _T0:.2f}s", flush=True)

    def on_closing():
        if listener is None or state["quitting"]:
            return True                          # really close
        # ✕ = hide and wait for the next PDF instead of quitting
        threading.Thread(target=lambda: (win.hide(), state.update(
            hidden_since=time.time())), daemon=True).start()
        return False

    def open_pdf(p, geo):
        name = os.path.basename(p)
        loaded.clear()
        win.load_url(Path(p).as_uri())
        win.set_title(name)
        try:
            gx, gy, gw, gh = _geometry(["", p] + [str(v) for v in geo])
            win.resize(gw, gh)
            win.move(gx, gy)
        except Exception:
            pass
        # show once the new file has loaded, so the old PDF never flashes
        loaded.wait(1.5)
        state["hidden_since"] = None
        win.show()
        _to_front(state["hwnd"])

    def serve():
        while True:
            try:
                conn = listener.accept()
            except Exception:
                return                           # listener closed → quitting
            try:
                msg = conn.recv()
                ok = isinstance(msg, dict) and os.path.isfile(msg.get("open", ""))
                if ok:
                    open_pdf(msg["open"], msg.get("geo") or [])
                # reply only once the PDF is showing: if this window ever
                # freezes, SnapGrab gets no answer and replaces the viewer
                conn.send("ok" if ok else "bad")
            except Exception:
                pass
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

    def watchdog():
        while True:
            time.sleep(5)
            hidden = state["hidden_since"]
            idle = hidden is not None and time.time() - hidden > IDLE_QUIT
            orphan = hidden is not None and parent_pid and not _alive(parent_pid)
            if idle or orphan:
                state["quitting"] = True
                try:
                    listener.close()
                except Exception:
                    pass
                try:
                    win.destroy()
                except Exception:
                    pass
                return

    win.events.shown += on_shown
    win.events.loaded += on_loaded
    win.events.closing += on_closing

    def started():
        if listener is not None:
            # SnapGrab reads this to replace us if we ever stop answering
            try:
                d = os.path.join(os.environ.get("LOCALAPPDATA", _tmp), "SnapGrab")
                os.makedirs(d, exist_ok=True)
                with open(os.path.join(d, "pdfviewer.pid"), "w") as f:
                    f.write(str(os.getpid()))
            except Exception:
                pass
            threading.Thread(target=serve, daemon=True).start()
            threading.Thread(target=watchdog, daemon=True).start()

    # keep WebView2's profile (not private) so later opens start warmer
    store = os.path.join(os.environ.get("LOCALAPPDATA", _tmp), "SnapGrab", "webview")
    webview.start(started, private_mode=False, storage_path=store)
    if listener is not None:                      # we were the shared viewer:
        try:                                      # retire our pid file so a
            pidf = os.path.join(os.environ.get("LOCALAPPDATA", _tmp),   # reused
                                "SnapGrab", "pdfviewer.pid")            # pid is
            with open(pidf) as f:                                       # never
                if f.read().strip() == str(os.getpid()):                # mistaken
                    os.remove(pidf)                                     # for us
        except Exception:
            pass
    os._exit(0)                                   # don't wait on the pipe thread


if __name__ == "__main__":
    main()
