#!/usr/bin/env python3
"""Render PNG screenshots of the HTML layout mocks with headless Chrome."""

from __future__ import annotations

import http.server
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHROME = "/opt/google/chrome/chrome"
if not Path(CHROME).is_file():
    CHROME = shutil.which("google-chrome") or shutil.which("google-chrome-stable") or shutil.which("chromium")

SHOTS = [
    ("docs/player-layout.html?shot=1&s=music", 1920, 720, "docs/player-layout/player_tab_music_1920x720.png"),
    ("docs/player-layout.html?shot=1&s=video", 1920, 720, "docs/player-layout/player_tab_video_1920x720.png"),
    ("docs/player-layout.html?shot=1&s=eq", 1920, 720, "docs/player-layout/player_tab_eq_1920x720.png"),
    ("docs/player-layout.html?shot=1&s=viz", 1920, 720, "docs/player-layout/player_tab_viz_1920x720.png"),
    ("docs/player-layout.html?shot=1&s=now", 1920, 720, "docs/player-layout/player_now_playing_1920x720.png"),
    ("docs/player-layout.html?shot=1&s=film", 1920, 720, "docs/player-layout/player_video_fullscreen_1920x720.png"),
    ("docs/player-layout.html?shot=1&s=music&guides=1", 1920, 720, "docs/player-layout/player_layout_guides_1920x720.png"),
    ("docs/aichat-layout.html?shot=1&s=chat", 1920, 720, "docs/aichat-layout/aichat_tab_chat_1920x720.png"),
    ("docs/aichat-layout.html?shot=1&s=settings", 1920, 720, "docs/aichat-layout/aichat_tab_settings_1920x720.png"),
    ("docs/aichat-layout.html?shot=1&s=history", 1920, 720, "docs/aichat-layout/aichat_tab_history_1920x720.png"),
    ("docs/aichat-layout.html?shot=1&s=voice", 1920, 720, "docs/aichat-layout/aichat_tab_voice_1920x720.png"),
    ("quickbar/capture.html?state=list", 1080, 1920, "docs/quickbar-layout/quickbar_list_1080x1920.png"),
    ("quickbar/capture.html?state=system", 1080, 1920, "docs/quickbar-layout/quickbar_system_1080x1920.png"),
    ("quickbar/capture.html?state=hidden", 1080, 1920, "docs/quickbar-layout/quickbar_hidden_1080x1920.png"),
    ("quickbar/capture.html?state=hide", 1080, 1920, "docs/quickbar-layout/quickbar_hide_1080x1920.png"),
    ("quickbar/capture.html?state=reorder", 1080, 1920, "docs/quickbar-layout/quickbar_reorder_1080x1920.png"),
    ("quickbar/capture.html?state=usb", 1080, 1920, "docs/quickbar-layout/quickbar_usb_1080x1920.png"),
    ("quickbar/capture.html?state=search", 1080, 1920, "docs/quickbar-layout/quickbar_search_1080x1920.png"),
    ("quickbar/capture.html?state=collapsed", 1080, 1920, "docs/quickbar-layout/quickbar_collapsed_1080x1920.png"),
    ("quickbar/capture.html?state=peek", 1080, 1920, "docs/quickbar-layout/quickbar_peek_1080x1920.png"),
    ("quickbar/capture.html?state=stash&guide=1", 1080, 1920, "docs/quickbar-layout/quickbar_stash_1080x1920.png"),
]


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def chrome_shot(url: str, dest: Path, width: int, height: int, profile: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        CHROME,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--hide-scrollbars",
        "--disable-extensions",
        "--no-first-run",
        "--no-default-browser-check",
        f"--user-data-dir={profile}",
        "--force-device-scale-factor=1",
        f"--window-size={width},{height}",
        "--default-background-color=FF121A2B",
        "--virtual-time-budget=1500",
        f"--screenshot={dest}",
        url,
    ]
    subprocess.run(cmd, check=True, cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    data = dest.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n" or dest.stat().st_size < 8_000:
        raise SystemExit(f"bad screenshot: {dest} ({dest.stat().st_size} bytes)")


def main() -> int:
    if not CHROME:
        print("google-chrome is required", file=sys.stderr)
        return 1
    httpd = socketserver.TCPServer(("127.0.0.1", 0), QuietHandler)
    httpd.allow_reuse_address = True
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]
    time.sleep(0.2)
    profile = Path(tempfile.mkdtemp(prefix="chrome-layout-"))
    try:
        for path, width, height, out in SHOTS:
            url = f"http://127.0.0.1:{port}/{path}"
            dest = ROOT / out
            print(f"{out} ← {path}", flush=True)
            chrome_shot(url, dest, width, height, profile)
    finally:
        httpd.shutdown()
        httpd.server_close()
        shutil.rmtree(profile, ignore_errors=True)
    print(f"rendered {len(SHOTS)} screens", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
