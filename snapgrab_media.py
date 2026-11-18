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
AUDIO_EXTS = (".mp3", ".m4a", ".flac", ".wav", ".ogg", ".opus", ".aac", ".wma")
IMAGE_EXTS = (".jpg", ".jpeg", ".jfif", ".png", ".gif", ".bmp", ".webp",
              ".tif", ".tiff", ".avif", ".ico")
TEXT_EXTS = (".txt", ".md", ".log", ".csv", ".json")
DOC_EXTS = (".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt",
            ".odt", ".ods", ".odp", ".rtf") + TEXT_EXTS
# text files whose first lines are drawn on the card (csv/json are left as
# icons — they're often data exports you don't want splashed on screen)
PREVIEW_TEXT_EXTS = (".txt", ".md", ".log")
PDF_HELPER = os.path.join(SCRIPT_DIR, "snapgrab_pdf.py")
CACHE_DIR = os.path.join(os.environ.get("LOCALAPPDATA") or SCRIPT_DIR,
                         "SnapGrab", "thumbs")

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


class SlimScrollbar(tk.Canvas):
    """Minimal dark scrollbar: a thin rounded pill on a transparent track —
    no arrows, no native Windows chrome. Widens/brightens on hover or drag,
    and hides itself when everything fits. Drop-in for tk.Scrollbar
    (takes command=..., provides .set(first, last))."""
    THIN, WIDE = 4, 7
    PAD = 4
    MIN_LEN = 36

    def __init__(self, parent, command=None, orient="vertical", bg=None,
                 color="#46464e", hover="#71717a", size=12):
        self.vert = orient == "vertical"
        bg = bg or T.BG
        kw = {"width": size} if self.vert else {"height": size}
        super().__init__(parent, bg=bg, highlightthickness=0, bd=0, **kw)
        self.command = command
        self._color, self._hover = color, hover
        self._first, self._last = 0.0, 1.0
        self._hot = False
        self._drag = None
        self._pill = self.create_line(0, 0, 0, 0, fill=color, width=self.THIN,
                                      capstyle="round")
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Enter>", lambda e: self._set_hot(True))
        self.bind("<Leave>", lambda e: self._drag is None and self._set_hot(False))
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<B1-Motion>", self._motion)
        self.bind("<ButtonRelease-1>", self._release)

    # tk.Scrollbar API used by Canvas/Text yscrollcommand
    def set(self, first, last):
        self._first, self._last = float(first), float(last)
        self._draw()

    def _geom(self):
        """(track start, track length, thumb start, thumb length) in px."""
        L = self.winfo_height() if self.vert else self.winfo_width()
        track = max(1, L - 2 * self.PAD)
        span = max(0.0, min(1.0, self._last - self._first))
        tl = max(self.MIN_LEN, span * track) if span < 1 else track
        tl = min(tl, track)
        movable = track - tl
        pos = (self._first / (1 - span)) * movable if span < 1 else 0
        return self.PAD, track, self.PAD + pos, tl

    def _draw(self):
        if self._last - self._first >= 0.999:          # everything fits → hide
            self.itemconfigure(self._pill, state="hidden")
            return
        w = self.WIDE if (self._hot or self._drag is not None) else self.THIN
        _, _, a, tl = self._geom()
        r = w / 2                                       # round caps add r at each end
        mid = (self.winfo_width() if self.vert else self.winfo_height()) / 2
        b = a + tl
        if self.vert:
            self.coords(self._pill, mid, a + r, mid, max(a + r, b - r))
        else:
            self.coords(self._pill, a + r, mid, max(a + r, b - r), mid)
        self.itemconfigure(self._pill, state="normal", width=w,
                           fill=self._hover if (self._hot or self._drag is not None) else self._color)

    def _set_hot(self, on):
        self._hot = on
        self._draw()

    def _pos(self, e):
        return e.y if self.vert else e.x

    def _press(self, e):
        if not self.command or self._last - self._first >= 0.999:
            return
        start, track, a, tl = self._geom()
        p = self._pos(e)
        if a <= p <= a + tl:                            # grab the thumb
            self._drag = p - a
        else:                                           # click the track: page
            self.command("scroll", -1 if p < a else 1, "pages")
        self._draw()

    def _motion(self, e):
        if self._drag is None or not self.command:
            return
        start, track, _, tl = self._geom()
        span = self._last - self._first
        movable = max(1, track - tl)
        a = min(max(self._pos(e) - self._drag, start), start + movable)
        self.command("moveto", (a - start) / movable * (1 - span))

    def _release(self, e):
        self._drag = None
        x, y = self.winfo_pointerxy()
        inside = self.winfo_containing(x, y) is self
        self._set_hot(inside)


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


