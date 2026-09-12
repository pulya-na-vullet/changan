from pathlib import Path
from zipfile import ZipFile

from hub.aichat import PACKAGE, aichat_apk


def test_aichat_sources() -> None:
    root = Path(__file__).resolve().parents[1]
    mf = (root / "android/aichat/src/main/AndroidManifest.xml").read_text(encoding="utf-8")
    assert 'package="com.changanhub.aichat"' in mf
    assert 'android:versionName="1.0.0"' in mf
    assert 'android:minSdkVersion="28"' in mf
    assert 'android:targetSdkVersion="28"' in mf
    assert "INTERNET" in mf
    assert "RECORD_AUDIO" in mf
    assert "FOREGROUND_SERVICE" in mf
    assert "com.changanhub.chat.ChatActivity" in mf
    assert "com.changanhub.chat.TtsService" in mf
    ui = (root / "android/aichat/src/main/java/com/changanhub/chat/ChatActivity.java").read_text(
        encoding="utf-8"
    )
    assert "0.20f" in ui
    assert "0.30f" in ui
    assert "tab_chat" in ui
    llm = (root / "android/aichat/src/main/java/com/changanhub/chat/Llm.java").read_text(encoding="utf-8")
    assert "api.deepseek.com" in (root / "android/aichat/src/main/java/com/changanhub/chat/Prefs.java").read_text(
        encoding="utf-8"
    )
    assert "chat/completions" in llm
    assert "llm.api.cloud.yandex.net" in (
        root / "android/aichat/src/main/java/com/changanhub/chat/Prefs.java"
    ).read_text(encoding="utf-8")
    assert "text/event-stream" in (root / "android/aichat/src/main/java/com/changanhub/chat/Net.java").read_text(
        encoding="utf-8"
    )
    assert "AndroidKeyStore" in (
        root / "android/aichat/src/main/java/com/changanhub/chat/SecretBox.java"
    ).read_text(encoding="utf-8")
    tts = (root / "android/aichat/src/main/java/com/changanhub/chat/TtsService.java").read_text(
        encoding="utf-8"
    )
    assert "TextToSpeech" in tts
    assert 'new Locale("ru", "RU")' in tts
    store = (root / "android/aichat/src/main/java/com/changanhub/chat/ChatStore.java").read_text(
        encoding="utf-8"
    )
    assert "export-chat.json" in store
    build = (root / "scripts/build_aichat.py").read_text(encoding="utf-8")
    assert '"1.0.0"' in build
    assert PACKAGE == "com.changanhub.aichat"


def test_hub_installs_aichat() -> None:
    from hub.catalog import CATALOG, package_label

    src = Path("hub/gui.py").read_text(encoding="utf-8")
    assert "deploy_aichat" in src
    assert '"aichat", "Чат ИИ"' in src
    assert any(app.id == "aichat" for app in CATALOG)
    row = package_label("com.changanhub.aichat")
    assert "AI Chat" in row
    assert "install_aichat" in Path("hub/aichat.py").read_text(encoding="utf-8")


def test_bundled_aichat_apk() -> None:
    apk = aichat_apk()
    assert apk.exists(), "AiChat.apk must be built and committed"
    from hub.apk_v2 import V2_MAGIC, has_v2_block
    from cryptography.hazmat.primitives.serialization import pkcs7
    from hub.signer import CHANGAN_SERIAL

    data = apk.read_bytes()
    assert V2_MAGIC in data
    assert has_v2_block(data)
    with ZipFile(apk) as zf:
        mf = zf.read("AndroidManifest.xml")
        assert "com.changanhub.aichat".encode("utf-16-le") in mf
        certs = pkcs7.load_der_pkcs7_certificates(zf.read("META-INF/CERT.RSA"))
        assert certs[0].serial_number == CHANGAN_SERIAL


def test_apk_package_name_aichat(tmp_path: Path) -> None:
    from hub.installer import apk_package_name

    assert apk_package_name(tmp_path / "AiChat.apk") == "com.changanhub.aichat"
    assert apk_package_name(tmp_path / "aichat-changan.apk") == "com.changanhub.aichat"
