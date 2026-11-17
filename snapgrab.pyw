"""
SnapGrab — Video Downloader
A minimal, modern GUI for downloading videos from YouTube, Instagram,
Pinterest, and other sites powered by yt-dlp.
"""

import os
import sys
import re
import json
import shutil
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

# ── Paths ──────────────────────────────────────────────────────────────
if getattr(sys, 'frozen', False):
    SCRIPT_DIR = os.path.dirname(sys.executable)
else:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Vendored engines (gallery-dl, pywebview + deps) live next to the app so
# they load no matter how the app is launched. The pip --user location under
# AppData\Roaming is unreliable from an Explorer-launched process on this PC,
# so we never depend on it: this folder, beside the .exe, always resolves.
_LIBS = os.path.join(SCRIPT_DIR, "snapgrab_libs")
if os.path.isdir(_LIBS) and _LIBS not in sys.path:
    sys.path.insert(0, _LIBS)
# ensure our own folder is importable (for snapgrab_media) no matter how launched
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

APP_VERSION = "2.5"

YTDLP_PATH = os.path.join(SCRIPT_DIR, "yt-dlp.exe")
ICON_PATH  = os.path.join(SCRIPT_DIR, "snapgrab.ico")

YTDLP_IS_LOCAL = os.path.isfile(YTDLP_PATH)
if not YTDLP_IS_LOCAL:
    YTDLP_PATH = "yt-dlp"


def find_ffmpeg_dir():
    """Directory containing ffmpeg.exe: next to the script, else on PATH."""
    local = os.path.join(SCRIPT_DIR, "ffmpeg.exe")
    if os.path.isfile(local):
        return SCRIPT_DIR
    found = shutil.which("ffmpeg")
    return os.path.dirname(found) if found else None


FFMPEG_DIR = find_ffmpeg_dir()


def find_gallery_dl():
    """Command prefix for gallery-dl (handles Instagram/Pinterest images +
    full carousels, which video-only yt-dlp can't).
    Returns (cmd_list, pythonpath_or_None); (None, None) if unavailable."""
    local = os.path.join(SCRIPT_DIR, "gallery-dl.exe")
    if os.path.isfile(local):
        return [local], None
    found = shutil.which("gallery-dl")
    if found:
        return [found], None
    py = sys.executable or ""
    if py.lower().endswith("pythonw.exe"):
        cand = os.path.join(os.path.dirname(py), "python.exe")
        if os.path.isfile(cand):
            py = cand
    # Vendored libs beside the app — the reliable source on this PC. Pass the
    # folder via PYTHONPATH so the subprocess imports it regardless of how the
    # app was launched or what the environment does to AppData.
    if os.path.isdir(os.path.join(_LIBS, "gallery_dl")):
        return [py, "-m", "gallery_dl"], _LIBS
    try:
        import importlib.util
        if importlib.util.find_spec("gallery_dl"):
            return [py, "-m", "gallery_dl"], None
    except Exception:
        pass
    # Last resort: the pip --user location (may be unreachable here).
    ver = f"{sys.version_info.major}{sys.version_info.minor}"
    homes = [os.environ.get("USERPROFILE"), os.path.dirname(SCRIPT_DIR),
             os.path.expanduser("~")]
    for home in homes:
        if not home or not os.path.isdir(home):
            continue
        site_dir = os.path.join(home, "AppData", "Roaming", "Python",
                                f"Python{ver}", "site-packages")
        if os.path.isdir(os.path.join(site_dir, "gallery_dl")):
            return [py, "-m", "gallery_dl"], site_dir
    return None, None


GDL_CMD, GDL_PYTHONPATH = find_gallery_dl()

# Optional cookies.txt next to the app (exported via a browser extension) —
# used automatically when no sign-in browser is selected. This is the only
# login route that works when every installed browser locks its cookie store.
COOKIES_TXT = os.path.join(SCRIPT_DIR, "cookies.txt")

PY_EXE = sys.executable or "python"
if PY_EXE.lower().endswith("pythonw.exe"):
    _cand = os.path.join(os.path.dirname(PY_EXE), "python.exe")
    if os.path.isfile(_cand):
        PY_EXE = _cand

CURL_EXE = shutil.which("curl") or r"C:\Windows\System32\curl.exe"


def find_user_site():
    """Folder holding gallery-dl / webview. Prefer the vendored libs beside
    the app (always reachable); fall back to the pip --user location."""
    if os.path.isdir(os.path.join(_LIBS, "gallery_dl")):
        return _LIBS
    ver = f"{sys.version_info.major}{sys.version_info.minor}"
    homes = [os.environ.get("USERPROFILE"), os.path.dirname(SCRIPT_DIR),
             os.path.expanduser("~")]
    for home in homes:
        if home and os.path.isdir(home):
            d = os.path.join(home, "AppData", "Roaming", "Python",
                             f"Python{ver}", "site-packages")
            if os.path.isdir(d):
                return d
    return None


USER_SITE = find_user_site()

# Hidden-browser helper: downloads public Instagram posts with NO login by
# reading the media URLs out of instagram.com's anonymous embed player.
EMBED_HELPER = os.path.join(SCRIPT_DIR, "snapgrab_embed.py")


def embed_available():
    if not os.path.isfile(EMBED_HELPER):
        return False
    if os.path.isdir(os.path.join(_LIBS, "webview")):
        return True
    try:
        import importlib.util
        if importlib.util.find_spec("webview"):
            return True
    except Exception:
        pass
    return bool(USER_SITE and os.path.isdir(os.path.join(USER_SITE, "webview")))


EMBED_OK = embed_available()


def user_site_env():
    """Env for python subprocesses that need pip --user packages even when
    the launcher stripped APPDATA."""
    if USER_SITE:
        env = dict(os.environ)
        env["PYTHONPATH"] = USER_SITE + os.pathsep + env.get("PYTHONPATH", "")
        return env
    return None

