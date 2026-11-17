# SnapGrab

A minimal Windows app that downloads videos from **YouTube, Instagram and Pinterest**, keeps them in a thumbnail **library**, and plays them in a fast built-in **player** with frame-by-frame stepping.

Built with Python + tkinter, on top of yt-dlp, gallery-dl, mpv and ffmpeg.

## Features

**Downloader**
- YouTube via yt-dlp, which updates itself on every launch so downloads keep working when sites change
- Instagram posts, reels and full carousels (images and videos). Public posts work without logging in, through Instagram's embed player
- Pinterest pins and carousels via gallery-dl
- Saves H.264/AAC MP4 (remuxed, not re-encoded), ready for After Effects and Premiere
- Optional sign-in browser cookies (or a `cookies.txt`) for private content

**Library**
- Thumbnail grid of your video folders, with durations
- Browser-style folder tabs that are remembered between sessions
- Thumbnails come from Windows' own Explorer thumbnail cache, so folders fill almost instantly
- Right-click a video: play, reveal in folder, open in default player, copy path

**Player** (mpv, with VLC as fallback)
- `.` / `,` step one frame forward / back, frame-accurate
- `space` play/pause · `←/→` skip 5 s · `↑/↓` volume
- `[` / `]` speed · `Backspace` reset speed · `m` mute
- `f` or double-click for fullscreen · `Esc` to exit fullscreen

## Requirements

- Windows 10/11
- [Python 3.12](https://www.python.org/downloads/)
- [ffmpeg](https://ffmpeg.org/) on PATH (`winget install ffmpeg`)
- [VLC](https://www.videolan.org/) (fallback player)

## Setup

1. Clone or download this repo into a folder.
2. Install the Python packages **into a `snapgrab_libs` folder next to the app**. SnapGrab loads its engines from there:
   ```
   pip install --target snapgrab_libs -r requirements.txt
   ```
3. Download [`yt-dlp.exe`](https://github.com/yt-dlp/yt-dlp/releases/latest) and put it next to `snapgrab.pyw`.
4. For the mpv player: download the latest `mpv-dev-x86_64-*.7z` from [mpv-winbuild-cmake releases](https://github.com/shinchiro/mpv-winbuild-cmake/releases), extract `libmpv-2.dll`, and put it in `snapgrab_libs`. Also put a copy there named `mpv-2.dll`. Without it, SnapGrab uses the VLC player instead.
5. Run it:
   ```
   pythonw snapgrab.pyw
   ```
   For a desktop icon, make a Windows shortcut to `pythonw.exe "path\to\snapgrab.pyw"` and set its icon to `snapgrab.ico`.

> Tip: launch it through a shortcut like this rather than compiling it into an `.exe`. Freshly compiled launchers that start Python tend to get flagged by Windows Defender as a false positive.

## Files

| File | What it is |
|---|---|
| `snapgrab.pyw` | Main app: window, downloader, routing between engines |
| `snapgrab_media.py` | Library grid, folder tabs, thumbnails, mpv/VLC players |
| `snapgrab_embed.py` | Login-free Instagram fetcher (hidden browser window reads the public embed player) |
| `snapgrab.ico` | App icon |

## Notes

- Only download content you have the right to download.
- Instagram may change its embed player at any time; if login-free downloads stop working, use a sign-in browser or `cookies.txt` instead.
