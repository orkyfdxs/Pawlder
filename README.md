# Pawlder

*(formerly SnapGrab — the code files keep their `snapgrab*` names)*

A minimal Windows app that downloads videos from **YouTube, Instagram and Pinterest**, and browses your **videos, images, music and documents** in fast, light libraries with built-in players and viewers.

Built with Python + tkinter, on top of yt-dlp, gallery-dl, mpv, ffmpeg, Pillow, pdfium and Edge WebView2.

## Features

**Downloader**
- YouTube via yt-dlp, which updates itself on every launch so downloads keep working when sites change
- Instagram posts, reels and full carousels (images and videos). Public posts work without logging in, through Instagram's embed player
- Pinterest pins and carousels via gallery-dl
- Saves H.264/AAC MP4 (remuxed, not re-encoded), ready for After Effects and Premiere
- Optional sign-in browser cookies (or a `cookies.txt`) for private content

**Libraries** — Videos, Images, Music and Docs, each with its own browser-style folder tabs (remembered between sessions)
- Virtualized grids: only the items on screen are drawn, so a folder of thousands of files opens in a fraction of a second and stays light on memory
- Thumbnails come from Windows' own Explorer thumbnail cache, so folders fill almost instantly
- **Videos**: thumbnails with durations
- **Images**: a Windows-Photos-style justified layout — real aspect ratios, rows that fill the width, grouped by month
- **Music**: album-art grid with track lengths (a ♪ tile when a song has no cover)
- **Docs**: PDF first-page covers with page counts, text-file previews, and icons for everything else
- Secondary-click any item to show it in its folder; Shift + secondary-click for the menu (open, reveal, open in default app, copy path)

**Viewers** — everything opens inside the main window, no extra windows to juggle. `Esc` or the window's ✕ goes back to the library, right where you were
- **Images**: opens instantly inside the app; `←/→` next/previous (neighbours are preloaded), mouse wheel zooms at the cursor, drag to pan, `0` fit, `1` 100 %, `f` fullscreen; animated GIF/WebP; phone-photo rotation
- **PDF**: Edge's own PDF viewer (zoom, search, select text, print), hosted inside the app. The engine starts with the first PDF (~1 s) and is then reused, so later PDFs open almost instantly; it shuts down after 5 idle minutes. Links in a PDF open in your normal browser. If Edge's engine can't start, a built-in pdfium page viewer takes over
- **Text** (`.txt .md .log .csv .json`): read-only dark viewer
- Word, Excel and other documents open in their default app

**Player** for videos and music (mpv, with VLC as fallback)
- `.` / `,` step one frame forward / back, frame-accurate
- `space` play/pause · `←/→` skip 5 s · `↑/↓` volume
- `[` / `]` speed · `Backspace` reset speed · `m` mute
- `f` or double-click for fullscreen · `Esc` to exit fullscreen, or to go back

## Requirements

- Windows 10/11
- [Python 3.12](https://www.python.org/downloads/)
- [ffmpeg](https://ffmpeg.org/) on PATH (`winget install ffmpeg`)
- [VLC](https://www.videolan.org/) (fallback player)
- Microsoft Edge WebView2 Runtime (built into Windows 11) for the PDF viewer and login-free Instagram

## Setup

1. Clone or download this repo into a folder.
2. Install the Python packages **into a `snapgrab_libs` folder next to the app**. Pawlder loads its engines from there:
   ```
   pip install --target snapgrab_libs -r requirements.txt
   ```
3. Download [`yt-dlp.exe`](https://github.com/yt-dlp/yt-dlp/releases/latest) and put it next to `snapgrab.pyw`.
4. For the mpv player: download the latest `mpv-dev-x86_64-*.7z` from [mpv-winbuild-cmake releases](https://github.com/shinchiro/mpv-winbuild-cmake/releases), extract `libmpv-2.dll`, and put it in `snapgrab_libs`. Without it, Pawlder uses the VLC player instead.
5. Run it:
   ```
   pythonw snapgrab.pyw
   ```
   For a desktop icon, make a Windows shortcut to `pythonw.exe "path\to\snapgrab.pyw"` and set its icon to `snapgrab.ico`.
   To pin it to the taskbar, put that shortcut in your Start menu folder (`%APPDATA%\Microsoft\Windows\Start Menu\Programs`), search for it in Start and choose **Pin to taskbar**. (Pinning the running window would pin plain `pythonw.exe` instead.)

> Tip: launch it through a shortcut like this rather than compiling it into an `.exe`. Freshly compiled launchers that start Python tend to get flagged by Windows Defender as a false positive.

## Files

| File | What it is |
|---|---|
| `snapgrab.pyw` | Main app: window, downloader, routing between engines |
| `snapgrab_media.py` | Libraries (virtualized grids, folder tabs, thumbnails), in-window mpv player, image, text and PDF viewers (Edge WebView2 + pdfium fallback) |
| `snapgrab_pdf.py` | Separate PDF viewer window (Edge WebView2) — last-resort fallback |
| `snapgrab_embed.py` | Login-free Instagram fetcher (hidden browser window reads the public embed player) |
| `snapgrab.ico` | App icon |

## Notes

- Only download content you have the right to download.
- Instagram may change its embed player at any time; if login-free downloads stop working, use a sign-in browser or `cookies.txt` instead.