MEDIA_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif",
              ".mp4", ".webm", ".m4v", ".mov", ".mp3", ".m4a")

# ── Quality presets ────────────────────────────────────────────────────
QUALITY_PRESETS = {
    "Best quality":      "bestvideo+bestaudio/best",
    "1080p":             "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
    "720p":              "bestvideo[height<=720]+bestaudio/best[height<=720]",
    "480p":              "bestvideo[height<=480]+bestaudio/best[height<=480]",
    "360p":              "bestvideo[height<=360]+bestaudio/best[height<=360]",
    "Audio only · MP3":  "bestaudio/best",
    "Audio only · M4A":  "bestaudio[ext=m4a]/bestaudio/best",
}

SITE_PATTERNS = [
    (re.compile(r"(youtube\.com|youtu\.be)", re.I), "YouTube"),
    (re.compile(r"(instagram\.com)", re.I),         "Instagram"),
    (re.compile(r"(pinterest\.\w+|pin\.it)", re.I), "Pinterest"),
]

# Lines from yt-dlp post-processors that mean "almost done, don't panic"
POSTPROCESS_RE = re.compile(
    r"\[(Merger|VideoRemuxer|VideoConvertor|ExtractAudio|FixupM3u8|Metadata)\]")

# ═══════════════════════════════════════════════════════════════════════
#  Theme — flat graphite, one accent
# ═══════════════════════════════════════════════════════════════════════
class T:
    BG       = "#0e0e10"   # window
    SURFACE  = "#151517"   # log panel
    FIELD    = "#1a1a1e"   # inputs
    BORDER   = "#27272c"
    FOCUS    = "#55555e"   # focused input border
    TEXT     = "#f4f4f5"
    SUBTEXT  = "#a1a1aa"
    MUTED    = "#71717a"
    DIM      = "#4b4b53"
    SELECT   = "#3f3f46"
    # status colors (kept names used by the download thread)
    BLUE     = "#d4d4d8"   # downloading
    CYAN     = "#d4d4d8"   # finalizing
    GREEN    = "#4ade80"
    RED      = "#f87171"
    YELLOW   = "#fbbf24"

F_BASE  = ("Segoe UI", 10)
F_SMALL = ("Segoe UI", 9)
F_LABEL = ("Segoe UI", 9)
F_TITLE = ("Segoe UI Semibold", 14)
F_BTN   = ("Segoe UI Semibold", 11)
F_MONO  = ("Cascadia Code", 9)


def rrect(canvas, x1, y1, x2, y2, r, **kw):
    """Draw a rounded rectangle on a canvas."""
    r = min(r, (x2 - x1) / 2, (y2 - y1) / 2)
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return canvas.create_polygon(pts, smooth=True, **kw)


# ═══════════════════════════════════════════════════════════════════════
#  Custom widgets
# ═══════════════════════════════════════════════════════════════════════
class Field(tk.Canvas):
    """Rounded text input with an optional trailing action (Paste / Browse)."""

    def __init__(self, parent, textvariable, action=None, on_action=None, height=42):
        super().__init__(parent, bg=parent["bg"], highlightthickness=0,
                         height=height, bd=0)
        self.action = action
        self.on_action = on_action
        self.focused = False
        self._border = None
        self.entry = tk.Entry(self, textvariable=textvariable, bd=0, relief="flat",
                              bg=T.FIELD, fg=T.TEXT, insertbackground=T.TEXT,
                              font=F_BASE, highlightthickness=0,
                              selectbackground=T.SELECT, selectforeground=T.TEXT)
        self.entry.bind("<FocusIn>",  lambda e: self._set_focus(True))
        self.entry.bind("<FocusOut>", lambda e: self._set_focus(False))
        self.bind("<Configure>", lambda e: self._redraw())

    def _set_focus(self, val):
        self.focused = val
        if self._border is not None:
            self.itemconfigure(self._border, outline=T.FOCUS if val else T.BORDER)

    def _redraw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4:
            return
        self._border = rrect(self, 1, 1, w - 1, h - 1, 10, fill=T.FIELD,
                             outline=T.FOCUS if self.focused else T.BORDER, width=1)
        action_w = 0
        if self.action:
            t = self.create_text(w - 14, h / 2, text=self.action, anchor="e",
                                 fill=T.MUTED, font=("Segoe UI Semibold", 9),
                                 tags="action")
            bbox = self.bbox(t)
            action_w = (bbox[2] - bbox[0]) + 26
            self.tag_bind("action", "<Button-1>",
                          lambda e: self.on_action and self.on_action())
            self.tag_bind("action", "<Enter>", lambda e: (
                self.itemconfigure(t, fill=T.TEXT), self.configure(cursor="hand2")))
            self.tag_bind("action", "<Leave>", lambda e: (
                self.itemconfigure(t, fill=T.MUTED), self.configure(cursor="")))
        self.create_window(14, h / 2, anchor="w", window=self.entry,
                           width=w - 28 - action_w, height=h - 16)


class Select(tk.Canvas):
    """Rounded dropdown backed by a styled tk.Menu."""

    def __init__(self, parent, variable, values, height=42):
        super().__init__(parent, bg=parent["bg"], highlightthickness=0,
                         height=height, bd=0, cursor="hand2")
        self.var = variable
        self.values = values
        self.hover = False
        self.menu = tk.Menu(self, tearoff=0, bg=T.FIELD, fg=T.SUBTEXT,
                            activebackground=T.SELECT, activeforeground=T.TEXT,
                            bd=0, relief="flat", font=F_BASE)
        for v in values:
            self.menu.add_command(label=f"  {v}  ",
                                  command=lambda val=v: self.var.set(val))
        self.var.trace_add("write", lambda *_: self._redraw())
        self.bind("<Configure>", lambda e: self._redraw())
        self.bind("<Button-1>", self._open)
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))

    def _set_hover(self, val):
        self.hover = val
        self._redraw()

    def _open(self, _=None):
        try:
            self.menu.tk_popup(self.winfo_rootx(),
                               self.winfo_rooty() + self.winfo_height() + 2)
        finally:
            self.menu.grab_release()

    def _redraw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4:
            return
        rrect(self, 1, 1, w - 1, h - 1, 10, fill=T.FIELD,
              outline=T.FOCUS if self.hover else T.BORDER, width=1)
        self.create_text(14, h / 2, text=self.var.get(), anchor="w",
                         fill=T.TEXT, font=F_BASE)
        self.create_text(w - 14, h / 2, text="▾", anchor="e",
                         fill=T.MUTED, font=F_SMALL)


