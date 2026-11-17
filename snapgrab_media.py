"""
SnapGrab media module: a thumbnail Library of downloaded videos and a
full embedded video player (libVLC). Kept separate from snapgrab.pyw so the
downloader keeps working even if VLC or Pillow is unavailable.

Public entry point: open_library(parent_tk, folder)
media_available() reports whether playback + thumbnails can work.
"""

import os
import sys
import shutil
import subprocess
import threading
import tkinter as tk

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_LIBS = os.path.join(SCRIPT_DIR, "snapgrab_libs")
if os.path.isdir(_LIBS) and _LIBS not in sys.path:
    sys.path.insert(0, _LIBS)
if os.path.isdir(_LIBS):
    try:
        os.add_dll_directory(_LIBS)   # let python-mpv find libmpv-2.dll
    except Exception:
        pass

MEDIA_EXTS = (".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi",
              ".mp3", ".m4a", ".flac", ".wav", ".ogg")
VIDEO_EXTS = (".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi")

# ── graphite theme (mirrors snapgrab.pyw) ──────────────────────────────
class T:
    BG      = "#0e0e10"
    SURFACE = "#151517"
    CARD    = "#1a1a1e"
    CARD_HI = "#222228"
    BORDER  = "#27272c"
    TEXT    = "#f4f4f5"
    SUB     = "#a1a1aa"
    MUTED   = "#71717a"
    DIM     = "#4b4b53"
    WHITE   = "#fafafa"

F_BASE  = ("Segoe UI", 10)
F_SMALL = ("Segoe UI", 9)
F_TINY  = ("Segoe UI", 8)
F_TITLE = ("Segoe UI Semibold", 13)


def _ff(name):
    p = shutil.which(name)
    if p:
        return p
    for d in (os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Links"),
              SCRIPT_DIR):
        c = os.path.join(d, name + ".exe")
        if os.path.isfile(c):
            return c
    return name


FFMPEG = _ff("ffmpeg")
FFPROBE = _ff("ffprobe")


def _no_window():
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = subprocess.SW_HIDE
    return si


def media_available():
    """True if we can both render thumbnails (Pillow) and play (vlc+libVLC)."""
    try:
        import PIL  # noqa
        import vlc
        vlc.Instance()
        return True
    except Exception:
        return False


def have_pillow():
    try:
        import PIL  # noqa
        return True
    except Exception:
        return False


def mpv_available():
    """True if the bundled libmpv + python-mpv are present (preferred player:
    frame-accurate stepping both directions, lighter/instant like VLC-embed)."""
    return (os.path.isfile(os.path.join(_LIBS, "libmpv-2.dll"))
            and os.path.isfile(os.path.join(_LIBS, "mpv.py")))


MPV_OK = mpv_available()


