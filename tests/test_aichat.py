from pathlib import Path
from zipfile import ZipFile

from hub.aichat import PACKAGE, aichat_apk


def test_aichat_sources() -> None:
    root = Path(__file__).resolve().parents[1]
    mf = (root / "android/aichat/src/main/AndroidManifest.xml").read_text(encoding="utf-8")
    assert 'package="com.changanhub.chatload"' in mf
    assert 'android:versionName="1.0.5"' in mf
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
    assert "0.08f" in ui
    assert "0.10f" in ui
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
    assert "TTSEngine" in tts
    assert "AudioTrack" in tts
    assert "Elena" in tts
    assert "ACTION_PREPARE" in tts
    assert "TextToSpeech" not in tts
    store = (root / "android/aichat/src/main/java/com/changanhub/chat/ChatStore.java").read_text(
        encoding="utf-8"
    )
    assert "export-chat.json" in store
    build = (root / "scripts/build_aichat.py").read_text(encoding="utf-8")
    assert '"1.0.5"' in build
    assert PACKAGE == "com.changanhub.chatload"
    assert "SpeechRecognizer.isRecognitionAvailable" in ui
    assert "setVisibility(View.GONE)" in ui
    assert "iFlytek" in ui
    assert "Яндекс-клавиатура" in ui
    assert "Распознавание речи на этой ГУ недоступно (нет Google STT)" not in ui
    assert "WRAP_CONTENT, 40" not in ui
    assert "setAllCaps(false)" in ui
    assert "160f * dm.density" in ui
    assert "RHVoice" in ui
    assert "TextToSpeech" not in ui
    assert "TTSEngine" in tts
    assert "AudioTrack" in tts
    assert "Elena" in tts
    assert "loadLibrary(\"RHVoice_jni\")" in (
        root / "android/aichat/src/main/java/com/github/olga_yakovleva/rhvoice/TTSEngine.java"
    ).read_text(encoding="utf-8")
    jni = root / "android/aichat/src/main/jniLibs/arm64-v8a/libRHVoice_jni.so"
    assert jni.is_file() and jni.stat().st_size > 1_000_000
    voice = root / "android/aichat/src/main/assets/rhvoice/voices/elena/voice.info"
    lang = root / "android/aichat/src/main/assets/rhvoice/languages/Russian/language.info"
    assert "Elena" in voice.read_text(encoding="utf-8")
    assert "Russian" in lang.read_text(encoding="utf-8")
    assert "-A" in build
    assert "jniLibs" in build
    assert "ZIP_STORED" in build
    notice = (root / "android/aichat/NOTICE.txt").read_text(encoding="utf-8")
    assert "RHVoice" in notice
    assert "Elena" in notice
    assert (root / "scripts/vendor_rhvoice.py").is_file()
    assert "extractNativeLibs" in mf
    assert "TtsService.prepare" in ui
    assert "appVersionLabel" in ui
    models = root / "android/aichat/src/main/assets/rhvoice/voices/elena/16000"
    assert (models / "mgc.pdf").is_file() and (models / "mgc.pdf").stat().st_size > 100_000
    assert (models / "voice.data").is_file() and (models / "voice.data").stat().st_size > 1_000_000
    mock = (root / "docs/aichat-layout.html").read_text(encoding="utf-8")
    assert "AI Chat 1.0.5" in mock
    assert "RHVoice" in mock
    assert "Переведи" in mock
    assert "Объясни" in mock
    assert "Сократи" in mock
    layout = (root / "android/aichat/src/main/res/layout/activity_chat.xml").read_text(encoding="utf-8")
    assert 'android:id="@+id/composer"' in layout
    assert 'android:id="@+id/btn_send"' in layout
    assert 'android:textAllCaps="false"' in layout
    assert 'android:maxLines="1"' in layout
    assert 'android:layout_width="168dp"' not in layout
    assert 'android:minHeight="104dp"' in layout


def test_hub_installs_aichat() -> None:
    from hub.catalog import CATALOG, package_label

    src = Path("hub/gui.py").read_text(encoding="utf-8")
    assert "deploy_aichat" in src
    assert '"ours", "Наши приложения"' in src
    assert any(app.id == "aichat" for app in CATALOG)
    row = package_label("com.changanhub.chatload")
    assert "AI Chat" in row
    leftover = package_label("com.changanhub.aichat")
    assert "старый" in leftover.lower()
    leftover_rise = package_label("com.changanhub.chatrise")
    assert "старый" in leftover_rise.lower()
    assert "install_aichat" in Path("hub/aichat.py").read_text(encoding="utf-8")
    assert "RHVoice" in src
    assert "Ответы озвучивает системный TTS" not in src
    assert "RHVoice" in Path("hub/catalog.py").read_text(encoding="utf-8")
    assert "RHVoice" in Path("hub/aichat.py").read_text(encoding="utf-8")


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
        names = set(zf.namelist())
        mf = zf.read("AndroidManifest.xml")
        assert "com.changanhub.chatload".encode("utf-16-le") in mf
        certs = pkcs7.load_der_pkcs7_certificates(zf.read("META-INF/CERT.RSA"))
        assert certs[0].serial_number == CHANGAN_SERIAL
        assert "lib/arm64-v8a/libRHVoice_jni.so" in names
        so = zf.getinfo("lib/arm64-v8a/libRHVoice_jni.so")
        assert so.compress_type == 0
        assert any(n.startswith("assets/rhvoice/voices/elena/") for n in names)
        assert any(n.startswith("assets/rhvoice/languages/Russian/") for n in names)
        assert "assets/rhvoice/voices/elena/16000/mgc.pdf" in names
        assert "assets/rhvoice/voices/elena/16000/voice.data" in names


def test_apk_package_name_aichat(tmp_path: Path) -> None:
    from hub.installer import apk_package_name

    assert apk_package_name(tmp_path / "AiChat.apk") == "com.changanhub.chatload"
    assert apk_package_name(tmp_path / "aichat-changan.apk") == "com.changanhub.chatload"
