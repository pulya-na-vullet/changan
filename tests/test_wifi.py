from pathlib import Path
from zipfile import ZipFile

from hub.wifi import JAVA_SERVICE, PACKAGE, install_wifi, start_wifi, wifi_apk
from hub.windowed import FREEFORM_SHELL, INSET_PACKAGES, enable_freeform, start_wifi_settings_windowed


class FakeAdb:
    def __init__(self) -> None:
        self.shells: list[str] = []

    def shell(self, command: str, timeout: int = 60):
        from hub.adb import CommandResult

        self.shells.append(command)
        return CommandResult(True, "", "", 0, [])


def test_bundled_wifi_apk() -> None:
    apk = wifi_apk()
    assert apk.exists(), "WifiButton.apk is vendored from changan_wifi"
    with ZipFile(apk) as zf:
        mf = zf.read("AndroidManifest.xml")
        assert "com.lamore.wifibutton".encode("utf-16-le") in mf
        assert "FloatingService".encode("utf-16-le") in mf
        assert "1.4".encode("utf-16-le") in mf


def test_wifi_grants_and_second_vision() -> None:
    fake = FakeAdb()
    lines = start_wifi(fake, second_vision=True)
    joined = "\n".join(fake.shells + lines)
    assert PACKAGE in joined
    assert "SYSTEM_ALERT_WINDOW" in joined
    assert JAVA_SERVICE.split(".")[-1] in joined or "FloatingService" in joined
    assert "WIFI_SETTINGS" in joined or "android.settings.WIFI_SETTINGS" in joined
    assert "windowingMode 5" in joined
    assert "enable_freeform_support" in joined
    assert "второй экран" in "\n".join(lines)


def test_enable_freeform_and_inset_list() -> None:
    fake = FakeAdb()
    enable_freeform(fake)
    assert any("enable_freeform_support" in cmd for cmd in fake.shells)
    assert any("force_resizable_activities" in cmd for cmd in FREEFORM_SHELL)
    assert "ru.dublgis.dgismobile" in INSET_PACKAGES
    assert "com.lamore.wifibutton" in INSET_PACKAGES
    start_wifi_settings_windowed(fake)
    assert any("WIFI_SETTINGS" in cmd for cmd in fake.shells)


def test_hub_installs_wifi_card() -> None:
    src = Path("hub/gui.py").read_text(encoding="utf-8")
    assert "deploy_wifi" in src
    assert "resume_wifi" in src
    assert "wifi_install_btn" in src
    assert "install_wifi" in Path("hub/wifi.py").read_text(encoding="utf-8")
    catalog = Path("hub/catalog.py").read_text(encoding="utf-8")
    assert 'id="wifi"' in catalog
    assert "com.lamore.wifibutton" in catalog
    assert "changan_wifi" in catalog
    assert "исходники не копируются" in catalog.lower() or "исходники не копиру" in catalog.lower()


def test_missing_wifi_apk_message(tmp_path, monkeypatch) -> None:
    from hub import wifi as wifi_mod

    monkeypatch.setattr(wifi_mod, "wifi_apk", lambda: tmp_path / "missing.apk")
    lines = install_wifi(FakeAdb())
    assert any("не найден" in line.lower() for line in lines)