def probe_duration(path):
    try:
        r = subprocess.run([FFPROBE, "-v", "error", "-show_entries",
                            "format=duration", "-of", "default=nk=1:nw=1", path],
                           capture_output=True, text=True, startupinfo=_no_window(),
                           timeout=20)
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def fmt_time(secs):
    secs = int(secs)
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def center_window(win, parent=None, wfrac=0.72, hfrac=0.74):
    """Size a window to a fraction of the screen and center it (on the parent's
    monitor when possible)."""
    win.update_idletasks()
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    w, h = int(sw * wfrac), int(sh * hfrac)
    cx, cy = sw // 2, sh // 2
    if parent is not None:
        try:
            if parent.winfo_width() > 1:
                cx = parent.winfo_rootx() + parent.winfo_width() // 2
                cy = parent.winfo_rooty() + parent.winfo_height() // 2
        except Exception:
            pass
    x, y = max(0, cx - w // 2), max(0, cy - h // 2)
    win.geometry(f"{w}x{h}+{x}+{y}")


# ═══════════════════════════════════════════════════════════════════════
#  Windows Shell thumbnails — read Explorer's own thumbnail cache
#  (thumbcache_*.db) and the file's duration property. A few ms per video,
#  no ffmpeg/ffprobe process launches. Falls back to ffmpeg if unavailable.
# ═══════════════════════════════════════════════════════════════════════
try:
    import ctypes
    import ctypes.wintypes as _wt
    from ctypes import POINTER as _P, byref as _byref, c_void_p as _vp

    _ole32, _shell32 = ctypes.windll.ole32, ctypes.windll.shell32
    _gdi32, _user32 = ctypes.windll.gdi32, ctypes.windll.user32

    class _GUID(ctypes.Structure):
        _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                    ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]

    def _guid(s):
        g = _GUID()
        _ole32.CLSIDFromString(ctypes.c_wchar_p(s), _byref(g))
        return g

    class _SIZE(ctypes.Structure):
        _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]

    class _BITMAP(ctypes.Structure):
        _fields_ = [("bmType", ctypes.c_long), ("bmWidth", ctypes.c_long),
                    ("bmHeight", ctypes.c_long), ("bmWidthBytes", ctypes.c_long),
                    ("bmPlanes", _wt.WORD), ("bmBitsPixel", _wt.WORD), ("bmBits", _vp)]

    class _BIH(ctypes.Structure):
        _fields_ = [("biSize", _wt.DWORD), ("biWidth", ctypes.c_long),
                    ("biHeight", ctypes.c_long), ("biPlanes", _wt.WORD),
                    ("biBitCount", _wt.WORD), ("biCompression", _wt.DWORD),
                    ("biSizeImage", _wt.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                    ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", _wt.DWORD),
                    ("biClrImportant", _wt.DWORD)]

    class _PROPERTYKEY(ctypes.Structure):
        _fields_ = [("fmtid", _GUID), ("pid", ctypes.c_ulong)]

    _IID_ImageFactory = _guid("{bcc18b79-ba16-442f-80c4-8a59c30c463b}")
    _IID_ShellItem2 = _guid("{7e9fb0d3-919f-4307-ab2e-9b1860310c93}")
    _PKEY_Duration = _PROPERTYKEY(_guid("{64440490-4C8B-11D1-8B70-080036B11A03}"), 3)

    _shell32.SHCreateItemFromParsingName.argtypes = [ctypes.c_wchar_p, _vp, _vp, _P(_vp)]
    _gdi32.GetObjectW.argtypes = [_wt.HANDLE, ctypes.c_int, _vp]
    _gdi32.GetDIBits.argtypes = [_wt.HDC, _wt.HBITMAP, _wt.UINT, _wt.UINT, _vp, _vp, _wt.UINT]
    _gdi32.DeleteObject.argtypes = [_wt.HGDIOBJ]
    _user32.GetDC.restype = _wt.HDC
    _user32.GetDC.argtypes = [_wt.HWND]
    _user32.ReleaseDC.argtypes = [_wt.HWND, _wt.HDC]

    _Release = ctypes.WINFUNCTYPE(ctypes.c_ulong, _vp)
    _GetImage = ctypes.WINFUNCTYPE(ctypes.c_long, _vp, _SIZE, ctypes.c_int, _P(_wt.HBITMAP))
    _GetUInt64 = ctypes.WINFUNCTYPE(ctypes.c_long, _vp, _P(_PROPERTYKEY), _P(ctypes.c_ulonglong))
    SHELL_OK = True
except Exception:
    SHELL_OK = False


def shell_init():
    """Call once per worker thread before shell_thumb/shell_duration."""
    if SHELL_OK:
        try:
            _ole32.CoInitialize(None)
        except Exception:
            pass


def _shell_item(path, iid):
    obj = _vp()
    p = os.path.normpath(os.path.abspath(path))     # Shell rejects '/' paths
    if _shell32.SHCreateItemFromParsingName(p, None, _byref(iid), _byref(obj)) != 0 or not obj:
        return None, None
    return obj, ctypes.cast(obj, _P(_P(_vp))).contents


def shell_thumb(path, size=256):
    """Explorer's cached thumbnail as a Pillow image, or None."""
    if not SHELL_OK:
        return None
    try:
        from PIL import Image
        obj, vt = _shell_item(path, _IID_ImageFactory)
        if obj is None:
            return None
        hbmp = _wt.HBITMAP()
        try:
            hr = _GetImage(vt[3])(obj, _SIZE(size, size), 0x8, _byref(hbmp))  # THUMBNAILONLY
        finally:
            _Release(vt[2])(obj)
        if hr != 0 or not hbmp:
            return None
        try:
            bm = _BITMAP()
            _gdi32.GetObjectW(hbmp, ctypes.sizeof(bm), _byref(bm))
            w, h = bm.bmWidth, bm.bmHeight
            bi = _BIH()
            bi.biSize, bi.biWidth, bi.biHeight = ctypes.sizeof(bi), w, -h
            bi.biPlanes, bi.biBitCount, bi.biCompression = 1, 32, 0
            buf = ctypes.create_string_buffer(w * h * 4)
            hdc = _user32.GetDC(None)
            _gdi32.GetDIBits(hdc, hbmp, 0, h, buf, _byref(bi), 0)
            _user32.ReleaseDC(None, hdc)
            return Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1).copy()
        finally:
            _gdi32.DeleteObject(hbmp)
    except Exception:
        return None