class PillButton(tk.Canvas):
    """Flat rounded button with primary / danger states."""

    KINDS = {"primary": ("#fafafa", "#e4e4e7", "#111113"),
             "danger":  ("#dc2626", "#ef4444", "#ffffff")}

    def __init__(self, parent, text, command, height=46):
        super().__init__(parent, bg=parent["bg"], highlightthickness=0,
                         height=height, bd=0, cursor="hand2")
        self.text = text
        self.command = command
        self.kind = "primary"
        self.hover = False
        self.bind("<Configure>", lambda e: self._redraw())
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<Button-1>", lambda e: self.command())

    def set(self, text, kind="primary"):
        self.text = text
        self.kind = kind
        self._redraw()

    def _set_hover(self, val):
        self.hover = val
        self._redraw()

    def _redraw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4:
            return
        base, hov, fg = self.KINDS[self.kind]
        fill = hov if self.hover else base
        rrect(self, 0, 0, w, h, 12, fill=fill, outline=fill)
        self.create_text(w / 2, h / 2, text=self.text, fill=fg, font=F_BTN)


class SlimBar(tk.Canvas):
    """Thin rounded progress bar."""

    def __init__(self, parent, height=5):
        super().__init__(parent, bg=parent["bg"], highlightthickness=0,
                         height=height, bd=0)
        self.value = 0.0
        self.bind("<Configure>", lambda e: self._redraw())

    def set(self, val):
        self.value = max(0.0, min(100.0, val))
        self._redraw()

    def _redraw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4:
            return
        rrect(self, 0, 0, w, h, h / 2, fill=T.BORDER, outline=T.BORDER)
        if self.value > 0:
            fw = max(h, w * self.value / 100)
            rrect(self, 0, 0, fw, h, h / 2, fill="#fafafa", outline="#fafafa")


class Switch(tk.Canvas):
    """Small toggle switch bound to a BooleanVar."""

    def __init__(self, parent, variable, width=36, height=20):
        super().__init__(parent, bg=parent["bg"], highlightthickness=0,
                         width=width, height=height, bd=0, cursor="hand2")
        self.var = variable
        self.var.trace_add("write", lambda *_: self._redraw())
        self.bind("<Button-1>", lambda e: self.var.set(not self.var.get()))
        self.bind("<Configure>", lambda e: self._redraw())

    def _redraw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4:
            return
        on = self.var.get()
        track = "#fafafa" if on else "#2c2c32"
        knob  = "#111113" if on else "#71717a"
        rrect(self, 0, 0, w, h, h / 2, fill=track, outline=track)
        r = (h - 8) / 2
        cx = w - 4 - r if on else 4 + r
        self.create_oval(cx - r, h / 2 - r, cx + r, h / 2 + r,
                         fill=knob, outline=knob)


