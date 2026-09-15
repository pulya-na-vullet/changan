from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parents[1]


def png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", path.name
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def test_player_and_chat_layout_pngs() -> None:
    player = ROOT / "docs/player-layout"
    chat = ROOT / "docs/aichat-layout"
    for name in (
        "player_tab_music_1920x720.png",
        "player_tab_video_1920x720.png",
        "player_tab_eq_1920x720.png",
        "player_tab_viz_1920x720.png",
        "player_now_playing_1920x720.png",
        "player_video_fullscreen_1920x720.png",
        "player_layout_guides_1920x720.png",
    ):
        path = player / name
        assert path.is_file(), name
        assert path.stat().st_size > 12_000, name
        width, height = png_size(path)
        assert (width, height) == (1920, 720), name
    for name in (
        "aichat_tab_chat_1920x720.png",
        "aichat_tab_settings_1920x720.png",
        "aichat_tab_history_1920x720.png",
        "aichat_tab_voice_1920x720.png",
    ):
        path = chat / name
        assert path.is_file(), name
        assert path.stat().st_size > 12_000, name
        assert png_size(path) == (1920, 720), name
    mock = (ROOT / "docs/player-layout.html").read_text(encoding="utf-8")
    assert "Баланс L / R" in mock
    assert "Субтитры" in mock
    assert "html.shot" in mock
    chat_mock = (ROOT / "docs/aichat-layout.html").read_text(encoding="utf-8")
    assert "Копир" in chat_mock
    assert "Озвук" in chat_mock
    assert "Елена (RHVoice)" in chat_mock
    assert "html.shot" in chat_mock


def test_quickbar_layout_pngs() -> None:
    folder = ROOT / "docs/quickbar-layout"
    for state in (
        "list",
        "system",
        "hidden",
        "hide",
        "reorder",
        "usb",
        "search",
        "collapsed",
        "peek",
        "stash",
    ):
        path = folder / f"quickbar_{state}_1080x1920.png"
        assert path.is_file(), path.name
        assert path.stat().st_size > 12_000, path.name
        assert png_size(path) == (1080, 1920), path.name
    script = (ROOT / "scripts/render_layouts.py").read_text(encoding="utf-8")
    assert "player-layout.html" in script
    assert "aichat-layout.html" in script
    assert "quickbar/capture.html" in script