def shell_duration(path):
    """Video duration in seconds from the file's Windows properties, or None."""
    if not SHELL_OK:
        return None
    try:
        obj, vt = _shell_item(path, _IID_ShellItem2)
        if obj is None:
            return None
        val = ctypes.c_ulonglong()
        try:
            hr = _GetUInt64(vt[19])(obj, _byref(_PKEY_Duration), _byref(val))
        finally:
            _Release(vt[2])(obj)
        return val.value / 1e7 if hr == 0 and val.value else None   # 100-ns units
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════
#  Embedded mpv player window  (preferred — frame-accurate, instant)
# ═══════════════════════════════════════════════════════════════════════
class MpvPlayer(tk.Toplevel):
    def __init__(self, parent, path):
        super().__init__(parent)
        import mpv
        self.path = path
        self.title(os.path.basename(path))
        self.configure(bg="#000000")
        self.minsize(480, 320)
        center_window(self, parent)
        self._fullscreen = False

        try:
            ico = os.path.join(SCRIPT_DIR, "snapgrab.ico")
            if os.path.isfile(ico):
                self.iconbitmap(ico)
        except Exception:
            pass

        self.video = tk.Frame(self, bg="#000000")
        self.video.pack(fill="both", expand=True)
        self.update_idletasks()

        # embed mpv into the tk frame; keyboard handled by tk (below), mouse
        # by mpv's own on-screen controller (osc)
        self.mpv = mpv.MPV(
            wid=str(self.video.winfo_id()),
            vo="gpu", osc=True, keep_open="yes", ytdl=False,
            cursor_autohide=1200,
            input_default_bindings=False, input_vo_keyboard=False)
        self.mpv.play(path)

        b = {
            "<space>":        lambda e: self._c("cycle", "pause"),
            "<period>":       lambda e: self._c("frame-step"),
            "<comma>":        lambda e: self._c("frame-back-step"),
            "<Right>":        lambda e: self._c("seek", 5),
            "<Left>":         lambda e: self._c("seek", -5),
            "<Up>":           lambda e: self._vol(5),
            "<Down>":         lambda e: self._vol(-5),
            "<bracketright>": lambda e: self._speed(1.1),
            "<bracketleft>":  lambda e: self._speed(0.9),
            "<BackSpace>":    lambda e: self._speed(0),      # reset speed
            "<m>":            lambda e: self._c("cycle", "mute"),
            "<f>":            lambda e: self.toggle_fullscreen(),
            "<Escape>":       lambda e: self._exit_fs(),
        }
        for seq, fn in b.items():
            self.bind(seq, fn)
        self.video.bind("<Double-Button-1>", lambda e: self.toggle_fullscreen())
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.focus_set()

    def _c(self, *args):
        try:
            self.mpv.command(*args)
        except Exception:
            pass

    def _osd(self, text, ms):
        try:
            self.mpv.command("show-text", text, ms)
        except Exception:
            pass

    def _vol(self, delta):
        try:
            v = max(0, min(130, (self.mpv.volume or 100) + delta))
            self.mpv.volume = v
            self._osd(f"Volume {int(v)}%", 800)
        except Exception:
            pass

    def _speed(self, factor):
        try:
            self.mpv.speed = 1.0 if factor == 0 else max(0.25, min(4.0, self.mpv.speed * factor))
            self._osd(f"Speed {self.mpv.speed:.2f}x", 900)
        except Exception:
            pass

    def toggle_fullscreen(self):
        self._fullscreen = not self._fullscreen
        self.attributes("-fullscreen", self._fullscreen)

    def _exit_fs(self):
        if self._fullscreen:
            self.toggle_fullscreen()

    def _close(self):
        try:
            self.mpv.terminate()
        except Exception:
            pass
        self.destroy()