def shell_thumb(path, size=256, icon=False):
    """Explorer's cached thumbnail as a Pillow image, or None.
    icon=True returns the file type's icon instead (RGBA, with transparency)."""
    if not SHELL_OK:
        return None
    try:
        from PIL import Image
        obj, vt = _shell_item(path, _IID_ImageFactory)
        if obj is None:
            return None
        hbmp = _wt.HBITMAP()
        try:
            flags = 0x4 if icon else 0x8                 # ICONONLY / THUMBNAILONLY
            hr = _GetImage(vt[3])(obj, _SIZE(size, size), flags, _byref(hbmp))
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
            if icon:
                return Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).copy()
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
            # libmpv defaults this to "no" (unlike the mpv app): show a
            # song's embedded cover art instead of a black window
            audio_display="embedded-first",
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

    # per-kind settings: which files to show, where tabs are saved, wording
    KINDS = {
        "video": dict(exts=VIDEO_EXTS, config="snapgrab_tabs.json",
                      one="video", many="videos"),
        "music": dict(exts=AUDIO_EXTS, config="snapgrab_music_tabs.json",
                      one="song", many="songs"),
        "docs":  dict(exts=DOC_EXTS, config="snapgrab_docs_tabs.json",
                      one="doc", many="docs"),
        "images": dict(exts=IMAGE_EXTS, config="snapgrab_images_tabs.json",
                       one="image", many="images"),
    }

    def __init__(self, parent, folder, on_play=None, kind="video"):
        super().__init__(parent, bg=T.BG)
        self.on_play = on_play
        self.kind = kind if kind in self.KINDS else "video"
        self._k = self.KINDS[self.kind]
        if self.kind == "docs":
            # portrait cards in A4 proportions (210:297), so PDF pages fill them
            self.THUMB_W, self.THUMB_H = 210, 297
        elif self.kind == "images":
            # 4:3 — 16:9 screenshots/wallpapers fit with thin bars, and
            # portrait phone photos still get a usable size
            self.THUMB_W, self.THUMB_H = 248, 186
        # longest file name that fits on one line under the card
        self._name_max = 38 if self.THUMB_W >= 248 else 31
        self._note_img = None    # music: shared "no cover art" image (lazy)
        # ── virtualized grid state ──
        # Only the cards that fit on screen (+1 row above/below) exist as
        # widgets; scrolling re-points those same "slots" at other files.
        # Thumbnails live in a small LRU cache, so a 10,000-file folder costs
        # about the same as a 30-file one.
        from collections import OrderedDict
        self._files = []         # every file in the current tab, in display order
        self._slots = []         # pooled card widgets
        self._cache = OrderedDict()   # path -> PhotoImage (LRU)
        self._failed = set()     # paths that produced no thumbnail
        self._want = []          # paths the worker should make next (visible first)
        self._want_lock = threading.Lock()
        self._want_evt = threading.Event()
        self._card_w = self._card_h = 0   # measured from the first slot
        self._view_pending = False
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
        sb = SlimScrollbar(wrap, command=self.canvas.yview)

        def on_scroll(first, last):         # any view change → refill slots
            sb.set(first, last)
            self._schedule_view()
        self.canvas.configure(yscrollcommand=on_scroll)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self._press = None           # (x_root, y_root, path) of the last left-press
        self._dragged = False
        # scope wheel scrolling to when the pointer is over the grid, so it
        # doesn't fight the Download view when they share one window
        self.canvas.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", self._on_wheel))
        self.canvas.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))

        self.empty_lbl = tk.Label(self.canvas, text="", font=F_BASE,
                                  bg=T.BG, fg=T.MUTED)
        self._empty_win = self.canvas.create_window(20, 40, window=self.empty_lbl,
                                                    anchor="nw", state="hidden")

        self.bind("<Destroy>", self._on_destroy)
        self._cols = 3
        self._render_tabs()
        self.reload()

    # ── tabs ────────────────────────────────────────────────────────────
    def _config_path(self):
        return os.path.join(SCRIPT_DIR, self._k["config"])

    def _load_tabs(self, default_folder):
        import json
        try:
            with open(self._config_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
            saved = data.get("folders", [])
            folders = [d for d in saved if os.path.isdir(d)]
            active = data.get("active", 0)
            # The saved list is the user's choice — restore it exactly. (It used
            # to re-add the default folder on every launch, so a tab you closed
            # came back after a restart.) The default is only used on the very
            # first run, or if every saved folder has since been deleted.
            if folders:
                # keep the tab you were on, matched by folder (indexes shift
                # if a saved folder was deleted)
                was = saved[active] if isinstance(active, int) and 0 <= active < len(saved) else None
                active = folders.index(was) if was in folders else 0
                return folders, active
        except Exception:
            pass
        return [default_folder], 0

    @staticmethod
    def _tab_index(folder, folders):
        """Index of `folder` in `folders`, treating C:/a and C:\\A as the same
        (the folder picker returns '/', Windows paths use '\\'). -1 if absent."""
        key = os.path.normcase(os.path.normpath(folder))
        for i, f in enumerate(folders):
            if os.path.normcase(os.path.normpath(f)) == key:
                return i
        return -1

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
        # separate process — see pick_folder() for why
        pick_folder(self.winfo_toplevel(), self.folder, self._on_folder_picked,
                    title="Add a folder tab")

    def _on_folder_picked(self, d):
        if not d or not os.path.isdir(d):
            return
        i = self._tab_index(d, self.folders)
        if i >= 0:
            self._select_tab(i)
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

    # ── virtualized grid ───────────────────────────────────────────────
    PAD = 9                       # gap around each card (18 px between cards)

    def _row_h(self):
        return self._card_h + 2 * self.PAD

    def _col_w(self):
        return (self._card_w or self.THUMB_W + 6) + getattr(self, "_gap", 2 * self.PAD)

    def _fit_columns(self, width):
        """As many columns as fit with at least a 12 px gap; leftover space
        is shared out as wider gaps (max 24 px) and the rest centres the
        grid — no clipped last column, no big empty strip on the right."""
        cw = self._card_w or self.THUMB_W + 6
        avail = max(1, width - 2 * self.PAD)
        cols = max(1, (avail + 12) // (cw + 12))
        gap = min(24, (avail - cols * cw) / (cols - 1)) if cols > 1 else 0
        used = cols * cw + (cols - 1) * gap
        self._gap = gap
        self._x0 = self.PAD + max(0, (avail - used) / 2)
        return cols

    def _total_h(self):
        rows = (len(self._files) + self._cols - 1) // max(1, self._cols)
        return rows * self._row_h() if self._files else 0

    def _on_canvas_resize(self, e):
        # (the old formula forgot the card border, so the right-most column
        # was clipped by the scrollbar)
        self._cols = self._fit_columns(e.width)
        self._update_scrollregion()
        self._schedule_view()

    def _update_scrollregion(self):
        w = max(1, self.canvas.winfo_width())
        self.canvas.configure(scrollregion=(0, 0, w, max(self._total_h(),
                                                          self.canvas.winfo_height())))

    def _on_wheel(self, e):
        # Only scroll when there's real overflow; otherwise stay pinned to the
        # top (tk canvases otherwise "overscroll" and leave an empty gap).
        if self._total_h() <= self.canvas.winfo_height():
            self.canvas.yview_moveto(0)
            return
        self.canvas.yview_scroll(int(-e.delta / 120), "units")

    def _scan(self):
        out = []
        try:
            # scandir: on Windows the mtime comes with the directory listing,
            # so sorting 10,000 files costs no extra disk calls
            with os.scandir(self.folder) as it:
                for ent in it:
                    if ent.name.lower().endswith(self._k["exts"]) and ent.is_file():
                        try:
                            out.append((ent.stat().st_mtime, ent.path))
                        except OSError:
                            pass
        except Exception:
            return []
        if self.kind == "docs" and os.path.normcase(os.path.abspath(self.folder)) \
                == os.path.normcase(SCRIPT_DIR):
            # hide SnapGrab's own settings/debug files sitting beside the app
            out = [t for t in out if not os.path.basename(t[1]).lower().startswith("snapgrab_")]
        out.sort(key=lambda t: t[0], reverse=True)
        return [p for _, p in out]

    def reload(self):
        self._stop = True
        self._gen += 1                # retire any worker from the previous tab
        self._cache.clear()
        self._failed.clear()
        with self._want_lock:
            self._want = []
        self._files = self._scan()
        for s in self._slots:         # forget what each slot was showing
            s["path"] = None
        n = len(self._files)
        noun = self._k["one"] if n == 1 else self._k["many"]
        self.count_lbl.config(text=f"{n} {noun}")
        if not n:
            self.empty_lbl.config(text=f"No {self._k['many']} in this folder yet.")
            self.canvas.itemconfigure(self._empty_win, state="normal")
        else:
            self.canvas.itemconfigure(self._empty_win, state="hidden")
            self._stop = False
            threading.Thread(target=self._thumb_worker, args=(self._gen,),
                             daemon=True).start()
        self._reset_scroll()

    def _reset_scroll(self):
        """Back to the top of the (new) list and refill the visible slots."""
        try:
            self._update_scrollregion()
            self.canvas.yview_moveto(0)
        except Exception:
            pass
        self._update_view()

    # ── slots ──────────────────────────────────────────────────────────
    # Cards are drawn as canvas items (rectangle + image + text), not real
    # widgets: scrolling a canvas only redraws, while every widget is a
    # native window Windows must move one by one. Slots are reused as a
    # ring (file i → slot i % pool), so scrolling a row refills only a row.
    def _new_slot(self):
        c = self.canvas
        W, H = self.THUMB_W, self.THUMB_H
        if not self._card_w:
            import tkinter.font as tkfont
            lh = tkfont.Font(font=F_TINY).metrics("linespace")
            self._card_w = W + 6
            self._card_h = H + 6 + 5 + lh + 7
        tag = f"slot{len(self._slots)}"
        tags = (tag, "card")
        rect = c.create_rectangle(0, 0, self._card_w - 1, self._card_h - 1, fill=T.CARD,
                                  outline=T.BORDER, width=1, tags=tags, state="hidden")
        bg = c.create_rectangle(3, 3, 3 + W, 3 + H, fill="#000000", width=0,
                                tags=tags, state="hidden")
        img = c.create_image(3 + W // 2, 3 + H // 2, anchor="center", tags=tags,
                             state="hidden")
        dots = c.create_text(3 + W // 2, 3 + H // 2, text="●●●", fill=T.DIM,
                             font=("Segoe UI", 9), tags=tags, state="hidden")
        name = c.create_text(11, 3 + H + 5, anchor="nw", text="", fill=T.SUB,
                             font=F_TINY, tags=tags, state="hidden")
        slot = {"tag": tag, "rect": rect, "bg": bg, "imgitem": img, "dots": dots, "name": name,
                "path": None, "img": None, "x": 0, "y": 0, "shown": False}

        def on_ctx(e, s=slot):
            if s["path"]:
                self._show_ctx(e, s["path"])

        def on_enter(e, s=slot):
            c.itemconfigure(s["rect"], fill=T.CARD_HI)
            c.configure(cursor="hand2")

        def on_leave(e, s=slot):
            c.itemconfigure(s["rect"], fill=T.CARD)
            c.configure(cursor="")
        # open on RELEASE without moving (press + slide away = no open)
        c.tag_bind(tag, "<ButtonPress-1>", lambda e, s=slot: self._card_press(e, s))
        c.tag_bind(tag, "<ButtonRelease-1>", lambda e, s=slot: self._card_release(e, s))
        c.tag_bind(tag, "<Button-3>", on_ctx)
        c.tag_bind(tag, "<Enter>", on_enter)
        c.tag_bind(tag, "<Leave>", on_leave)
        self._slots.append(slot)
        return slot

    def _show_slot(self, slot, on):
        if slot["shown"] == on:
            return
        slot["shown"] = on
        c = self.canvas
        st = "normal" if on else "hidden"
        for k in ("rect", "bg", "imgitem", "name"):
            c.itemconfigure(slot[k], state=st)
        c.itemconfigure(slot["dots"], state=st if (on and slot["img"] is None
                                                   and slot["path"] not in self._failed) else "hidden")

    def _place_slot(self, slot, x, y):
        if (slot["x"], slot["y"]) != (x, y):
            self.canvas.move(slot["tag"], x - slot["x"], y - slot["y"])
            slot["x"], slot["y"] = x, y

    def _set_slot_image(self, slot, img):
        c = self.canvas
        slot["img"] = img
        c.itemconfigure(slot["imgitem"], image=img if img is not None else "")
        loading = img is None and slot["path"] not in self._failed
        c.itemconfigure(slot["dots"], state="normal" if (loading and slot["shown"]) else "hidden")

    def _fill_slot(self, slot, path):
        if slot["path"] != path:
            slot["path"] = path
            self.canvas.itemconfigure(slot["name"], text=self._fit_name(os.path.basename(path)))
            slot["img"] = False                 # force the image refresh below
        img = self._cache.get(path)
        if img is not None:
            self._cache.move_to_end(path)       # recently seen
        if slot["img"] is not img:
            self._set_slot_image(slot, img)

    # ── click vs drag ──────────────────────────────────────────────────
    # A click (press + release without moving) opens the file; pressing and
    # sliding off does nothing, so a stray drag never opens anything.
    CLICK_SLOP = 5               # px the mouse may wobble and still be a click

    def _card_press(self, e, slot):
        self._press = (e.x_root, e.y_root, slot["path"])
        self._dragged = False

    def _card_release(self, e, slot):
        p, self._press = self._press, None
        if self._dragged or not p or not p[2] or p[2] != slot["path"]:
            return
        if abs(e.x_root - p[0]) <= self.CLICK_SLOP and abs(e.y_root - p[1]) <= self.CLICK_SLOP:
            self.play(p[2])

    def _fit_name(self, name):
        """Cut a file name to the card's width in real pixels (a character
        count fails for wide scripts like Korean/CJK)."""
        if not hasattr(self, "_name_font"):
            import tkinter.font as tkfont
            self._name_font = tkfont.Font(font=F_TINY)
        maxw = self.THUMB_W - 10
        f = self._name_font
        if f.measure(name) <= maxw:
            return name
        lo, hi = 0, len(name)
        while lo < hi:                          # longest prefix that fits with "…"
            mid = (lo + hi + 1) // 2
            if f.measure(name[:mid] + "…") <= maxw:
                lo = mid
            else:
                hi = mid - 1
        return name[:lo].rstrip() + "…"

    def _schedule_view(self):
        if not self._view_pending:
            self._view_pending = True
            self.after_idle(self._update_view)

    def _update_view(self):
        """Point the slot ring at whatever rows are on screen right now and
        ask the worker for their thumbnails (visible first, then the next
        screen down and up, so normal scrolling never shows a blank)."""
        self._view_pending = False
        if not self.winfo_exists():
            return
        if not self._slots:
            self._new_slot()
        n, cols = len(self._files), max(1, self._cols)
        ch = max(1, self.canvas.winfo_height())
        rh = self._row_h()
        top = self.canvas.canvasy(0)
        first_row = max(0, int(top // rh) - 1)
        last_row = int((top + ch) // rh) + 1
        start = first_row * cols
        end = min(n, (last_row + 1) * cols)
        need = end - start
        if len(self._slots) < need:
            # grow the ring (keeps i % pool distinct within the window)
            while len(self._slots) < need + cols:
                self._new_slot()
        P = len(self._slots)
        used = set()
        for i in range(start, end):
            slot = self._slots[i % P]
            used.add(i % P)
            self._fill_slot(slot, self._files[i])
            self._place_slot(slot, round(getattr(self, "_x0", self.PAD) + (i % cols) * self._col_w()),
                             self.PAD + (i // cols) * rh)
            self._show_slot(slot, True)
        for j, slot in enumerate(self._slots):
            if j not in used and slot["shown"]:
                self._show_slot(slot, False)
                slot["path"] = None
        # keep roughly three screens of thumbnails in memory
        self._cache_cap = max(150, 3 * max(need, 1))
        while len(self._cache) > self._cache_cap:
            self._cache.popitem(last=False)
        # work order: on screen, then one screen below, then one above
        page = max(cols, need)
        order = (self._files[start:end] + self._files[end:end + page]
                 + self._files[max(0, start - page):start][::-1])
        want = [p for p in order if p not in self._cache and p not in self._failed]
        with self._want_lock:
            self._want = want
        if want:
            self._want_evt.set()

    def _visible_loaded(self):
        """True once every on-screen card shows its thumbnail (for tests)."""
        return all(s["img"] is not None or s["path"] in self._failed
                   for s in self._slots if s["path"] and s["shown"])

    # ── thumbnails (background) ─────────────────────────────────────────
    def _thumb_worker(self, gen):
        """Background: make thumbnails for whatever _update_view asked for,
        newest request first, and hand them to the UI in batches (the first
        screen of a cached folder lands in one paint)."""
        import time as _time
        shell_init()
        batch, last_flush, first = [], _time.perf_counter(), True

        def flush():
            nonlocal batch, last_flush, first
            if batch and gen == self._gen:
                b, batch = batch, []
                try:
                    self.after(0, lambda b=b: self._apply_batch(b, gen))
                except Exception:
                    pass
                first = False
            last_flush = _time.perf_counter()

        while gen == self._gen and not self._stop:
            with self._want_lock:
                path = self._want.pop(0) if self._want else None
            if path is None:
                flush()
                self._want_evt.wait(0.5)
                self._want_evt.clear()
                continue
            if path in self._cache or path in self._failed:
                continue
            try:
                src, badge = self._make_thumb(path)
                img = self._compose(src, badge) if src is not None else None
            except Exception:
                img = None
            batch.append((path, img))
            # hold the first batch up to 150 ms so a cached folder lands in one
            # paint; after that show progress every 80 ms
            limit = 0.15 if first else 0.08
            if _time.perf_counter() - last_flush > limit:
                flush()

    def _make_thumb(self, path):
        if self.kind == "docs":
            return self._doc_thumb(path)
        if self.kind == "images":
            return self._image_thumb(path)
        return self._media_thumb(path)

    def _media_thumb(self, path):
        """Video/music: (image or path, duration badge) — or (None, None)."""
        # 1) Explorer's own cache: thumbnail + duration in a few ms
        src = shell_thumb(path)
        dur = shell_duration(path)
        if src is None and self.kind == "music":
            # no embedded cover art: draw a music-note card instead
            # (skip ffmpeg — there's no frame to grab from audio)
            src = self._note_image()
        elif src is None:
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
                return None, None
            src = tpath
        return src, (fmt_time(dur) if dur else None)

    # ── images ──────────────────────────────────────────────────────────
    def _image_thumb(self, path):
        """Images: Windows' thumbnail cache first (a few ms); otherwise decode
        with Pillow at reduced size (JPEG 'draft' decodes at 1/2–1/8 scale)."""
        badge = "GIF" if path.lower().endswith(".gif") else None
        im = shell_thumb(path)
        if im is not None:
            return im, badge
        from PIL import Image, ImageOps
        with Image.open(path) as src:
            try:
                src.draft("RGB", (self.THUMB_W * 2, self.THUMB_H * 2))
            except Exception:
                pass
            im = ImageOps.exif_transpose(src)
            im.thumbnail((self.THUMB_W * 2, self.THUMB_H * 2))
            return _flatten(im), badge

    # ── docs ────────────────────────────────────────────────────────────
    def _doc_thumb(self, path):
        """Docs: (cover image, type badge). PDFs get their first page,
        .txt/.md/.log their first lines, everything else Windows' preview
        or the file-type icon."""
        ext = os.path.splitext(path)[1].lower()
        kind = ext[1:].upper()
        if ext == ".pdf":
            im, pages = self._pdf_cover(path)
            if im is not None:
                return im, f"{kind} · {pages}p" if pages else kind
        elif ext in PREVIEW_TEXT_EXTS:
            im = self._text_cover(path)
            if im is not None:
                return im, kind
        im = shell_thumb(path)                    # e.g. Office's own previews
        if im is not None:
            return im, kind
        return self._icon_tile(path), kind

    def _pdf_cover(self, path):
        """First page via pdfium, cached as a jpg in %LOCALAPPDATA%\\SnapGrab
        (keyed by path + size + mtime, so edits re-render). (image, pages)."""
        import hashlib
        from PIL import Image
        st = os.stat(path)
        # card height is in the key so a size change re-renders crisp covers
        key = hashlib.sha1(f"{os.path.normcase(path)}|{st.st_size}|{int(st.st_mtime)}"
                           f"|{self.THUMB_H}".encode("utf-8", "replace")).hexdigest()
        os.makedirs(CACHE_DIR, exist_ok=True)
        hits = [f for f in os.listdir(CACHE_DIR) if f.startswith(key)]
        if hits:                                  # name: <key>.<pages>.jpg
            try:
                pages = int(hits[0].split(".")[1])
                return Image.open(os.path.join(CACHE_DIR, hits[0])).convert("RGB"), pages
            except Exception:
                pass
        try:
            import pypdfium2 as pdfium
        except Exception:
            return None, 0
        doc = pdfium.PdfDocument(path)
        try:
            pages = len(doc)
            page = doc[0]
            _w, h = page.get_size()
            im = page.render(scale=(self.THUMB_H * 2) / max(h, 1)).to_pil().convert("RGB")
        finally:
            doc.close()
        try:
            im.save(os.path.join(CACHE_DIR, f"{key}.{pages}.jpg"), quality=85)
        except Exception:
            pass
        return im, pages

    def _text_cover(self, path):
        """The first lines of a text file, drawn small like a page preview."""
        from PIL import Image, ImageDraw, ImageFont
        head = read_text(path, 1500)
        if head is None:
            return None
        W, H = self.THUMB_W, self.THUMB_H
        im = Image.new("RGB", (W, H), (21, 21, 23))
        d = ImageDraw.Draw(im)
        try:
            font = ImageFont.truetype("consola.ttf", 10)
        except Exception:
            font = ImageFont.load_default()
        y = 10
        rows, cols = (H - 34) // 12, (W - 24) // 6     # fill the card, keep badge clear
        for line in head.replace("\t", "    ").splitlines()[:rows]:
            d.text((12, y), line[:cols], font=font, fill=(161, 161, 170))
            y += 12
        return im

    def _icon_tile(self, path):
        """The file type's Windows icon on a dark tile — but only if Windows
        has a real large icon; tiny 16-32 px ones (drawn small inside a big
        empty frame) look broken scaled up, so those get a drawn page glyph."""
        from PIL import Image, ImageDraw
        W, H = self.THUMB_W, self.THUMB_H
        tile = Image.new("RGB", (W, H), (26, 26, 30))
        ic = shell_thumb(path, size=256, icon=True)
        box = ic.getchannel("A").getbbox() if ic is not None else None
        if box and (box[2] - box[0]) >= 96:
            ic = ic.crop(box)
            ic.thumbnail((72, 72), Image.LANCZOS)
            tile.paste(ic, ((W - ic.width) // 2, (H - ic.height) // 2), ic)
            return tile
        # minimal page with a folded corner
        d = ImageDraw.Draw(tile)
        pw, ph, fold = 52, 68, 14
        x0, y0 = (W - pw) // 2, (H - ph) // 2
        line = (82, 82, 91)
        d.polygon([(x0, y0), (x0 + pw - fold, y0), (x0 + pw, y0 + fold),
                   (x0 + pw, y0 + ph), (x0, y0 + ph)], fill=(34, 34, 39), outline=line)
        d.line([(x0 + pw - fold, y0), (x0 + pw - fold, y0 + fold),
                (x0 + pw, y0 + fold)], fill=line)
        for i in range(4):
            yy = y0 + 26 + i * 9
            d.line([(x0 + 10, yy), (x0 + pw - (10 if i < 3 else 22), yy)], fill=line)
        return tile

    def _note_image(self):
        """Thread-safe: a plain dark tile with a ♪, for songs without art."""
        if self._note_img is None:
            from PIL import Image, ImageDraw, ImageFont
            im = Image.new("RGB", (self.THUMB_W, self.THUMB_H), (26, 26, 30))
            d = ImageDraw.Draw(im)
            try:
                font = ImageFont.truetype("seguisym.ttf", 56)
            except Exception:
                font = ImageFont.load_default()
            d.text((self.THUMB_W // 2, self.THUMB_H // 2), "♪", font=font,
                   fill=(113, 113, 122), anchor="mm")
            self._note_img = im
        return self._note_img

    def _compose(self, src, badge):
        """Thread-safe: fit image into the card box and draw the corner badge
        (a duration like "3:25", or a doc type like "PDF · 13p")."""
        from PIL import Image, ImageDraw
        im = (src if isinstance(src, Image.Image) else Image.open(src)).convert("RGB")
        im.thumbnail((self.THUMB_W, self.THUMB_H), Image.LANCZOS)
        canvas = Image.new("RGB", (self.THUMB_W, self.THUMB_H), (0, 0, 0))
        canvas.paste(im, ((self.THUMB_W - im.width) // 2, (self.THUMB_H - im.height) // 2))
        if badge:
            d = ImageDraw.Draw(canvas)
            txt = badge
            d.rectangle([self.THUMB_W - 8 - 7*len(txt) - 8, self.THUMB_H - 22,
                         self.THUMB_W - 4, self.THUMB_H - 4], fill=(0, 0, 0))
            d.text((self.THUMB_W - 8 - 7*len(txt) - 4, self.THUMB_H - 20),
                   txt, fill=(240, 240, 240))
        return canvas

    def _apply_batch(self, batch, gen):
        """UI thread: turn composed images into Tk images and show them."""
        if gen != self._gen or not self.winfo_exists():
            return
        from PIL import ImageTk
        showing = {s["path"]: s for s in self._slots if s["path"]}
        for path, pil in batch:
            if pil is None:
                self._failed.add(path)
                s = showing.get(path)
                if s is not None:
                    self._set_slot_image(s, None)      # hides the ●●●
                continue
            try:
                img = ImageTk.PhotoImage(pil)
            except Exception:
                continue
            self._cache[path] = img
            s = showing.get(path)
            if s is not None:
                self._set_slot_image(s, img)
        cap = getattr(self, "_cache_cap", 150)
        visible = set(showing)
        while len(self._cache) > cap:        # evict least-recently-seen, never on-screen
            old = next(iter(self._cache))
            if old in visible:
                self._cache.move_to_end(old)
                if all(p in visible for p in self._cache):
                    break
                continue
            self._cache.popitem(last=False)

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
        docs = self.kind == "docs"
        m.add_command(label="  Open" if docs else "  Play",
                      command=lambda: self.play(path))
        m.add_command(label="  Reveal in folder", command=lambda: self._reveal(path))
        m.add_command(label="  Open in default app" if docs else "  Open in default player",
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
        if self.kind == "docs":
            self._open_doc(path)
            return
        if self.kind == "images":
            try:
                ImageViewer(self.winfo_toplevel(), list(self._files),
                            self._files.index(path))
            except Exception:
                self._open_external(path)
            return
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
            mb.showerror("Pawlder", f"Couldn't open player:\n{e}\n\nOpening externally.")
            try:
                os.startfile(path)
            except Exception:
                pass

    def _open_doc(self, path):
        """PDF → SnapGrab's PDF window; text → built-in text viewer;
        anything else (Word, Excel, …) → its normal app."""
        ext = os.path.splitext(path)[1].lower()
        top = self.winfo_toplevel()
        if ext == ".pdf" and open_pdf(top, path):
            # first PDF starts the viewer (~1 s); later ones reuse it (fast)
            try:
                top.config(cursor="watch")
                top.after(700, lambda: top.config(cursor=""))
            except Exception:
                pass
            return
        if ext in TEXT_EXTS:
            try:
                TextViewer(top, path)
                return
            except Exception:
                pass
        self._open_external(path)

    def _on_destroy(self, e=None):
        if e is None or e.widget is self:
            self._stop = True
            self._gen += 1
            self._want_evt.set()          # wake the worker so it can exit
            try:
                self.canvas.unbind_all("<MouseWheel>")
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════════════
#  Docs: PDF window (separate process) + plain-text viewer
# ═══════════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════
#  Folder picker in its own process
#  Windows' folder dialog is Explorer running inside the calling program:
#  it loads shell add-ons (Dropbox, Google Drive, Adobe CoreSync, network
#  providers) onto the UI thread. Two real "Not Responding" hangs had the
#  dialog open with those loaded. Running it in a tiny helper process means
#  a stalled add-on can only freeze the picker — never SnapGrab.
# ═══════════════════════════════════════════════════════════════════════
_PICKER_SRC = r"""
import sys, tkinter as tk
from tkinter import filedialog
init, cx, cy, title, out = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4], sys.argv[5]
r = tk.Tk()
r.overrideredirect(True)
r.attributes('-alpha', 0.0)
r.geometry('1x1+%d+%d' % (cx, cy))   # invisible owner on SnapGrab's monitor
r.update(); r.lift(); r.focus_force()
try:
    ico = sys.argv[6]
    if ico: r.iconbitmap(ico)
except Exception:
    pass
d = filedialog.askdirectory(parent=r, initialdir=init or None, title=title, mustexist=True)
with open(out, 'w', encoding='utf-8') as f:
    f.write(d or '')
"""
_picker_busy = False


def pick_folder(parent, initialdir, on_done, title="Choose a folder"):
    """Show the folder picker without blocking SnapGrab. Calls on_done(path)
    on the UI thread when a folder is chosen (not called on cancel)."""
    global _picker_busy
    if _picker_busy:                  # one picker at a time
        return
    import tempfile
    try:
        cx = parent.winfo_rootx() + parent.winfo_width() // 2
        cy = parent.winfo_rooty() + parent.winfo_height() // 3
    except Exception:
        cx = cy = 200
    fd, out = tempfile.mkstemp(prefix="snapgrab_pick_", suffix=".txt")
    os.close(fd)
    ico = os.path.join(SCRIPT_DIR, "snapgrab.ico")
    try:
        # no startupinfo=_no_window(): SW_HIDE would hide the dialog itself
        proc = subprocess.Popen([_pythonw(), "-c", _PICKER_SRC, initialdir or "",
                                 str(cx), str(cy), title, out,
                                 ico if os.path.isfile(ico) else ""])
    except Exception:
        # couldn't start the helper: fall back to the in-process dialog
        try:
            os.remove(out)
        except Exception:
            pass
        from tkinter import filedialog
        d = filedialog.askdirectory(initialdir=initialdir, title=title)
        if d:
            on_done(d)
        return
    _picker_busy = True

    def poll():
        global _picker_busy
        if proc.poll() is None:
            try:
                parent.after(120, poll)
            except Exception:             # parent window gone
                _picker_busy = False
            return
        _picker_busy = False
        try:
            with open(out, "r", encoding="utf-8") as f:
                d = f.read().strip()
        except Exception:
            d = ""
        try:
            os.remove(out)
        except Exception:
            pass
        if d:
            on_done(d)
    parent.after(120, poll)


def read_text(path, limit):
    """Up to `limit` characters of a text file, honouring UTF-8/UTF-16 byte
    order marks (Windows tools like installers often write UTF-16 logs).
    None if unreadable."""
    try:
        with open(path, "rb") as f:
            raw = f.read(limit * 2 + 4)
    except Exception:
        return None
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        enc = "utf-16"
    elif raw.startswith(b"\xef\xbb\xbf"):
        enc = "utf-8-sig"
    else:
        enc = "utf-8"
    return raw.decode(enc, errors="replace")[:limit]


def _pythonw():
    """pythonw.exe beside the running interpreter (no console window)."""
    exe = sys.executable or "pythonw"
    if exe.lower().endswith("python.exe"):
        w = exe[:-len("python.exe")] + "pythonw.exe"
        if os.path.isfile(w):
            return w
    return exe


def open_pdf(parent, path):
    """Open a PDF in SnapGrab's Edge-engine viewer. Returns False if it
    couldn't be launched (caller falls back to the default app)."""
    if not os.path.isfile(PDF_HELPER):
        return False
    try:
        geo = [parent.winfo_rootx(), parent.winfo_rooty(),
               parent.winfo_width(), parent.winfo_height()]
    except Exception:
        geo = []
    try:
        # we're the foreground app (the user just clicked): let the viewer
        # process bring its window to the front
        ctypes.windll.user32.AllowSetForegroundWindow(-1)   # ASFW_ANY
    except Exception:
        pass

    def work():
        global _pdf_launched
        import time as _t
        # 1) a viewer is already running (maybe hidden) → just hand it the file.
        #    If we launched one moments ago and it's STILL starting up, give it
        #    up to 6 s to begin listening; if it already exited, don't wait.
        t0 = _t.time()
        while True:
            if _pdf_send(path, geo):
                return
            starting = (_pdf_launched is not None and _pdf_launched.poll() is None
                        and not _pdf_viewer_pid())
            if not starting or _t.time() - t0 > 6:
                break
            _t.sleep(0.1)
        # 2) none running → start one (it becomes the shared viewer)
        try:
            # NOTE: no startupinfo=_no_window() — SW_HIDE would be applied to
            # the viewer's first window and keep it invisible.
            _pdf_launched = subprocess.Popen(
                [_pythonw(), PDF_HELPER, path] + [str(v) for v in geo]
                + [str(os.getpid())], cwd=SCRIPT_DIR)
        except Exception:
            try:
                os.startfile(path)
            except Exception:
                pass
    threading.Thread(target=work, daemon=True).start()
    return True


# must match snapgrab_pdf.py
_PDF_PIPE = r"\\.\pipe\snapgrab-pdf-" + "".join(
    c for c in (os.environ.get("USERNAME") or "user") if c.isalnum())
_PDF_AUTH = b"snapgrab-pdf-v1"
_pdf_launched = None              # Popen of the viewer we last started


_PDF_PIDFILE = os.path.join(os.environ.get("LOCALAPPDATA") or SCRIPT_DIR,
                            "SnapGrab", "pdfviewer.pid")


def _pdf_viewer_pid():
    try:
        with open(_PDF_PIDFILE) as f:
            return int(f.read().strip())
    except Exception:
        return 0


def _pdf_viewer_hung(pid):
    """True if any window of the viewer process is frozen ("Not Responding")."""
    if not pid:
        return False
    from ctypes import wintypes
    u = ctypes.windll.user32
    u.IsHungAppWindow.argtypes = [wintypes.HWND]
    hung = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(h, _):
        p = wintypes.DWORD()
        u.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and u.IsWindowVisible(h) and u.IsHungAppWindow(h):
            hung.append(h)
        return True
    u.EnumWindows(cb, 0)
    return bool(hung)


def _kill_pdf_viewer(pid):
    """End a frozen viewer — only if that pid really is a Python process
    (never kill something else that reused the number)."""
    if not pid or pid == os.getpid():
        return
    k = ctypes.windll.kernel32
    h = k.OpenProcess(0x0001 | 0x1000, False, pid)   # TERMINATE | QUERY_LIMITED
    if not h:
        return
    try:
        buf = ctypes.create_unicode_buffer(260)
        n = ctypes.c_ulong(260)
        if k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)) and \
                os.path.basename(buf.value).lower() in ("pythonw.exe", "python.exe"):
            k.TerminateProcess(h, 1)
    finally:
        k.CloseHandle(h)
    try:
        os.remove(_PDF_PIDFILE)
    except Exception:
        pass


def _pdf_send(path, geo):
    """Hand a PDF to the running viewer. False if none is listening — or if
    it is frozen, in which case it's closed so a fresh one gets started."""
    pid = _pdf_viewer_pid()
    if _pdf_viewer_hung(pid):
        _kill_pdf_viewer(pid)
        return False
    try:
        from multiprocessing.connection import Client
        c = Client(_PDF_PIPE, family="AF_PIPE", authkey=_PDF_AUTH)
    except Exception:
        return False
    try:
        c.send({"open": path, "geo": geo})
        # the viewer answers once the PDF is on screen (~0.1-1.5 s)
        if c.poll(8):
            return c.recv() == "ok"
        _kill_pdf_viewer(pid)            # no answer → frozen: replace it
        return False
    except Exception:
        return False
    finally:
        try:
            c.close()
        except Exception:
            pass


class TextViewer(tk.Toplevel):
    """Read-only viewer for .txt/.md/.log/.csv/.json (first 2 MB)."""
    LIMIT = 2 * 1024 * 1024

    def __init__(self, parent, path):
        super().__init__(parent)
        self.title(os.path.basename(path))
        self.configure(bg=T.BG)
        self.minsize(420, 300)
        center_window(self, parent, wfrac=0.56, hfrac=0.74)
        try:
            ico = os.path.join(SCRIPT_DIR, "snapgrab.ico")
            if os.path.isfile(ico):
                self.iconbitmap(ico)
        except Exception:
            pass

        body = read_text(path, self.LIMIT + 1) or ""
        cut = len(body) > self.LIMIT
        if cut:
            body = body[:self.LIMIT]

        # prose wraps; data files (csv/json/log) keep their lines intact
        wrap = "word" if path.lower().endswith((".txt", ".md")) else "none"
        frame = tk.Frame(self, bg=T.BG)
        frame.pack(fill="both", expand=True)
        self.text = tk.Text(frame, bg=T.SURFACE, fg=T.TEXT, insertbackground=T.TEXT,
                            selectbackground="#3f3f46", relief="flat", bd=0,
                            padx=18, pady=14, wrap=wrap, font=("Consolas", 10),
                            undo=False)
        ys = SlimScrollbar(frame, command=self.text.yview, bg=T.SURFACE)
        self.text.configure(yscrollcommand=ys.set)
        ys.pack(side="right", fill="y")
        if wrap == "none":
            xs = SlimScrollbar(frame, orient="horizontal", command=self.text.xview,
                               bg=T.SURFACE)
            self.text.configure(xscrollcommand=xs.set)
            xs.pack(side="bottom", fill="x")
        self.text.pack(side="left", fill="both", expand=True)
        self.text.insert("1.0", body)
        if cut:
            self.text.insert("end", "\n\n— showing the first 2 MB · open in its "
                                    "default app for the rest —")
        self.text.mark_set("insert", "1.0")

        # read-only, but selection + copy still work
        def guard(e):
            if (e.state & 0x4) and e.keysym.lower() in ("c", "a"):
                if e.keysym.lower() == "a":
                    self.text.tag_add("sel", "1.0", "end")
                    return "break"
                return None
            if e.keysym in ("Up", "Down", "Left", "Right", "Prior", "Next",
                            "Home", "End"):
                return None
            return "break"
        self.text.bind("<Key>", guard)
        self.text.bind("<<Paste>>", lambda e: "break")
        self.text.bind("<<Cut>>", lambda e: "break")
        self.bind("<Escape>", lambda e: self.destroy())
        self.text.focus_set()


# ═══════════════════════════════════════════════════════════════════════
#  Image viewer — in-process (no engine to start), neighbours preloaded
# ═══════════════════════════════════════════════════════════════════════
def _flatten(im, bg=(17, 17, 19)):
    """Any Pillow image → RGB; transparency composited over a dark grey."""
    from PIL import Image
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        base = Image.new("RGB", im.size, bg)
        base.paste(im, mask=im.getchannel("A"))
        return base
    return im.convert("RGB") if im.mode != "RGB" else im


def _decode(path, box=None):
    """Open + orient an image → (image, displayed full-res size).
    box=(w, h): only a window-sized copy is needed — JPEGs decode at reduced
    scale (much faster) and the result is pre-scaled to fit the box."""
    from PIL import Image, ImageOps
    with Image.open(path) as src:
        size = src.size
        try:            # EXIF orientation 5–8 = stored sideways: swap w/h
            if src.getexif().get(0x0112, 1) in (5, 6, 7, 8):
                size = (size[1], size[0])
        except Exception:
            pass
        if box:
            try:
                src.draft("RGB", box)
            except Exception:
                pass
        im = ImageOps.exif_transpose(src)
        im.load()
        im = _flatten(im)
    if box:
        # pre-scale to fit the window here (worker thread) — down for big
        # photos, UP for small ones — so showing it on the UI thread is just
        # "make a PhotoImage", no big resize
        from PIL import Image
        s = min(box[0] / im.width, box[1] / im.height, 8.0)
        if abs(s - 1.0) > 0.01:
            im = im.resize((max(1, round(im.width * s)), max(1, round(im.height * s))),
                           Image.LANCZOS, reducing_gap=2.0 if s < 1 else None)
    return im, size


class ImageViewer(tk.Toplevel):
    """←/→ next/prev (preloaded), wheel = zoom at cursor, drag = pan,
    0 = fit, 1 = 100 %, F / double-click = fullscreen, Esc = close."""
    BG = "#0b0b0d"

    def __init__(self, parent, files, index):
        super().__init__(parent)
        self.configure(bg=self.BG)
        self.minsize(480, 320)
        # big "photo pop-up" (players use 72 %; photos want the screen)
        # (85 % tall: at 90 % the title bar pushed the bottom under the taskbar)
        center_window(self, parent, wfrac=0.92, hfrac=0.85)
        try:
            ico = os.path.join(SCRIPT_DIR, "snapgrab.ico")
            if os.path.isfile(ico):
                self.iconbitmap(ico)
        except Exception:
            pass
        self.files, self.idx = files, index
        self.cv = tk.Canvas(self, bg=self.BG, highlightthickness=0, bd=0)
        self.cv.pack(fill="both", expand=True)
        self._img_item = self.cv.create_image(0, 0, anchor="center")
        self._osd = self.cv.create_text(14, 0, anchor="sw", fill="#71717a",
                                        font=("Segoe UI", 9))
        self._tk = None            # current PhotoImage
        self._pre = {}             # path -> (screen-size PIL image, original size)
        self._full = None          # (path, full-res PIL image) for zooming
        self._anim = None          # after-id for GIF frames
        self._frames = None
        self.zoom = None           # None = fit to window, else scale vs full-res
        self.cx = self.cy = 0.0    # image point at the window centre (full-res px)
        self._fullscreen = False
        self._resize_job = None
        self._lock = threading.Lock()

        b = {"<Left>": lambda e: self.step(-1), "<Right>": lambda e: self.step(1),
             "<Home>": lambda e: self.go(0), "<End>": lambda e: self.go(len(self.files) - 1),
             "<Escape>": self._esc, "<f>": lambda e: self._toggle_fs(),
             "<F11>": lambda e: self._toggle_fs(), "<Key-0>": lambda e: self._fit(),
             "<Key-1>": lambda e: self._actual(), "<plus>": lambda e: self._zoom_by(1.25),
             "<equal>": lambda e: self._zoom_by(1.25), "<minus>": lambda e: self._zoom_by(0.8)}
        for k, fn in b.items():
            self.bind(k, fn)
        self.cv.bind("<MouseWheel>", self._on_wheel)
        self.cv.bind("<Double-Button-1>", lambda e: self._toggle_fs())
        self.cv.bind("<ButtonPress-1>", self._drag_start)
        self.cv.bind("<B1-Motion>", self._drag)
        self.cv.bind("<Configure>", self._on_resize)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.update_idletasks()
        self.go(index)
        self.focus_force()

    # ── navigation ───────────────────────────────────────────────────────
    def _view_box(self):
        return max(64, self.cv.winfo_width()), max(64, self.cv.winfo_height())

    def step(self, d):
        if self.files:
            self.go((self.idx + d) % len(self.files))

    def go(self, i):
        self._stop_anim()
        self.idx = i
        path = self.files[i]
        self.zoom = None
        with self._lock:
            got = self._pre.get(path)
        try:
            if got is None:
                got = _decode(path, self._view_box())
                with self._lock:
                    self._pre[path] = got
            self._shown, self._orig = got
        except Exception:
            self._shown, self._orig = None, (0, 0)
        self._full = None
        self._render()
        self._maybe_animate(path)
        self._prefetch(i)

    def _prefetch(self, i):
        """Decode the neighbours (and keep only them) in the background, so
        ←/→ shows the next image without waiting."""
        n = len(self.files)
        keep = {self.files[(i + d) % n] for d in (-1, 0, 1)}
        with self._lock:
            for p in list(self._pre):
                if p not in keep:
                    del self._pre[p]
        box = self._view_box()
        todo = [self.files[(i + 1) % n], self.files[(i - 1) % n]]

        def work():
            for p in todo:
                with self._lock:
                    if p in self._pre:
                        continue
                try:
                    got = _decode(p, box)
                except Exception:
                    continue
                with self._lock:
                    if p in keep:
                        self._pre[p] = got
        threading.Thread(target=work, daemon=True).start()

    # ── drawing ──────────────────────────────────────────────────────────
    def _fit_scale(self):
        """Fill the window — small images (e.g. a 920 px screenshot) are
        scaled UP too, so the picture is the window, not a stamp in it.
        (Press 1 for true 100 % size.)"""
        vw, vh = self._view_box()
        w, h = self._orig
        return min(vw / max(w, 1), vh / max(h, 1), 8.0)

    def _render(self, quality=True):
        from PIL import Image, ImageTk
        vw, vh = self._view_box()
        path = self.files[self.idx]
        if self._shown is None:
            self.cv.itemconfigure(self._img_item, image="")
            self._set_osd(f"{os.path.basename(path)}  ·  can't open this image")
            self.title(os.path.basename(path))
            return
        W, H = self._orig
        if self.zoom is None:
            s = self._fit_scale()
            tw, th = max(1, round(W * s)), max(1, round(H * s))
            src = self._shown
            if src.width < tw - 2 and src.size != (W, H):
                # window got bigger than the pre-scaled copy (e.g. fullscreen):
                # re-decode at the new size rather than upscale a small copy
                try:
                    src, _ = _decode(path, (vw, vh))
                    self._shown = src
                    with self._lock:
                        self._pre[path] = (src, self._orig)
                except Exception:
                    pass
            if abs(src.width - tw) <= 2 and abs(src.height - th) <= 2:
                out = src                     # already window-sized (pre-scaled)
            else:
                out = src.resize((tw, th), Image.LANCZOS if quality else Image.BILINEAR,
                                 reducing_gap=2.0)
            pos = (vw / 2, vh / 2)
        else:
            s = self.zoom
            # take pixels from the full-res copy if ready, else the screen copy
            if self._full and self._full[0] == path:
                src, k = self._full[1], 1.0
            else:
                src = self._shown
                k = src.width / max(W, 1)
            hw, hh = vw / (2 * s), vh / (2 * s)          # half view in full-res px
            x0, y0 = max(0, self.cx - hw), max(0, self.cy - hh)
            x1, y1 = min(W, self.cx + hw), min(H, self.cy + hh)
            box = (int(x0 * k), int(y0 * k), max(int(x0 * k) + 1, int(x1 * k)),
                   max(int(y0 * k) + 1, int(y1 * k)))
            crop = src.crop(box)
            tw, th = max(1, round((x1 - x0) * s)), max(1, round((y1 - y0) * s))
            rs = Image.NEAREST if s >= 3 else (Image.LANCZOS if quality else Image.BILINEAR)
            out = crop.resize((tw, th), rs)
            # where that crop sits on screen
            pos = (vw / 2 + ((x0 + x1) / 2 - self.cx) * s,
                   vh / 2 + ((y0 + y1) / 2 - self.cy) * s)
        self._tk = ImageTk.PhotoImage(out)
        self.cv.itemconfigure(self._img_item, image=self._tk)
        self.cv.coords(self._img_item, *pos)
        pct = round((self.zoom or self._fit_scale()) * 100)
        info = (f"{self.idx + 1} / {len(self.files)}   ·   {W} × {H}   ·   {pct}%")
        self._set_osd(info)
        self.title(f"{os.path.basename(path)}  —  {self.idx + 1} / {len(self.files)}")

    def _set_osd(self, text):
        """Small info pill (index · size · zoom) that shows on change and
        fades after 1.6 s — never a permanent overlay."""
        cv = self.cv
        if not hasattr(self, "_osd_bg"):
            self._osd_bg = cv.create_rectangle(0, 0, 0, 0, fill="#000000",
                                               outline="", stipple="")
            self._osd_job = None
        cv.itemconfigure(self._osd, text=text, fill="#d4d4d8", state="normal")
        cv.coords(self._osd, 22, self._view_box()[1] - 18)
        x0, y0, x1, y1 = cv.bbox(self._osd)
        cv.coords(self._osd_bg, x0 - 8, y0 - 4, x1 + 8, y1 + 4)
        cv.itemconfigure(self._osd_bg, state="normal")
        cv.tag_raise(self._osd_bg)
        cv.tag_raise(self._osd)
        if self._osd_job:
            self.after_cancel(self._osd_job)

        def hide():
            self._osd_job = None
            cv.itemconfigure(self._osd, state="hidden")
            cv.itemconfigure(self._osd_bg, state="hidden")
        self._osd_job = self.after(1600, hide)

    def _on_resize(self, e):
        if self._resize_job:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(60, lambda: (self._render(), self._restart_anim()))

    # ── zoom / pan ───────────────────────────────────────────────────────
    def _need_full(self):
        """Load the full-resolution image in the background the first time
        the user zooms (the screen-size copy is enough until then)."""
        path = self._full_path = self.files[self.idx]
        if (self._full and self._full[0] == path) or getattr(self, "_full_loading", None) == path:
            return
        if self._shown is not None and self._shown.size == tuple(self._orig):
            self._full = (path, self._shown)       # already full resolution
            return
        self._full_loading = path

        def work():
            try:
                im, _ = _decode(path)
            except Exception:
                return
            def done():
                self._full_loading = None
                if self.files[self.idx] == path:
                    self._full = (path, im)
                    if self.zoom is not None:
                        self._render()
            try:
                self.after(0, done)
            except Exception:
                pass
        threading.Thread(target=work, daemon=True).start()

    def _zoom_by(self, f, at=None):
        if self._shown is None or self._frames:
            return                                      # no zoom on animations
        W, H = self._orig
        cur = self.zoom or self._fit_scale()
        new = max(self._fit_scale(), min(cur * f, 16.0))
        vw, vh = self._view_box()
        if self.zoom is None:
            self.cx, self.cy = W / 2, H / 2
        if at is not None:              # keep the point under the cursor still
            ix = self.cx + (at[0] - vw / 2) / cur
            iy = self.cy + (at[1] - vh / 2) / cur
            self.cx = ix - (at[0] - vw / 2) / new
            self.cy = iy - (at[1] - vh / 2) / new
        if new <= self._fit_scale() + 1e-6:
            self.zoom = None
        else:
            self.zoom = new
            self._clamp()
            self._need_full()
        self._render(quality=False)
        self._schedule_sharp()

    def _schedule_sharp(self):
        # fast BILINEAR while zooming/dragging; one sharp LANCZOS pass after
        if getattr(self, "_sharp_job", None):
            self.after_cancel(self._sharp_job)
        self._sharp_job = self.after(140, self._render)

    def _clamp(self):
        W, H = self._orig
        vw, vh = self._view_box()
        s = self.zoom or 1
        hw, hh = vw / (2 * s), vh / (2 * s)
        self.cx = W / 2 if hw * 2 >= W else min(max(self.cx, hw), W - hw)
        self.cy = H / 2 if hh * 2 >= H else min(max(self.cy, hh), H - hh)

    def _on_wheel(self, e):
        self._zoom_by(1.25 if e.delta > 0 else 0.8, at=(e.x, e.y))

    def _fit(self):
        self.zoom = None
        self._render()

    def _actual(self):
        if self._shown is None or self._frames:
            return
        W, H = self._orig
        self.cx, self.cy = W / 2, H / 2
        # toggle: true 100 % size ⇄ fill the window (works for big AND small)
        if self.zoom == 1.0 or abs(self._fit_scale() - 1.0) < 0.01:
            self.zoom = None
        else:
            self.zoom = 1.0
            self._need_full()
        self._render()

    def _drag_start(self, e):
        self._drag_from = (e.x, e.y, self.cx, self.cy)

    def _drag(self, e):
        if self.zoom is None or not getattr(self, "_drag_from", None):
            return
        x, y, cx, cy = self._drag_from
        self.cx = cx - (e.x - x) / self.zoom
        self.cy = cy - (e.y - y) / self.zoom
        self._clamp()
        self._render(quality=False)
        self._schedule_sharp()

    # ── animated GIF / WebP ──────────────────────────────────────────────
    def _maybe_animate(self, path):
        from PIL import Image
        self._frames = None
        try:
            with Image.open(path) as im:
                if not getattr(im, "is_animated", False) or im.n_frames < 2:
                    return
                n = min(im.n_frames, 300)
                frames, durs = [], []
                for f in range(n):
                    im.seek(f)
                    frames.append(_flatten(im.convert("RGBA")))
                    durs.append(max(20, int(im.info.get("duration", 80) or 80)))
        except Exception:
            return
        self._frames = (frames, durs)
        self._restart_anim()

    def _restart_anim(self):
        self._stop_anim()
        if not self._frames:
            return
        from PIL import Image, ImageTk
        frames, durs = self._frames
        s = self._fit_scale()
        W, H = self._orig
        size = (max(1, round(W * s)), max(1, round(H * s)))
        tk_frames = [ImageTk.PhotoImage(f.resize(size, Image.BILINEAR)) for f in frames]
        vw, vh = self._view_box()
        self.cv.coords(self._img_item, vw / 2, vh / 2)
        state = {"i": 0}

        def tick():
            i = state["i"] % len(tk_frames)
            self._tk = tk_frames[i]
            self.cv.itemconfigure(self._img_item, image=self._tk)
            state["i"] += 1
            self._anim = self.after(durs[i], tick)
        tick()

    def _stop_anim(self):
        if self._anim:
            try:
                self.after_cancel(self._anim)
            except Exception:
                pass
            self._anim = None

    # ── window ───────────────────────────────────────────────────────────
    def _toggle_fs(self):
        self._fullscreen = not self._fullscreen
        self.attributes("-fullscreen", self._fullscreen)

    def _esc(self, e=None):
        if self._fullscreen:
            self._toggle_fs()
        else:
            self._close()

    def _close(self):
        self._stop_anim()
        for job in ("_osd_job", "_sharp_job", "_resize_job"):
            j = getattr(self, job, None)
            if j:
                try:
                    self.after_cancel(j)
                except Exception:
                    pass
        self.destroy()


# ═══════════════════════════════════════════════════════════════════════
#  Images: Windows-Photos-style justified grid
#  Pictures keep their real shape, rows fill the full width, month headings,
#  no frames/names. Still virtualized: only on-screen pictures exist.
# ═══════════════════════════════════════════════════════════════════════
_SIZE_CACHE = None            # normcase(path) -> [mtime, w, h], shared, on disk
_SIZE_LOCK = threading.Lock()


def _size_cache():
    global _SIZE_CACHE
    if _SIZE_CACHE is None:
        import json
        try:
            with open(os.path.join(CACHE_DIR, "image_sizes.json"), "r", encoding="utf-8") as f:
                _SIZE_CACHE = json.load(f)
        except Exception:
            _SIZE_CACHE = {}
    return _SIZE_CACHE


def _save_size_cache():
    import json
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with _SIZE_LOCK:
            data = json.dumps(_size_cache())
        tmp = os.path.join(CACHE_DIR, "image_sizes.json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(tmp, os.path.join(CACHE_DIR, "image_sizes.json"))
    except Exception:
        pass


def _image_size(path, mtime):
    """Displayed (w, h) from the file header only — no decoding. Cached."""
    key = os.path.normcase(path)
    c = _size_cache()
    hit = c.get(key)
    if hit and hit[0] == int(mtime):
        return hit[1], hit[2]
    from PIL import Image
    try:
        with Image.open(path) as im:
            w, h = im.size
            # rotation tags only matter for camera JPEG/TIFF. NOT PNG: there
            # getexif() decodes the whole image (tag may follow the pixels)
            if im.format in ("JPEG", "MPO", "TIFF"):
                try:
                    if im.getexif().get(0x0112, 1) in (5, 6, 7, 8):
                        w, h = h, w
                except Exception:
                    pass
    except Exception:
        return None
    with _SIZE_LOCK:
        c[key] = [int(mtime), w, h]
    return w, h


class ImageGridView(LibraryView):
    TARGET_H = 200     # row height to aim for (rows stretch/shrink to fill)
    GAP = 6            # space between pictures
    HEAD_H = 46        # month heading block
    MARGIN = 12
    RADIUS = 6         # rounded corners, baked into each thumbnail

    def __init__(self, parent, folder, on_play=None):
        # state the base __init__ (which calls reload) will need
        self._mtime = {}
        self._aspect = {}          # path -> w/h
        self._cell = {}            # path -> (x, y, w, h)
        self._rows = []            # [(y, h, first_idx, last_idx)]
        self._row_tops = []
        self._layout_w = 0
        self._layout_h = 0
        self._sizes_gen = 0
        super().__init__(parent, folder, on_play=on_play, kind="images")
        self.canvas.configure(cursor="")
        c = self.canvas
        # one shared hover highlight + name pill (disabled = ignores the mouse)
        self._hov = c.create_rectangle(0, 0, 0, 0, outline="#e4e4e7", width=2,
                                       state="hidden")
        self._hov_bg = c.create_rectangle(0, 0, 0, 0, fill="#000000", outline="",
                                          state="hidden")
        self._hov_txt = c.create_text(0, 0, anchor="sw", fill="#e4e4e7",
                                      font=F_TINY, state="hidden")

    # ── scan + sizes ─────────────────────────────────────────────────────
    def _scan(self):
        files = super()._scan()
        self._mtime = {}
        for p in files:
            try:
                self._mtime[p] = os.path.getmtime(p)
            except OSError:
                self._mtime[p] = 0
        return files

    def reload(self):
        self._stop = True
        self._gen += 1
        self._sizes_gen += 1
        self._cache.clear()
        self._failed.clear()
        with self._want_lock:
            self._want = []
        self._files = self._scan()
        for s in self._slots:
            s["path"] = None
        n = len(self._files)
        noun = self._k["one"] if n == 1 else self._k["many"]
        self.count_lbl.config(text=f"{n} {noun}")
        # sizes: cached ones are free; read the first screen's worth now so
        # the top rows are right immediately, the rest in the background
        self._aspect = {}
        missing = []
        for i, p in enumerate(self._files):
            key = os.path.normcase(p)
            hit = _size_cache().get(key)
            if hit and hit[0] == int(self._mtime.get(p, 0)):
                self._aspect[p] = hit[1] / max(1, hit[2])
            elif i < 120:
                wh = _image_size(p, self._mtime.get(p, 0))
                if wh:
                    self._aspect[p] = wh[0] / max(1, wh[1])
            else:
                missing.append(p)
        if missing:
            # start after the first screen has painted: reading headers is
            # Python work that would otherwise compete with drawing it
            sg = self._sizes_gen
            self.after(400, lambda: threading.Thread(
                target=self._size_worker, args=(missing, sg), daemon=True).start())
        elif n:
            threading.Thread(target=_save_size_cache, daemon=True).start()
        if not n:
            self.empty_lbl.config(text=f"No {self._k['many']} in this folder yet.")
            self.canvas.itemconfigure(self._empty_win, state="normal")
        else:
            self.canvas.itemconfigure(self._empty_win, state="hidden")
            self._stop = False
            threading.Thread(target=self._thumb_worker, args=(self._gen,),
                             daemon=True).start()
        self._relayout()
        self._reset_scroll()

    def _size_worker(self, paths, sgen):
        got = {}
        for p in paths:
            if sgen != self._sizes_gen:
                return
            wh = _image_size(p, self._mtime.get(p, 0))
            if wh:
                got[p] = wh[0] / max(1, wh[1])
        _save_size_cache()

        def apply():
            if sgen != self._sizes_gen:
                return
            self._aspect.update(got)
            self._relayout(keep_cache=True)
            self._update_scrollregion()
            self._update_view()
        try:
            self.after(0, apply)
        except Exception:
            pass

    # ── justified layout ─────────────────────────────────────────────────
    def _relayout(self, keep_cache=False):
        """Fill rows left→right at ~TARGET_H, then scale each full row so it
        exactly spans the width (Windows Photos style). Months get a heading
        and never share a row."""
        import time as _t
        c = self.canvas
        width = max(200, c.winfo_width())
        avail = width - 2 * self.MARGIN
        old_cells = self._cell
        self._cell, self._rows, self._row_tops = {}, [], []
        c.delete("head")
        y = 4
        G, H = self.GAP, self.TARGET_H
        files = self._files

        def place(row, h, justify):
            nonlocal y
            x = self.MARGIN
            for k, (i, a) in enumerate(row):
                w = a * h
                if justify and k == len(row) - 1:
                    w = self.MARGIN + avail - x        # absorb rounding
                self._cell[files[i]] = (round(x), round(y), max(1, round(w)), round(h))
                x += w + G
            self._rows.append((round(y), round(h), row[0][0], row[-1][0]))
            self._row_tops.append(round(y))
            y += h + G

        month = None
        row, asum = [], 0.0
        for i, p in enumerate(files):
            m = _t.strftime("%B %Y", _t.localtime(self._mtime.get(p, 0)))
            if m != month:
                if row:
                    place(row, H, False)
                    row, asum = [], 0.0
                if month is not None:
                    y += 10
                month = m
                c.create_text(self.MARGIN + 2, y + 30, anchor="sw", text=m,
                              fill=T.TEXT, font=("Segoe UI Semibold", 12), tags=("head",))
                y += self.HEAD_H
            # unknown size → assume 16:9; clamp extremes so rows stay sane
            a = min(3.0, max(0.5, self._aspect.get(p, 16 / 9)))
            row.append((i, a))
            asum += a
            if asum * H + G * (len(row) - 1) >= avail:
                place(row, (avail - G * (len(row) - 1)) / asum, True)
                row, asum = [], 0.0
        if row:
            place(row, H, False)                       # last row: natural size
        self._layout_h = round(y + 12) if files else 0
        self._layout_w = width
        # thumbnails are made at each cell's exact size: drop the ones whose
        # cell changed size (a resize, or real sizes replacing the 16:9 guess)
        for p in list(self._cache):
            if old_cells.get(p, (0, 0, 0, 0))[2:] != self._cell.get(p, (0, 0, -1, -1))[2:]:
                del self._cache[p]
        for s in self._slots:
            s["path"] = None                           # re-place every slot

    def _total_h(self):
        return self._layout_h

    def _on_canvas_resize(self, e):
        if abs(e.width - self._layout_w) > 1:
            self._relayout(keep_cache=True)
        self._update_scrollregion()
        self._schedule_view()

    # ── slots: a plain picture (no frame/name) ───────────────────────────
    def _new_slot(self):
        c = self.canvas
        tag = f"slot{len(self._slots)}"
        tags = (tag, "card")
        bg = c.create_rectangle(0, 0, 1, 1, fill="#1a1a1e", width=0, tags=tags,
                                state="hidden")
        img = c.create_image(0, 0, anchor="nw", tags=tags, state="hidden")
        slot = {"tag": tag, "rect": bg, "imgitem": img, "path": None, "img": None,
                "x": 0, "y": 0, "wh": (0, 0), "shown": False}

        def on_ctx(e, s=slot):
            if s["path"]:
                self._show_ctx(e, s["path"])

        def on_enter(e, s=slot):
            if not s["path"]:
                return
            x, y = s["x"], s["y"]
            w, h = s["wh"]
            c.coords(self._hov, x + 1, y + 1, x + w - 1, y + h - 1)
            name = self._fit_name_px(os.path.basename(s["path"]), w - 24)
            c.itemconfigure(self._hov_txt, text=name)
            c.coords(self._hov_txt, x + 10, y + h - 8)
            bx = c.bbox(self._hov_txt)
            if bx:
                c.coords(self._hov_bg, bx[0] - 6, bx[1] - 3, bx[2] + 6, bx[3] + 3)
            for it in (self._hov_bg, self._hov_txt, self._hov):
                c.itemconfigure(it, state="disabled")
                c.tag_raise(it)
            c.configure(cursor="hand2")

        def on_leave(e, s=slot):
            for it in (self._hov, self._hov_bg, self._hov_txt):
                c.itemconfigure(it, state="hidden")
            c.configure(cursor="")
        # open on RELEASE without moving (press + slide away = no open)
        c.tag_bind(tag, "<ButtonPress-1>", lambda e, s=slot: self._card_press(e, s))
        c.tag_bind(tag, "<ButtonRelease-1>", lambda e, s=slot: self._card_release(e, s))
        c.tag_bind(tag, "<Button-3>", on_ctx)
        c.tag_bind(tag, "<Enter>", on_enter)
        c.tag_bind(tag, "<Leave>", on_leave)
        self._slots.append(slot)
        return slot

    def _fit_name_px(self, name, maxw):
        if not hasattr(self, "_name_font"):
            import tkinter.font as tkfont
            self._name_font = tkfont.Font(font=F_TINY)
        f = self._name_font
        if f.measure(name) <= maxw:
            return name
        lo, hi = 0, len(name)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if f.measure(name[:mid] + "…") <= maxw:
                lo = mid
            else:
                hi = mid - 1
        return name[:lo].rstrip() + "…"

    def _show_slot(self, slot, on):
        if slot["shown"] == on:
            return
        slot["shown"] = on
        st = "normal" if on else "hidden"
        self.canvas.itemconfigure(slot["rect"], state=st)
        self.canvas.itemconfigure(slot["imgitem"], state=st)

    def _set_slot_image(self, slot, img):
        slot["img"] = img
        self.canvas.itemconfigure(slot["imgitem"], image=img if img is not None else "")

    def _fill_slot(self, slot, path):
        if slot["path"] != path:
            slot["path"] = path
            slot["img"] = False
        img = self._cache.get(path)
        if img is not None:
            self._cache.move_to_end(path)
        if slot["img"] is not img:
            self._set_slot_image(slot, img)

    def _place_cell(self, slot, cell):
        x, y, w, h = cell
        if (slot["x"], slot["y"], slot["wh"]) != (x, y, (w, h)):
            self.canvas.coords(slot["rect"], x, y, x + w, y + h)
            self.canvas.coords(slot["imgitem"], x, y)
            slot["x"], slot["y"], slot["wh"] = x, y, (w, h)

    def _update_view(self):
        import bisect
        self._view_pending = False
        if not self.winfo_exists():
            return
        n = len(self._files)
        ch = max(1, self.canvas.winfo_height())
        top = self.canvas.canvasy(0)
        lo_y, hi_y = top - ch * 0.25, top + ch * 1.25
        r0 = max(0, bisect.bisect_right(self._row_tops, lo_y) - 1)
        r1 = bisect.bisect_right(self._row_tops, hi_y)
        rows = self._rows[r0:r1]
        start = rows[0][2] if rows else 0
        end = rows[-1][3] + 1 if rows else 0
        need = end - start
        if len(self._slots) < need:
            while len(self._slots) < need + 24:
                self._new_slot()
        P = max(1, len(self._slots))
        used = set()
        for i in range(start, end):
            slot = self._slots[i % P]
            used.add(i % P)
            p = self._files[i]
            self._fill_slot(slot, p)
            self._place_cell(slot, self._cell[p])
            self._show_slot(slot, True)
        for j, slot in enumerate(self._slots):
            if j not in used and slot["shown"]:
                self._show_slot(slot, False)
                slot["path"] = None
        if hasattr(self, "_hov"):        # created after the first draw
            self.canvas.tag_raise(self._hov)
        self._cache_cap = max(150, 3 * max(need, 1))
        while len(self._cache) > self._cache_cap:
            self._cache.popitem(last=False)
        # work order: on screen, then the next screen down, then up
        page = max(need, 20)
        order = (self._files[start:end] + self._files[end:end + page]
                 + self._files[max(0, start - page):start][::-1])
        want = [p for p in order if p not in self._cache and p not in self._failed]
        with self._want_lock:
            self._want = want
        if want:
            self._want_evt.set()

    # ── thumbnails at each cell's exact size ─────────────────────────────
    def _make_thumb(self, path):
        cell = self._cell.get(path)
        if cell is None:
            return None, None
        w, h = cell[2], cell[3]
        im = shell_thumb(path, 512 if max(w, h) <= 512 else 768)
        if im is None:
            im, _ = self._image_thumb(path)
        return im, (w, h)                      # "badge" carries the target size

    def _compose(self, src, size):
        """Thread-safe: cover-fit into the cell (crops only clamped extremes)
        and round the corners."""
        from PIL import Image, ImageDraw
        w, h = size
        im = src if isinstance(src, Image.Image) else Image.open(src)
        im = im.convert("RGB")
        s = max(w / im.width, h / im.height)
        nw, nh = max(w, round(im.width * s)), max(h, round(im.height * s))
        im = im.resize((nw, nh), Image.LANCZOS, reducing_gap=2.0)
        l, t = (nw - w) // 2, (nh - h) // 2
        im = im.crop((l, t, l + w, t + h))
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), self.RADIUS, fill=255)
        out = Image.new("RGB", (w, h), (14, 14, 16))       # = T.BG
        out.paste(im, (0, 0), mask)
        return out

    def _apply_batch(self, batch, gen):
        # drop thumbnails made for a cell size that has since changed
        ok = [(p, im) for p, im in batch
              if im is None or (p in self._cell and im.size == tuple(self._cell[p][2:]))]
        super()._apply_batch(ok, gen)

    def _visible_loaded(self):
        return all(s["img"] is not None or s["path"] in self._failed
                   for s in self._slots if s["path"] and s["shown"])


def open_library(parent, folder):
    """Standalone Library window (kept for convenience; the app embeds a
    LibraryView directly)."""
    win = tk.Toplevel(parent)
    win.title("Pawlder — Library")
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
