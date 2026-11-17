"""
SnapGrab helper: fetch Instagram post media WITHOUT login via the public
embed player (instagram.com/p/<code>/embed/), which is open to anonymous
visitors. The embed page builds its media data with JavaScript, so this
runs it in a hidden WebView2 window and extracts the CDN URLs.

Usage:  python snapgrab_embed.py <instagram_url>
Output: JSON list on stdout: [{"type": "video"|"image", "url": "..."}]
        (empty list if the post is private or extraction failed)
"""

import os
import re
import sys
import time

# The SnapGrab launcher starts python with a stripped environment where
# APPDATA/LOCALAPPDATA/TEMP are missing or hold unexpanded %USERPROFILE%
# junk. WebView2 and pythonnet refuse to start without them, so rebuild
# them from this file's own location (…\Users\<name>\Downloads\…).
_home = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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

# Load pywebview + deps from the vendored folder beside the app, so this
# works regardless of how the app was launched or the AppData quirk.
_libs = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snapgrab_libs")
if os.path.isdir(_libs) and _libs not in sys.path:
    sys.path.insert(0, _libs)

EXTRACT_JS = r"""
(function(){
  try {
    var h = document.documentElement.outerHTML;
    var m = h.match(/"contextJSON":"((?:[^"\\]|\\.)*)"/);
    if (!m) return null;
    var ctx = JSON.parse(JSON.parse('"' + m[1] + '"'));
    var media = ctx.gql_data && ctx.gql_data.shortcode_media;
    if (!media) return null;
    var out = [];
    var edges = media.edge_sidecar_to_children && media.edge_sidecar_to_children.edges;
    var nodes = edges ? edges.map(function(e){ return e.node; }) : [media];
    nodes.forEach(function(n){
      if (n.video_url) out.push({type: "video", url: n.video_url});
      else if (n.display_url) out.push({type: "image", url: n.display_url});
    });
    return out.length ? JSON.stringify(out) : null;
  } catch (e) { return null; }
})()
"""


def main():
    if len(sys.argv) < 2:
        print("[]")
        return
    m = re.search(r"instagram\.com/(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)", sys.argv[1])
    if not m:
        print("[]")
        return
    embed_url = f"https://www.instagram.com/p/{m.group(1)}/embed/captioned/"

    import webview

    result = {"json": None}

    def worker(window):
        deadline = time.time() + 25
        while time.time() < deadline:
            try:
                r = window.evaluate_js(EXTRACT_JS)
                if r:
                    result["json"] = r
                    break
            except Exception:
                pass
            time.sleep(0.7)
        try:
            window.destroy()
        except Exception:
            pass

    w = webview.create_window("snapgrab", embed_url, hidden=True,
                              width=500, height=700)
    webview.start(worker, w, private_mode=True)

    print(result["json"] or "[]")


if __name__ == "__main__":
    main()