# ═══════════════════════════════════════════════════════════════════════
#  Embedded VLC player window  (fallback)
# ═══════════════════════════════════════════════════════════════════════
class Player(tk.Toplevel):
    def __init__(self, parent, path):
        super().__init__(parent)
        import vlc
        self.vlc = vlc
        self.path = path
        self.title(os.path.basename(path))
        self.configure(bg="#000000")
        self.minsize(480, 320)
        center_window(self, parent)
        self._dragging = False
        self._fullscreen = False
        self._len = 0

        try:
            ico = os.path.join(SCRIPT_DIR, "snapgrab.ico")
            if os.path.isfile(ico):
                self.iconbitmap(ico)
        except Exception:
            pass

        # video surface
        self.video = tk.Frame(self, bg="#000000")
        self.video.pack(fill="both", expand=True)

        # control bar
        self.bar = tk.Frame(self, bg=T.BG, height=52)
        self.bar.pack(fill="x", side="bottom")
        self.bar.pack_propagate(False)

        self.seek = _SeekBar(self, height=6, on_seek=self._on_seek)
        self.seek.pack(fill="x", side="bottom")

        self.play_btn = tk.Label(self.bar, text="⏸", font=("Segoe UI", 15),
                                 bg=T.BG, fg=T.WHITE, cursor="hand2", width=3)
        self.play_btn.pack(side="left", padx=(10, 2), pady=8)
        self.play_btn.bind("<Button-1>", lambda e: self.toggle_play())

        self.time_lbl = tk.Label(self.bar, text="0:00 / 0:00", font=F_SMALL,
                                 bg=T.BG, fg=T.SUB)
        self.time_lbl.pack(side="left", padx=8)

        self.fs_btn = tk.Label(self.bar, text="⛶", font=("Segoe UI", 13),
                               bg=T.BG, fg=T.SUB, cursor="hand2", width=3)
        self.fs_btn.pack(side="right", padx=(2, 10))
        self.fs_btn.bind("<Button-1>", lambda e: self.toggle_fullscreen())

        ext_btn = tk.Label(self.bar, text="Open externally", font=F_TINY,
                           bg=T.BG, fg=T.MUTED, cursor="hand2")
        ext_btn.pack(side="right", padx=6)
        ext_btn.bind("<Button-1>", lambda e: self._open_external())

        self.vol = _SeekBar(self.bar, width=90, height=6, on_seek=self._on_vol,
                            value=1.0, inline=True)
        self.vol.pack(side="right", padx=8)
        tk.Label(self.bar, text="Vol", font=F_TINY, bg=T.BG, fg=T.MUTED).pack(side="right")

        # vlc wiring
        self.inst = vlc.Instance()
        self.mp = self.inst.media_player_new()
        self.update_idletasks()
        hwnd = self.video.winfo_id()
        self.mp.set_hwnd(hwnd)
        media = self.inst.media_new(path)
        self.mp.set_media(media)
        self.mp.audio_set_volume(100)
        self.mp.play()

        self.bind("<space>", lambda e: self.toggle_play())
        self.bind("<f>", lambda e: self.toggle_fullscreen())
        self.bind("<Escape>", lambda e: self._exit_fullscreen())
        self.bind("<Left>", lambda e: self._nudge(-5))
        self.bind("<Right>", lambda e: self._nudge(5))
        self.video.bind("<Double-Button-1>", lambda e: self.toggle_fullscreen())
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(300, self._tick)
        self.focus_set()

    def toggle_play(self):
        self.mp.pause()
        self.after(60, lambda: self.play_btn.config(
            text="⏸" if self.mp.is_playing() else "▶"))

    def _nudge(self, secs):
        t = self.mp.get_time()
        if t >= 0:
            self.mp.set_time(max(0, t + secs * 1000))

    def _on_seek(self, frac):
        if self._len > 0:
            self.mp.set_time(int(frac * self._len))

    def _on_vol(self, frac):
        self.mp.audio_set_volume(int(max(0, min(1, frac)) * 100))

    def _tick(self):
        try:
            if not self.mp.get_hwnd():
                return
            self._len = self.mp.get_length()
            t = self.mp.get_time()
            if self._len > 0 and not self.seek.dragging:
                self.seek.set(t / self._len)
            self.time_lbl.config(text=f"{fmt_time(t/1000)} / {fmt_time(self._len/1000)}")
            if not self.mp.is_playing() and self.mp.get_state() == self.vlc.State.Ended:
                self.play_btn.config(text="▶")
        except Exception:
            pass
        self.after(300, self._tick)

    def toggle_fullscreen(self):
        self._fullscreen = not self._fullscreen
        self.attributes("-fullscreen", self._fullscreen)
        if self._fullscreen:
            self.bar.pack_forget()
            self.seek.pack_forget()
        else:
            self.seek.pack(fill="x", side="bottom")
            self.bar.pack(fill="x", side="bottom")

    def _exit_fullscreen(self):
        if self._fullscreen:
            self.toggle_fullscreen()

    def _open_external(self):
        try:
            os.startfile(self.path)
        except Exception:
            pass

    def _close(self):
        try:
            self.mp.stop()
            self.mp.release()
        except Exception:
            pass
        self.destroy()


