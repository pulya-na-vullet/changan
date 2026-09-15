from pathlib import Path
from zipfile import ZipFile

from hub.player import PACKAGE, player_apk


def test_player_sources_and_formats() -> None:
    root = Path(__file__).resolve().parents[1]
    src = (root / "android/player/src/main/java/com/changanhub/player/MediaTypes.java").read_text(
        encoding="utf-8"
    )
    for ext in ("mp3", "flac", "wav", "ogg", "m4a", "opus", "wma", "mp4", "mkv", "webm", "avi", "mov", "ts", "m2ts"):
        assert f'"{ext}"' in src
    mf = (root / "android/player/src/main/AndroidManifest.xml").read_text(encoding="utf-8")
    assert 'package="com.changanhub.pl1_1_3"' in mf
    assert "APP_MUSIC" not in mf
    assert 'android:versionName="1.1.3"' in mf
    assert 'android:minSdkVersion="28"' in mf
    assert 'android:targetSdkVersion="28"' in mf
    assert "RECORD_AUDIO" in mf
    assert "FOREGROUND_SERVICE" in mf
    assert "com.changanhub.player.BrowserActivity" in mf
    assert "com.changanhub.player.PlayerService" in mf
    viz = (root / "android/player/src/main/java/com/changanhub/player/VisualizerView.java").read_text(
        encoding="utf-8"
    )
    assert "Visualizer" in viz
    assert "MODE_PARTICLES" in viz
    assert "MODE_RADIAL" in viz
    eq = (root / "android/player/src/main/java/com/changanhub/player/PlayerService.java").read_text(
        encoding="utf-8"
    )
    assert "android.media.audiofx.Equalizer" in eq
    assert "BassBoost" in eq
    assert "Virtualizer" in eq
    assert "LoudnessEnhancer" in eq
    assert "ACTION_EQ_NAMED" in eq
    usb = (root / "android/player/src/main/java/com/changanhub/player/UsbMedia.java").read_text(
        encoding="utf-8"
    )
    assert "/mnt/media_rw" in usb
    assert "/storage/usb0" in usb
    assert "scanAll" in usb
    ui = (root / "android/player/src/main/java/com/changanhub/player/BrowserActivity.java").read_text(
        encoding="utf-8"
    )
    assert "0.08f" in ui
    assert "0.10f" in ui
    assert "tab_music" in ui
    prefs = (root / "android/player/src/main/java/com/changanhub/player/EqPrefs.java").read_text(
        encoding="utf-8"
    )
    assert "Bass Boost" in prefs
    srt = (root / "android/player/src/main/java/com/changanhub/player/SrtSubtitles.java").read_text(
        encoding="utf-8"
    )
    assert "-->" in srt
    fog = (root / "android/player/src/main/java/com/changanhub/player/GlFogView.java").read_text(
        encoding="utf-8"
    )
    assert "GLSurfaceView" in fog
    build = (root / "scripts/build_player.py").read_text(encoding="utf-8")
    assert '"1.1.3"' in build
    assert '"28"' in build
    assert PACKAGE == "com.changanhub.pl1_1_3"
    assert "effectiveShape" in eq
    assert "applyEffectiveBands" in eq
    assert "private void applyTone" not in eq
    assert "putTone" in prefs
    assert "toneDefault" in prefs
    rock = "{600, 400, 200, 0, -200, 0, 300, 500, 400, 300}"
    pop = "{-200, 0, 300, 400, 200, 0, 200, 300, 200, 0}"
    jazz = "{200, 100, 0, 200, 300, 200, 0, 100, 200, 100}"
    assert rock in prefs
    assert pop in prefs
    assert jazz in prefs
    assert rock != pop
    assert "memoryRoots" in usb
    assert "volumes(" in usb
    assert "/mnt/media_rw" in usb
    assert "addFromProcMounts" in usb
    assert "/proc/mounts" in usb
    assert "appVersionLabel" in ui
    assert "btn_volumes" in ui
    assert "refreshVolumes" in ui
    assert "showRoots()" in ui
    assert "160f * dm.density" in ui
    assert "ACTION_MEDIA_MOUNTED" in ui
    xml = (root / "android/player/src/main/res/layout/activity_browser.xml").read_text(encoding="utf-8")
    assert 'android:textSize="40sp"' in xml
    assert 'android:layout_height="88dp"' in xml
    assert 'android:id="@+id/btn_volumes"' in xml
    mock = (root / "docs/player-layout.html").read_text(encoding="utf-8")
    assert "Lamore Player 1.1.3" in mock
    assert "Флешки" in mock


def test_hub_installs_player() -> None:
    from hub.catalog import CATALOG, package_label

    src = Path("hub/gui.py").read_text(encoding="utf-8")
    assert "deploy_player" in src
    assert '"ours", "Наши приложения"' in src
    assert any(app.id == "player" for app in CATALOG)
    row = package_label("com.changanhub.pl1_1_3")
    assert "Lamore Player" in row
    leftover = package_label("com.changanhub.lamoreplayer")
    assert "старый" in leftover.lower()
    leftover_rise = package_label("com.changanhub.playrise")
    assert "старый" in leftover_rise.lower()
    leftover_load = package_label("com.changanhub.playload")
    assert "старый" in leftover_load.lower()
    assert "install_player" in Path("hub/player.py").read_text(encoding="utf-8")
    player_src = Path("hub/player.py").read_text(encoding="utf-8")
    assert "LEGACY_PACKAGES" in player_src
    assert "com.changanhub.lamoreplayer" in player_src
    assert "com.changanhub.playrise" in player_src
    assert "com.changanhub.playload" in player_src


def test_bundled_player_apk() -> None:
    apk = player_apk()
    assert apk.exists(), "Player.apk must be built and committed"
    from hub.apk_v2 import V2_MAGIC, has_v2_block
    from cryptography.hazmat.primitives.serialization import pkcs7
    from hub.signer import CHANGAN_SERIAL

    data = apk.read_bytes()
    assert V2_MAGIC in data
    assert has_v2_block(data)
    with ZipFile(apk) as zf:
        mf = zf.read("AndroidManifest.xml")
        assert "com.changanhub.pl1_1_3".encode("utf-16-le") in mf
        certs = pkcs7.load_der_pkcs7_certificates(zf.read("META-INF/CERT.RSA"))
        assert certs[0].serial_number == CHANGAN_SERIAL


def test_apk_package_name_player(tmp_path: Path) -> None:
    from hub.installer import apk_package_name

    assert apk_package_name(tmp_path / "Player.apk") == "com.changanhub.pl1_1_3"
    assert apk_package_name(tmp_path / "LamorePlayer.apk") == "com.changanhub.pl1_1_3"