# ═══════════════════════════════════════════════════════════════════════
#  Main Application
# ═══════════════════════════════════════════════════════════════════════
class SnapGrabApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("SnapGrab")
        self.root.configure(bg=T.BG)
        self.root.resizable(True, True)
        self.root.minsize(660, 560)
        self.downloading = False
        self.process = None
        self.last_file = None

        try:
            if os.path.isfile(ICON_PATH):
                self.root.iconbitmap(ICON_PATH)
        except Exception:
            pass

        self.output_dir = os.path.join(os.path.expanduser("~"), "Videos")
        if not os.path.isdir(self.output_dir):
            self.output_dir = SCRIPT_DIR

        self._build_ui()
        self._center(960, 680)          # restore size when un-maximized
        try:
            self.root.state("zoomed")   # open maximized
        except Exception:
            pass
        self._dark_title_bar()
        self._autofill_from_clipboard()
        self._write_debug()

        if YTDLP_IS_LOCAL:
            threading.Thread(target=self._update_ytdlp, daemon=True).start()

    def _write_debug(self):
        """Startup ground-truth: which engines this exact process can see.
        Written to snapgrab_debug.txt next to the app and into the log."""
        import datetime
        engines = []
        if GDL_CMD: engines.append("gallery-dl")
        if EMBED_OK: engines.append("embed")
        summary = f"v{APP_VERSION} pid={os.getpid()} engines: yt-dlp" + \
                  ("".join(" + " + e for e in engines) or " ONLY")
        self._log(summary, auto_show=False)
        try:
            with open(os.path.join(SCRIPT_DIR, "snapgrab_debug.txt"), "w") as f:
                f.write(f"time: {datetime.datetime.now()}\n"
                        f"version: {APP_VERSION}\npid: {os.getpid()}\n"
                        f"script_mtime: {datetime.datetime.fromtimestamp(os.path.getmtime(os.path.abspath(__file__)))}\n"
                        f"sys.executable: {sys.executable}\n"
                        f"APPDATA: {os.environ.get('APPDATA')}\n"
                        f"USERPROFILE: {os.environ.get('USERPROFILE')}\n"
                        f"GDL_CMD: {GDL_CMD}\nGDL_PYTHONPATH: {GDL_PYTHONPATH}\n"
                        f"USER_SITE: {USER_SITE}\nEMBED_OK: {EMBED_OK}\n"
                        f"EMBED_HELPER exists: {os.path.isfile(EMBED_HELPER)}\n"
                        f"CURL_EXE: {CURL_EXE}\nFFMPEG_DIR: {FFMPEG_DIR}\n")
                import site as _site
                f.write(f"\n-- import diag --\n"
                        f"ENABLE_USER_SITE: {_site.ENABLE_USER_SITE}\n"
                        f"PYTHONNOUSERSITE: {os.environ.get('PYTHONNOUSERSITE')}\n"
                        f"site.getusersitepackages: {_site.getusersitepackages()}\n"
                        f"user_site exists: {os.path.isdir(_site.getusersitepackages())}\n"
                        f"sys.path:\n" + "\n".join("  " + p for p in sys.path) + "\n")
        except Exception:
            pass

    def _dark_title_bar(self):
        """Match the native title bar to the app (Windows 10/11)."""
        try:
            import ctypes
            self.root.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            one = ctypes.byref(ctypes.c_int(1))
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, one, 4)  # dark mode
            # Win11: paint the caption the same color as the window
            caption = ctypes.byref(ctypes.c_int(0x00100e0e))  # BGR of T.BG
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 35, caption, 4)
        except Exception:
            pass

    # ── UI construction ───────────────────────────────────────────────
    def _build_ui(self):
        outer = tk.Frame(self.root, bg=T.BG)
        outer.pack(fill="both", expand=True)

        # Header with Library / Download toggle
        hdr = tk.Frame(outer, bg=T.BG)
        hdr.pack(fill="x", padx=24, pady=(16, 8))
        tk.Label(hdr, text="SnapGrab", font=F_TITLE, bg=T.BG, fg=T.TEXT).pack(side="left")
        self.hdr_note = tk.Label(hdr, text=f"v{APP_VERSION}", font=F_SMALL, bg=T.BG, fg=T.DIM)
        self.hdr_note.pack(side="right")

        seg = tk.Frame(hdr, bg=T.BG)
        seg.pack(side="left", padx=(22, 0))
        self._nav = {}
        for key, label in (("library", "▦  Library"), ("download", "⬇  Download")):
            b = tk.Label(seg, text=label, font=("Segoe UI Semibold", 9), bg=T.BG,
                         fg=T.MUTED, cursor="hand2", padx=12, pady=5)
            b.pack(side="left", padx=(0, 6))
            b.bind("<Button-1>", lambda e, k=key: self._show_view(k))
            self._nav[key] = b

        tk.Frame(outer, bg=T.BORDER, height=1).pack(fill="x", padx=24)

        # Swappable content area
        self.content = tk.Frame(outer, bg=T.BG)
        self.content.pack(fill="both", expand=True)

        self.download_view = tk.Frame(self.content, bg=T.BG)
        self._build_download_view(self.download_view)

        self._build_library_view()   # sets self.library_view (or None)

        if self.library_view is None:
            self._nav["library"].pack_forget()
        self._show_view("library" if self.library_view is not None else "download")

    def _build_library_view(self):
        self.library_view = None
        folder = self.output_dir
        try:
            if os.path.isdir(self.dir_var.get().strip()):
                folder = self.dir_var.get().strip()
        except Exception:
            pass
        try:
            import snapgrab_media
            if snapgrab_media.have_pillow():
                self.library_view = snapgrab_media.LibraryView(self.content, folder)
        except Exception:
            self.library_view = None

    def _show_view(self, key):
        if key == "library" and self.library_view is None:
            key = "download"
        self.download_view.pack_forget()
        if self.library_view is not None:
            self.library_view.pack_forget()
        if key == "library":
            self.library_view.pack(fill="both", expand=True)
        else:
            self.download_view.pack(fill="both", expand=True)
        for k, b in self._nav.items():
            active = (k == key)
            b.config(fg=T.TEXT if active else T.MUTED, bg=T.SURFACE if active else T.BG)
        self._view = key

    def _build_download_view(self, parent):
        # engines footer pinned to the bottom
        engines = "yt-dlp  ·  gallery-dl  ·  ffmpeg" if GDL_CMD else "yt-dlp  ·  ffmpeg"
        tk.Label(parent, text=engines, font=("Segoe UI", 8),
                 bg=T.BG, fg=T.DIM).pack(side="bottom", pady=(4, 10))

        # centered fixed-width column so the form doesn't stretch in the wide window
        holder = tk.Frame(parent, bg=T.BG)
        holder.pack(fill="both", expand=True)
        holder.grid_columnconfigure(0, weight=1)
        holder.grid_columnconfigure(1, minsize=560)
        holder.grid_columnconfigure(2, weight=1)
        holder.grid_rowconfigure(0, weight=1)
        form = tk.Frame(holder, bg=T.BG)
        form.grid(row=0, column=1, sticky="nsew", pady=(10, 0))

        # URL
        url_row = tk.Frame(form, bg=T.BG)
        url_row.pack(fill="x", pady=(10, 6))
        tk.Label(url_row, text="Video URL", font=F_LABEL, bg=T.BG, fg=T.MUTED).pack(side="left")
        self.site_lbl = tk.Label(url_row, text="", font=F_SMALL, bg=T.BG, fg=T.SUBTEXT)
        self.site_lbl.pack(side="right")

        self.url_var = tk.StringVar()
        self.url_var.trace_add("write", lambda *_: self._update_site_badge())
        self.url_field = Field(form, self.url_var, action="Paste", on_action=self._paste_clip)
        self.url_field.pack(fill="x")
        self.url_entry = self.url_field.entry
        self.url_entry.bind("<Return>", lambda e: self._on_download())

        # Playlist switch
        self.playlist_var = tk.BooleanVar(value=False)
        pl_row = tk.Frame(form, bg=T.BG)
        pl_row.pack(fill="x", pady=(12, 4))
        Switch(pl_row, self.playlist_var).pack(side="left")
        pl_lbl = tk.Label(pl_row, text="Download full playlist", font=F_SMALL,
                          bg=T.BG, fg=T.SUBTEXT, cursor="hand2")
        pl_lbl.pack(side="left", padx=(10, 0))
        pl_lbl.bind("<Button-1>", lambda e: self.playlist_var.set(not self.playlist_var.get()))

        # Quality + Sign-in browser, side by side
        row = tk.Frame(form, bg=T.BG)
        row.pack(fill="x", pady=(14, 0))
        row.columnconfigure(0, weight=1, uniform="half")
        row.columnconfigure(1, weight=1, uniform="half")

        qcol = tk.Frame(row, bg=T.BG)
        qcol.grid(row=0, column=0, sticky="ew", padx=(0, 7))
        tk.Label(qcol, text="Quality", font=F_LABEL, bg=T.BG, fg=T.MUTED,
                 anchor="w").pack(fill="x", pady=(0, 6))
        self.quality_var = tk.StringVar(value="Best quality")
        Select(qcol, self.quality_var, list(QUALITY_PRESETS.keys())).pack(fill="x")

        acol = tk.Frame(row, bg=T.BG)
        acol.grid(row=0, column=1, sticky="ew", padx=(7, 0))
        tk.Label(acol, text="Sign-in browser  ·  fixes bot errors", font=F_LABEL,
                 bg=T.BG, fg=T.MUTED, anchor="w").pack(fill="x", pady=(0, 6))
        self.cookie_var = tk.StringVar(value="None")
        Select(acol, self.cookie_var,
               ["None", "Firefox", "Chrome", "Edge", "Brave", "Opera", "Vivaldi"]).pack(fill="x")

        # Save to
        tk.Label(form, text="Save to", font=F_LABEL, bg=T.BG, fg=T.MUTED,
                 anchor="w").pack(fill="x", pady=(14, 6))
        self.dir_var = tk.StringVar(value=self.output_dir)
        Field(form, self.dir_var, action="Browse", on_action=self._browse).pack(fill="x")

        # Download button
        self.dl_btn = PillButton(form, "Download", self._on_download)
        self.dl_btn.pack(fill="x", pady=(22, 0))

        # Progress
        self.progress = SlimBar(form)
        self.progress.pack(fill="x", pady=(18, 0))

        # Status row
        status_row = tk.Frame(form, bg=T.BG)
        status_row.pack(fill="x", pady=(8, 0))
        self.status_var = tk.StringVar(value="Ready")
        self.status_lbl = tk.Label(status_row, textvariable=self.status_var,
                                   font=F_SMALL, bg=T.BG, fg=T.MUTED, anchor="w",
                                   wraplength=430, justify="left")
        self.status_lbl.pack(side="left", fill="x", expand=True)

        self.play_link = tk.Label(status_row, text="▶  Play", font=("Segoe UI Semibold", 9),
                                  bg=T.BG, fg=T.GREEN, cursor="hand2")
        self.play_link.bind("<Button-1>", lambda e: self._play_and_close())

        # Log
        self.log_shown = False
        self.log_hdr = tk.Label(form, text="Show log", font=F_SMALL, bg=T.BG,
                                fg=T.DIM, anchor="w", cursor="hand2")
        self.log_hdr.pack(fill="x", pady=(12, 0))
        self.log_hdr.bind("<Button-1>", lambda e: self._toggle_log())
        self.log_hdr.bind("<Enter>", lambda e: self.log_hdr.config(fg=T.MUTED))
        self.log_hdr.bind("<Leave>", lambda e: self.log_hdr.config(fg=T.DIM))

        self.log_frame = tk.Frame(form, bg=T.SURFACE, highlightbackground=T.BORDER,
                                  highlightthickness=1)
        self.log_text = tk.Text(self.log_frame, font=F_MONO, bg=T.SURFACE, fg=T.SUBTEXT,
                                relief="flat", bd=0, wrap="word", height=6,
                                insertbackground=T.TEXT, state="disabled",
                                selectbackground=T.SELECT, selectforeground=T.TEXT)
        log_sb = tk.Scrollbar(self.log_frame, command=self.log_text.yview,
                              bg=T.SURFACE, troughcolor=T.SURFACE, width=8)
        self.log_text.configure(yscrollcommand=log_sb.set)
        log_sb.pack(side="right", fill="y", padx=(0, 2), pady=4)
        self.log_text.pack(side="left", fill="both", expand=True, padx=10, pady=8)

    def _center(self, w, h):
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() - w) // 2
        y = (self.root.winfo_screenheight() - h) // 2
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    # ── Helpers ────────────────────────────────────────────────────────
    @staticmethod
    def _detect_site(url):
        for pattern, name in SITE_PATTERNS:
            if pattern.search(url):
                return name
        return None

    def _update_site_badge(self):
        site = self._detect_site(self.url_var.get())
        self.site_lbl.config(text=site or "")

    def _autofill_from_clipboard(self):
        """Pre-fill the URL box if the clipboard already holds a video link."""
        try:
            clip = self.root.clipboard_get().strip()
        except Exception:
            return
        if clip.startswith(("http://", "https://")) and " " not in clip and self._detect_site(clip):
            self.url_var.set(clip)
            self.url_entry.icursor("end")

    def _update_ytdlp(self):
        """Silently self-update the bundled yt-dlp.exe (stale yt-dlp is the
        #1 cause of YouTube downloads suddenly breaking)."""
        try:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = subprocess.SW_HIDE
            r = subprocess.run([YTDLP_PATH, "-U"], capture_output=True, text=True,
                               startupinfo=si, timeout=120)
            if "Updated yt-dlp to" in (r.stdout or ""):
                ver = re.search(r"Updated yt-dlp to (\S+)", r.stdout)
                msg = f"downloader updated to {ver.group(1)}" if ver else "downloader updated"
                self.root.after(0, lambda: self.hdr_note.config(text=msg))
        except Exception:
            pass  # no network / already busy — never block the UI over this

    def _browse(self):
        f = filedialog.askdirectory(initialdir=self.dir_var.get())
        if f: self.dir_var.set(f)

    def _paste_clip(self, _=None):
        try:
            self.url_var.set(self.root.clipboard_get().strip())
            self.url_entry.icursor("end")
        except Exception: pass

    def _toggle_log(self):
        if self.log_shown:
            self.log_frame.pack_forget()
            self.log_hdr.config(text="Show log")
        else:
            self.log_frame.pack(fill="both", expand=True, pady=(6, 0))
            self.log_hdr.config(text="Hide log")
        self.log_shown = not self.log_shown

    def _log(self, msg, auto_show=True):
        self.log_text.config(state="normal")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")
        if auto_show and not self.log_shown:
            self._toggle_log()

    def _status(self, msg, color=None):
        self.status_var.set(msg)
        self.status_lbl.config(fg=color or T.MUTED)

    def _prog(self, val):
        self.progress.set(val)

    def _show_play_btn(self):
        self.play_link.pack(side="right", padx=(8, 0))

    def _play_and_close(self):
        file_to_play = self.last_file
        if not file_to_play or not os.path.exists(file_to_play):
            out_dir = self.dir_var.get().strip()
            if os.path.isdir(out_dir):
                files = [os.path.join(out_dir, f) for f in os.listdir(out_dir)]
                files = [f for f in files if os.path.isfile(f) and f.lower().endswith(MEDIA_EXTS + ('.mkv', '.avi'))]
                if files: file_to_play = max(files, key=os.path.getctime)

        if file_to_play and os.path.exists(file_to_play):
            try: os.startfile(file_to_play)
            except Exception: pass
        self.root.destroy()

    def _cancel(self):
        if self.process and self.process.poll() is None:
            try: subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.process.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                try: self.process.kill()
                except Exception: pass
            self.process = None
        self.downloading = False
        self._status("Cancelled", T.YELLOW)
        self._log("--- Cancelled by user ---")
        self._prog(0)
        self.dl_btn.set("Download", "primary")

    def _on_download(self):
        if self.downloading:
            self._cancel()
            return
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("SnapGrab", "Paste a video URL first.")
            return
        out = self.dir_var.get().strip()
        if not os.path.isdir(out):
            messagebox.showwarning("SnapGrab", "Output folder doesn't exist.")
            return

        qk = self.quality_var.get()
        fmt = QUALITY_PRESETS.get(qk, "best")
        audio_only = "Audio only" in qk

        self.downloading = True
        self.dl_btn.set("Cancel", "danger")
        self._status("Starting...", T.YELLOW)
        self._prog(0)
        self.play_link.pack_forget()

        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")

        playlist = self.playlist_var.get()

        browser = self.cookie_var.get().strip().lower()

        # Instagram / Pinterest posts go through gallery-dl: it grabs full
        # carousels including images, which video-only yt-dlp skips.
        # Instagram without any login source goes through the anonymous
        # embed-player route instead (public posts need no login there).
        site = self._detect_site(url)
        has_login = browser != "none" or os.path.isfile(COOKIES_TXT)
        if site == "Instagram" and not audio_only and not has_login and EMBED_OK:
            threading.Thread(target=self._embed_thread, args=(url, out), daemon=True).start()
        elif site in ("Instagram", "Pinterest") and not audio_only and GDL_CMD:
            threading.Thread(target=self._gdl_thread, args=(url, out, browser), daemon=True).start()
        elif site == "Instagram" and not audio_only and EMBED_OK:
            # gallery-dl missing but embed works — never fall through to
            # yt-dlp for Instagram (its resolver can't do DNS on this PC)
            threading.Thread(target=self._embed_thread, args=(url, out), daemon=True).start()
        else:
            if site == "Instagram" and not audio_only:
                self._log("WARNING: no Instagram engine found — falling back to yt-dlp, this will likely fail", auto_show=True)
            threading.Thread(target=self._dl_thread, args=(url, fmt, out, audio_only, playlist, browser, qk), daemon=True).start()

    def _build_cmd(self, url, fmt, out, audio_only, playlist, browser, fmt_label=""):
        if playlist:
            out_template = os.path.join(out, "%(playlist_title)s", "%(playlist_index)03d - %(title)s.%(ext)s")
        else:
            out_template = os.path.join(out, "%(title)s.%(ext)s")

        cmd = [YTDLP_PATH,
               "--yes-playlist" if playlist else "--no-playlist",
               "-f", fmt,
               "-o", out_template,
               "--newline", "--no-colors", "--progress", "--encoding", "utf-8",
               "--windows-filenames",
               "--retries", "10", "--fragment-retries", "10",
               "--extractor-retries", "5",
               "--concurrent-fragments", "4",
               "--socket-timeout", "30"]

        if FFMPEG_DIR:
            cmd += ["--ffmpeg-location", FFMPEG_DIR]

        if audio_only:
            af = "mp3" if "MP3" in fmt_label else "m4a"
            cmd += ["-x", "--audio-format", af, "--audio-quality", "0"]
        else:
            # Prefer H.264 + AAC for After Effects / editor compatibility.
            # Remux (rewrap) into mp4 — unlike --recode-video this never
            # re-encodes, so downloads finish as soon as the merge does.
            cmd += ["-S", "vcodec:h264,acodec:aac",
                    "--merge-output-format", "mp4",
                    "--remux-video", "mp4"]

        if browser != "none":
            cmd += ["--cookies-from-browser", browser]
        elif os.path.isfile(COOKIES_TXT):
            cmd += ["--cookies", COOKIES_TXT]

        cmd.append(url)
        return cmd

    @staticmethod
    def _friendly_error(full_output, url, browser):
        low = full_output.lower()
        site = SnapGrabApp._detect_site(url) or ""
        if "sign in to confirm" in low or "not a bot" in low:
            if browser == "none":
                return "YouTube bot check. Pick a sign-in browser (Firefox is most reliable) and retry."
            return "YouTube bot check even with cookies. Make sure you're logged into YouTube in that browser, or try Firefox."
        if "failed to decrypt" in low or "dpapi" in low:
            return "Couldn't read this browser's cookies (newer Chrome blocks this). Use Firefox instead."
        if "could not copy" in low and "cookie" in low:
            return "Browser cookie file is locked. Close the browser completely and retry, or use Firefox."
        if site == "Instagram" and ("login required" in low or "rate-limit" in low or "not available" in low or "requested content" in low):
            return "Instagram wants a login. Pick your sign-in browser (be logged into Instagram there) and retry."
        if site == "Pinterest" and ("unsupported url" in low or "no video" in low or "unable to extract" in low):
            return "This pin doesn't seem to have a video (image-only pins can't be grabbed as video). Try the pin's video URL."
        if "video unavailable" in low:
            return "This video is unavailable (private, deleted, or region-locked)."
        if "is not a valid url" in low or "unsupported url" in low:
            return "This URL is not supported. Check the link and try again."
        if "http error 429" in low or "rate" in low and "limit" in low:
            return "The site is rate-limiting you. Wait a few minutes and retry."
        if "resolving timed out" in low or "getaddrinfo failed" in low or "name or service not known" in low:
            return "DNS hiccup — your connection briefly failed to look up the site. Just hit Download again."
        if "timed out" in low or "network" in low and "error" in low:
            return "Network error — check your internet connection and retry."
        return None

    @staticmethod
    def _friendly_gdl_error(full_output, url, browser):
        low = full_output.lower()
        site = SnapGrabApp._detect_site(url) or ""
        if site == "Instagram" and ("login" in low or "401" in low or "challenge" in low
                                    or "checkpoint" in low or "cookies" in low or "403" in low):
            if browser == "none":
                return "Instagram wants a login. Pick your sign-in browser (be logged into Instagram there) and retry."
            return "Instagram rejected the login. Open Instagram in that browser, make sure you're signed in, then retry (Firefox works best)."
        if "failed to decrypt" in low or "dpapi" in low:
            return "Couldn't read this browser's cookies (newer Chrome blocks this). Use Firefox instead."
        if "no results" in low or "unsupported" in low:
            return "Nothing downloadable found at this URL. Check the link and try again."
        if "429" in low or "rate" in low and "limit" in low:
            return "The site is rate-limiting you. Wait a few minutes and retry."
        return None

    def _embed_thread(self, url, out):
        """Download a public Instagram post with no login: a hidden browser
        opens the anonymous embed player and hands back the CDN media URLs."""
        self.last_file = None
        try:
            self.root.after(0, lambda: self._status(
                "Fetching post via embed player (no login)...", T.YELLOW))
            cmd = [PY_EXE, EMBED_HELPER, url]
            self.root.after(0, lambda: self._log("> " + " ".join(cmd), auto_show=False))

            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = subprocess.SW_HIDE

            r = subprocess.run(cmd, capture_output=True, text=True,
                               encoding="utf-8", errors="replace",
                               startupinfo=si, env=user_site_env(), timeout=90)
            try:
                items = json.loads((r.stdout or "").strip() or "[]")
            except Exception:
                items = []

            if not items:
                if r.stderr:
                    self.root.after(0, lambda e=r.stderr.strip()[-400:]: self._log(e, auto_show=False))
                self.root.after(0, lambda: self._status(
                    "Couldn't fetch anonymously — post may be private. "
                    "Set a sign-in browser or add cookies.txt, then retry.", T.RED))
                return

            m = re.search(r"instagram\.com/(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)", url)
            code = m.group(1) if m else "post"
            n, done = len(items), 0
            for i, it in enumerate(items, 1):
                ext = ".mp4" if it.get("type") == "video" else ".jpg"
                suffix = f" - {i} of {n}" if n > 1 else ""
                dest = os.path.join(out, f"instagram {code}{suffix}{ext}")
                self.root.after(0, lambda i=i, n=n: self._status(
                    f"Downloading {i} of {n}...", T.BLUE))
                dl = subprocess.run([CURL_EXE, "-sL", "--max-time", "180",
                                     it["url"], "-o", dest],
                                    capture_output=True, startupinfo=si)
                if dl.returncode == 0 and os.path.isfile(dest) and os.path.getsize(dest) > 0:
                    done += 1
                    self.last_file = dest
                    self.root.after(0, lambda p=100 * i / n: self._prog(p))
                    self.root.after(0, lambda d=dest: self._log(d, auto_show=False))

            if done:
                self.root.after(0, lambda: self._prog(100))
                self.root.after(0, lambda d=done: self._status(
                    f"Done — {d} file{'s' if d > 1 else ''} saved (no login needed)", T.GREEN))
                self.root.after(0, self._show_play_btn)
            else:
                self.root.after(0, lambda: self._status(
                    "Download failed. Check the log for details.", T.RED))

        except Exception as e:
            self.root.after(0, lambda err=str(e): self._status(f"Error: {err}", T.RED))
            self.root.after(0, lambda err=str(e): self._log(f"ERROR: {err}"))
        finally:
            self.downloading = False
            self.root.after(0, lambda: self.dl_btn.set("Download", "primary"))

    def _gdl_thread(self, url, out, browser):
        """Download an Instagram/Pinterest post via gallery-dl —
        gets every item in a carousel, images and videos alike."""
        self.last_file = None
        try:
            cmd = list(GDL_CMD) + ["-D", out]
            if browser != "none":
                cmd += ["--cookies-from-browser", browser]
            elif os.path.isfile(COOKIES_TXT):
                cmd += ["--cookies", COOKIES_TXT]
            cmd.append(url)
            self.root.after(0, lambda: self._log("> " + " ".join(cmd), auto_show=False))
            self.root.after(0, lambda: self._status("Fetching post (images + videos)...", T.YELLOW))

            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = subprocess.SW_HIDE

            env = None
            if GDL_PYTHONPATH:
                env = dict(os.environ)
                env["PYTHONPATH"] = GDL_PYTHONPATH + os.pathsep + env.get("PYTHONPATH", "")

            self.process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", startupinfo=si,
                bufsize=1, env=env)

            output_lines = []
            files = 0

            for line in self.process.stdout:
                line = line.strip()
                if not line: continue
                output_lines.append(line)

                path = line[2:].strip() if line.startswith("# ") else line
                if path.lower().endswith(MEDIA_EXTS):
                    files += 1
                    self.last_file = path if os.path.isabs(path) else os.path.join(out, os.path.basename(path))
                    self.root.after(0, lambda n=files: self._prog(100 * n / (n + 1)))
                    self.root.after(0, lambda n=files: self._status(
                        f"Downloading...  {n} file{'s' if n > 1 else ''}", T.BLUE))
                else:
                    is_err = "error" in line.lower() or "warning" in line.lower()
                    self.root.after(0, lambda l=line, a=is_err: self._log(l, auto_show=a))

            self.process.wait()
            rc = self.process.returncode

            if files > 0:
                self.root.after(0, lambda: self._prog(100))
                self.root.after(0, lambda n=files: self._status(
                    f"Done — {n} file{'s' if n > 1 else ''} saved", T.GREEN))
                self.root.after(0, lambda: self._log("\nDone!", auto_show=False))
                self.root.after(0, self._show_play_btn)
            else:
                full_output = "\n".join(output_lines)
                error_detail = self._friendly_gdl_error(full_output, url, browser) \
                    or f"Nothing was downloaded (exit code {rc}). Check the log for details."
                self.root.after(0, lambda msg=error_detail: self._status(msg, T.RED))

        except Exception as e:
            self.root.after(0, lambda: self._status(f"Error: {e}", T.RED))
            self.root.after(0, lambda err=str(e): self._log(f"ERROR: {err}"))
        finally:
            self.process = None
            self.downloading = False
            self.root.after(0, lambda: self.dl_btn.set("Download", "primary"))

    def _dl_thread(self, url, fmt, out, audio_only, playlist=False, browser="none", fmt_label=""):
        self.last_file = None
        try:
            cmd = self._build_cmd(url, fmt, out, audio_only, playlist, browser, fmt_label)
            self.root.after(0, lambda: self._log("> " + " ".join(cmd), auto_show=False))

            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = subprocess.SW_HIDE

            self.process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", startupinfo=si, bufsize=1)

            output_lines = []
            playlist_info = ""

            for line in self.process.stdout:
                line = line.strip()
                if not line: continue
                output_lines.append(line)

                # Track playlist progress (e.g. "[download] Downloading item 3 of 15")
                pl_match = re.search(r"\[download\] Downloading item (\d+) of (\d+)", line)
                if pl_match:
                    playlist_info = f"[{pl_match.group(1)}/{pl_match.group(2)}] "
                    self.root.after(0, lambda info=playlist_info: self._status(
                        f"Playlist: video {info.strip('[] ')}...", T.CYAN))

                if "[download] Destination:" in line:
                    self.last_file = line.split("[download] Destination:")[1].strip()
                elif "Merging formats into" in line:
                    m_file = re.search(r'Merging formats into "(.*?)"', line)
                    if m_file: self.last_file = m_file.group(1)
                elif "has already been downloaded" in line:
                    m_file = re.search(r'\[download\] (.*?) has already been', line)
                    if m_file: self.last_file = m_file.group(1)

                if POSTPROCESS_RE.search(line):
                    self.root.after(0, lambda: self._status("Finalizing...", T.CYAN))
                    self.root.after(0, lambda l=line: self._log(l, auto_show=False))
                    continue

                m = re.search(r"(\d+(?:\.\d+)?)%", line)
                if m:
                    pct = float(m.group(1))
                    speed = re.search(r"at\s+(\S+/s)", line)
                    eta = re.search(r"ETA\s+(\S+)", line)
                    parts = [f"{playlist_info}Downloading {pct:.1f}%"]
                    if speed: parts.append(speed.group(1))
                    if eta: parts.append(f"ETA {eta.group(1)}")
                    txt = "  ·  ".join(parts)
                    self.root.after(0, lambda p=pct: self._prog(p))
                    self.root.after(0, lambda s=txt: self._status(s, T.BLUE))
                else:
                    is_err = line.startswith(("ERROR", "WARNING"))
                    self.root.after(0, lambda l=line, a=is_err: self._log(l, auto_show=a))

            self.process.wait()
            rc = self.process.returncode

            if rc == 0:
                self.root.after(0, lambda: self._prog(100))
                self.root.after(0, lambda: self._status("Download complete", T.GREEN))
                self.root.after(0, lambda: self._log("\nDone!", auto_show=False))
                self.root.after(0, self._show_play_btn)
            else:
                full_output = "\n".join(output_lines)
                error_detail = self._friendly_error(full_output, url, browser) \
                    or f"Download failed (exit code {rc}). Check the log for details."
                self.root.after(0, lambda msg=error_detail: self._status(msg, T.RED))

        except Exception as e:
            self.root.after(0, lambda: self._status(f"Error: {e}", T.RED))
            self.root.after(0, lambda err=str(e): self._log(f"ERROR: {err}"))
        finally:
            self.process = None
            self.downloading = False
            self.root.after(0, lambda: self.dl_btn.set("Download", "primary"))

def main():
    root = tk.Tk()
    SnapGrabApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