class _SeekBar(tk.Canvas):
    """Click/drag progress bar (0..1). Used for seek and volume."""
    def __init__(self, parent, on_seek, height=6, width=None, value=0.0, inline=False):
        bg = T.BG if inline else "#000000"
        kw = {"height": height, "highlightthickness": 0, "bd": 0, "bg": bg}
        if width:
            kw["width"] = width
        super().__init__(parent, **kw)
        self.on_seek = on_seek
        self.value = value
        self.dragging = False
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Button-1>", self._press)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<ButtonRelease-1>", self._release)

    def set(self, v):
        self.value = max(0.0, min(1.0, v))
        self._draw()

    def _frac(self, x):
        w = self.winfo_width()
        return max(0.0, min(1.0, x / w)) if w else 0.0

    def _press(self, e):
        self.dragging = True
        self.value = self._frac(e.x)
        self._draw()

    def _drag(self, e):
        if self.dragging:
            self.value = self._frac(e.x)
            self._draw()

    def _release(self, e):
        self.dragging = False
        self.on_seek(self._frac(e.x))

    def _draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 2:
            return
        self.create_rectangle(0, h/2 - 1, w, h/2 + 1, fill=T.BORDER, outline="")
        fw = w * self.value
        self.create_rectangle(0, h/2 - 1, fw, h/2 + 1, fill=T.WHITE, outline="")
        self.create_oval(fw - 5, h/2 - 5, fw + 5, h/2 + 5, fill=T.WHITE, outline="")


# ═══════════════════════════════════════════════════════════════════════
#  Library window
# ═══════════════════════════════════════════════════════════════════════
class LibraryView(tk.Frame):
    """Embeddable library panel (a Frame, so it lives inside the main window).
    on_play(path) is optional; by default it opens the built-in Player."""
    THUMB_W, THUMB_H = 248, 140

    def __init__(self, parent, folder, on_play=None):
        super().__init__(parent, bg=T.BG)
        self.on_play = on_play
        self._imgs = {}          # keep ImageTk refs alive
        self._cards = {}         # path -> widgets
        self._stop = False
        self._gen = 0            # bumps on every reload; stale workers bail out
        # blank image at the real thumbnail size, so empty cards are the SAME
        # size as loaded ones (no size "pop" when a thumbnail arrives)
        self._placeholder = tk.PhotoImage(master=self, width=self.THUMB_W,
                                          height=self.THUMB_H)

        # folder tabs — restored from config, else the folder we were opened on
        self.folders, self.active = self._load_tabs(folder)
        self.folder = self.folders[self.active]
        self.thumb_dir = os.path.join(self.folder, ".snapgrab_thumbs")

        # toolbar
        bar = tk.Frame(self, bg=T.BG)
        bar.pack(fill="x", padx=18, pady=(10, 6))
        self.count_lbl = tk.Label(bar, text="", font=F_SMALL, bg=T.BG, fg=T.MUTED)
        self.count_lbl.pack(side="left")

        refresh = tk.Label(bar, text="⟳ Refresh", font=F_SMALL, bg=T.BG,
                           fg=T.SUB, cursor="hand2")
        refresh.pack(side="right")
        refresh.bind("<Button-1>", lambda e: self.reload())

        # tab strip
        self.tabbar = tk.Frame(self, bg=T.BG)
        self.tabbar.pack(fill="x", padx=16, pady=(0, 0))
        tk.Frame(self, bg=T.BORDER, height=1).pack(fill="x", padx=16, pady=(0, 8))

        self.path_lbl = tk.Label(self, text=self.folder, font=F_TINY, bg=T.BG,
                                 fg=T.DIM, anchor="w")
        self.path_lbl.pack(fill="x", padx=18, pady=(0, 8))

        # scrollable grid
        wrap = tk.Frame(self, bg=T.BG)
        wrap.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.canvas = tk.Canvas(wrap, bg=T.BG, highlightthickness=0, bd=0)
        sb = tk.Scrollbar(wrap, command=self.canvas.yview, width=10)
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.grid_frame = tk.Frame(self.canvas, bg=T.BG)
        self.canvas_win = self.canvas.create_window((0, 0), window=self.grid_frame, anchor="nw")
        self.grid_frame.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        # scope wheel scrolling to when the pointer is over the grid, so it
        # doesn't fight the Download view when they share one window
        self.canvas.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", self._on_wheel))
        self.canvas.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))

        self.empty_lbl = tk.Label(self.grid_frame, text="", font=F_BASE,
                                  bg=T.BG, fg=T.MUTED)

        self.bind("<Destroy>", self._on_destroy)
        self._cols = 3
        self._render_tabs()
        self.reload()

    # ── tabs ────────────────────────────────────────────────────────────
    def _config_path(self):
        return os.path.join(SCRIPT_DIR, "snapgrab_tabs.json")

    def _load_tabs(self, default_folder):
        import json
        try:
            with open(self._config_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
            folders = [d for d in data.get("folders", []) if os.path.isdir(d)]
            active = data.get("active", 0)
            # always keep the download folder available as a tab (appended so
            # the saved active index stays valid), but restore the last-viewed
            # tab like a browser rather than forcing the download folder.
            if default_folder and os.path.isdir(default_folder) and default_folder not in folders:
                folders.append(default_folder)
            if folders:
                active = active if 0 <= active < len(folders) else 0
                return folders, active
        except Exception:
            pass
        return [default_folder], 0

    def _save_tabs(self):
        import json
        try:
            with open(self._config_path(), "w", encoding="utf-8") as f:
                json.dump({"folders": self.folders, "active": self.active}, f)
        except Exception:
            pass

    def _render_tabs(self):
        for w in self.tabbar.winfo_children():
            w.destroy()
        for i, path in enumerate(self.folders):
            active = (i == self.active)
            name = os.path.basename(path.rstrip("\\/")) or path
            if len(name) > 22:
                name = name[:20] + "…"
            tab = tk.Frame(self.tabbar, bg=T.CARD if active else T.BG, cursor="hand2")
            tab.pack(side="left", padx=(0, 4))
            lbl = tk.Label(tab, text=name, font=F_SMALL,
                           bg=T.CARD if active else T.BG,
                           fg=T.TEXT if active else T.MUTED, cursor="hand2",
                           padx=12, pady=7)
            lbl.pack(side="left")
            lbl.bind("<Button-1>", lambda e, idx=i: self._select_tab(idx))
            if len(self.folders) > 1:
                x = tk.Label(tab, text="✕", font=("Segoe UI", 8),
                             bg=T.CARD if active else T.BG,
                             fg=T.SUB if active else T.DIM, cursor="hand2", padx=(2))
                x.pack(side="left", padx=(0, 8))
                x.bind("<Button-1>", lambda e, idx=i: self._close_tab(idx))
                x.bind("<Enter>", lambda e, w=x: w.config(fg=T.TEXT))
                x.bind("<Leave>", lambda e, w=x, a=active: w.config(fg=T.SUB if a else T.DIM))
            if not active:
                for wgt in (tab, lbl):
                    wgt.bind("<Enter>", lambda e, t=tab, l=lbl: (
                        t.config(bg=T.SURFACE), l.config(bg=T.SURFACE, fg=T.SUB)))
                    wgt.bind("<Leave>", lambda e, t=tab, l=lbl: (
                        t.config(bg=T.BG), l.config(bg=T.BG, fg=T.MUTED)))
        add = tk.Label(self.tabbar, text="+", font=("Segoe UI", 13), bg=T.BG,
                       fg=T.SUB, cursor="hand2", padx=10)
        add.pack(side="left", padx=(2, 0))
        add.bind("<Button-1>", lambda e: self._add_folder())
        add.bind("<Enter>", lambda e: add.config(fg=T.TEXT))
        add.bind("<Leave>", lambda e: add.config(fg=T.SUB))

    def _select_tab(self, idx):
        if idx == self.active or not (0 <= idx < len(self.folders)):
            return
        self.active = idx
        self.folder = self.folders[idx]
        self.thumb_dir = os.path.join(self.folder, ".snapgrab_thumbs")
        self.path_lbl.config(text=self.folder)
        self._save_tabs()
        self._render_tabs()
        self.reload()

    def _add_folder(self):
        from tkinter import filedialog
        d = filedialog.askdirectory(initialdir=self.folder)
        if not d:
            return
        if d in self.folders:
            self._select_tab(self.folders.index(d))
            return
        self.folders.append(d)
        self._save_tabs()
        self._select_tab(len(self.folders) - 1)

    def _close_tab(self, idx):
        if len(self.folders) <= 1:
            return
        del self.folders[idx]
        if self.active >= len(self.folders):
            self.active = len(self.folders) - 1
        elif idx < self.active:
            self.active -= 1
        self.folder = self.folders[self.active]
        self.thumb_dir = os.path.join(self.folder, ".snapgrab_thumbs")
        self.path_lbl.config(text=self.folder)
        self._save_tabs()
        self._render_tabs()
        self.reload()

    # ── grid layout ────────────────────────────────────────────────────
    def _on_canvas_resize(self, e):
        self.canvas.itemconfig(self.canvas_win, width=e.width)
        cols = max(1, e.width // (self.THUMB_W + 18))
        if cols != self._cols:
            self._cols = cols
            self._relayout()

    def _on_wheel(self, e):
        # When the grid is shorter than the window, tkinter's canvas will
        # happily "overscroll" and drift the content away from the top,
        # leaving an empty gap. Only scroll when there's real overflow;
        # otherwise keep it pinned to the top.
        bbox = self.canvas.bbox("all")
        if not bbox:
            return
        content_h = bbox[3] - bbox[1]
        if content_h <= self.canvas.winfo_height():
            self.canvas.yview_moveto(0)
            return
        self.canvas.yview_scroll(int(-e.delta / 120), "units")

    def _relayout(self):
        for i, (path, w) in enumerate(self._cards.items()):
            w["frame"].grid(row=i // self._cols, column=i % self._cols,
                            padx=9, pady=9, sticky="n")

    def _scan(self):
        try:
            files = [os.path.join(self.folder, f) for f in os.listdir(self.folder)]
        except Exception:
            return []
        vids = [f for f in files if os.path.isfile(f)
                and f.lower().endswith(VIDEO_EXTS)]
        vids.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        return vids

    def reload(self):
        self._stop = True
        self._gen += 1                # retire any worker from the previous tab
        for w in self._cards.values():
            w["frame"].destroy()
        self._cards.clear()
        self._imgs.clear()
        self.empty_lbl.grid_forget()

        vids = self._scan()
        self.count_lbl.config(text=f"{len(vids)} video{'s' if len(vids) != 1 else ''}")
        if not vids:
            self.empty_lbl.config(text="No videos in this folder yet.")
            self.empty_lbl.grid(row=0, column=0, padx=20, pady=40)
            self._reset_scroll()
            return

        # start fetching thumbnails right away, in parallel with building the
        # cards (results are only applied once the cards exist)
        self._stop = False
        threading.Thread(target=self._thumb_worker, args=(vids, self._gen),
                         daemon=True).start()
        for i, path in enumerate(vids):
            self._make_card(path, i)
        self._reset_scroll()

    def _reset_scroll(self):
        """Snap to the top now (cheap), then recompute the scroll region and
        snap again once layout has settled, so a tab switch never leaves the
        grid scrolled into empty space."""
        try:
            self.canvas.yview_moveto(0)
        except Exception:
            pass

        def snap():
            try:
                self.canvas.update_idletasks()
                self.canvas.configure(scrollregion=self.canvas.bbox("all"))
                self.canvas.yview_moveto(0)
            except Exception:
                pass
        self.after_idle(snap)

    def _make_card(self, path, i):
        frame = tk.Frame(self.grid_frame, bg=T.CARD, highlightbackground=T.BORDER,
                         highlightthickness=1)
        thumb = tk.Label(frame, bg="#000000", image=self._placeholder,
                         compound="center", text="●●●", fg=T.DIM,
                         font=("Segoe UI", 9))
        thumb.pack()
        name = os.path.basename(path)
        disp = name if len(name) <= 38 else name[:35] + "…"
        lbl = tk.Label(frame, text=disp, font=F_TINY, bg=T.CARD, fg=T.SUB,
                       wraplength=self.THUMB_W, justify="left", anchor="w")
        lbl.pack(fill="x", padx=8, pady=(5, 7))

        for wgt in (frame, thumb, lbl):
            wgt.bind("<Button-1>", lambda e, p=path: self.play(p))
            wgt.bind("<Button-3>", lambda e, p=path: self._show_ctx(e, p))
            wgt.bind("<Enter>", lambda e, f=frame: f.config(bg=T.CARD_HI))
            wgt.bind("<Leave>", lambda e, f=frame: f.config(bg=T.CARD))
        self._cards[path] = {"frame": frame, "thumb": thumb, "label": lbl}
        frame.grid(row=i // self._cols, column=i % self._cols, padx=9, pady=9, sticky="n")

    # ── thumbnails (background) ─────────────────────────────────────────
    def _thumb_worker(self, vids, gen):
        """Background: build finished thumbnails and hand them to the UI in
        batches, so a cached folder appears essentially all at once."""
        import time as _time
        shell_init()
        batch, last_flush, first = [], _time.perf_counter(), True

        def flush():
            nonlocal batch, last_flush
            if batch and gen == self._gen:
                b, batch = batch, []
                try:
                    self.after(0, lambda b=b: self._apply_batch(b, gen))
                except Exception:
                    pass
            last_flush = _time.perf_counter()

        for path in vids:
            if gen != self._gen:          # a newer tab/refresh took over
                return
            try:
                # 1) Explorer's own cache: thumbnail + duration in a few ms
                src = shell_thumb(path)
                dur = shell_duration(path)
                if src is None:
                    # 2) fallback: make our own with ffmpeg, cached as a jpg
                    if dur is None:
                        dur = probe_duration(path)
                    os.makedirs(self.thumb_dir, exist_ok=True)
                    tpath = self._thumb_path(path)
                    if not os.path.isfile(tpath):
                        ts = max(0.0, dur * 0.2) if dur else 1.0
                        subprocess.run([FFMPEG, "-y", "-ss", str(ts), "-i", path,
                                        "-frames:v", "1", "-vf",
                                        f"scale={self.THUMB_W}:-1", tpath],
                                       capture_output=True, startupinfo=_no_window(),
                                       timeout=40)
                    if not os.path.isfile(tpath):
                        continue
                    src = tpath
                batch.append((path, self._compose(src, dur)))
            except Exception:
                continue
            # hold the first batch up to 150 ms so a cached folder lands in one
            # paint; after that (slow/new folders) show progress every 80 ms
            limit = 0.15 if first else 0.08
            if batch and (_time.perf_counter() - last_flush > limit):
                flush()
                first = False
        flush()

    def _compose(self, src, dur):
        """Thread-safe: fit image into the card box and draw the duration badge."""
        from PIL import Image, ImageDraw
        im = (src if isinstance(src, Image.Image) else Image.open(src)).convert("RGB")
        im.thumbnail((self.THUMB_W, self.THUMB_H), Image.LANCZOS)
        canvas = Image.new("RGB", (self.THUMB_W, self.THUMB_H), (0, 0, 0))
        canvas.paste(im, ((self.THUMB_W - im.width) // 2, (self.THUMB_H - im.height) // 2))
        if dur:
            d = ImageDraw.Draw(canvas)
            txt = fmt_time(dur)
            d.rectangle([self.THUMB_W - 8 - 7*len(txt) - 8, self.THUMB_H - 22,
                         self.THUMB_W - 4, self.THUMB_H - 4], fill=(0, 0, 0))
            d.text((self.THUMB_W - 8 - 7*len(txt) - 4, self.THUMB_H - 20),
                   txt, fill=(240, 240, 240))
        return canvas

    def _apply_batch(self, batch, gen):
        """UI thread: turn composed images into Tk images and show them."""
        if gen != self._gen:
            return
        from PIL import ImageTk
        for path, canvas in batch:
            card = self._cards.get(path)
            if card is None:
                continue
            try:
                img = ImageTk.PhotoImage(canvas)
                self._imgs[path] = img
                card["thumb"].config(image=img, text="")
            except Exception:
                pass

    def _thumb_path(self, path):
        st = os.stat(path)
        key = f"{os.path.basename(path)}.{int(st.st_mtime)}.{st.st_size}.jpg"
        key = "".join(c if c.isalnum() or c in "._-" else "_" for c in key)
        return os.path.join(self.thumb_dir, key)

    # ── actions ─────────────────────────────────────────────────────────
    def _show_ctx(self, event, path):
        m = tk.Menu(self, tearoff=0, bg=T.CARD, fg=T.TEXT,
                    activebackground=T.CARD_HI, activeforeground=T.TEXT,
                    bd=0, font=F_SMALL)
        m.add_command(label="  Play", command=lambda: self.play(path))
        m.add_command(label="  Reveal in folder", command=lambda: self._reveal(path))
        m.add_command(label="  Open in default player",
                      command=lambda: self._open_external(path))
        m.add_separator()
        m.add_command(label="  Copy file path", command=lambda: self._copy_path(path))
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            m.grab_release()

    def _reveal(self, path):
        """Open Explorer with the file selected."""
        try:
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        except Exception:
            try:
                os.startfile(os.path.dirname(path))
            except Exception:
                pass

    def _open_external(self, path):
        try:
            os.startfile(path)
        except Exception:
            pass

    def _copy_path(self, path):
        try:
            self.clipboard_clear()
            self.clipboard_append(path)
        except Exception:
            pass

    def play(self, path):
        if self.on_play:
            self.on_play(path)
            return
        # Prefer mpv (frame-accurate + instant); fall back to VLC, then the
        # system default player.
        if MPV_OK:
            try:
                MpvPlayer(self.winfo_toplevel(), path)
                return
            except Exception:
                pass
        try:
            Player(self.winfo_toplevel(), path)
            return
        except Exception as e:
            import tkinter.messagebox as mb
            mb.showerror("SnapGrab", f"Couldn't open player:\n{e}\n\nOpening externally.")
            try:
                os.startfile(path)
            except Exception:
                pass

    def _on_destroy(self, e=None):
        if e is None or e.widget is self:
            self._stop = True
            self._gen += 1
            try:
                self.canvas.unbind_all("<MouseWheel>")
            except Exception:
                pass


def open_library(parent, folder):
    """Standalone Library window (kept for convenience; the app embeds a
    LibraryView directly)."""
    win = tk.Toplevel(parent)
    win.title("SnapGrab — Library")
    win.configure(bg=T.BG)
    win.geometry("900x640")
    win.minsize(560, 400)
    try:
        ico = os.path.join(SCRIPT_DIR, "snapgrab.ico")
        if os.path.isfile(ico):
            win.iconbitmap(ico)
    except Exception:
        pass
    LibraryView(win, folder).pack(fill="both", expand=True)
    return win
