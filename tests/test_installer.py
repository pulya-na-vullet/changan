import zipfile
from pathlib import Path
from unittest.mock import patch

from hub.adb import CommandResult
from hub.installer import install_apk


class FakeAdb:
    def __init__(self) -> None:
        self.connected_flag = True
        self.pushed = []
        self.shells = []

    def connected(self) -> bool:
        return True

    def install_stream(self, apk: Path, timeout: int = 180) -> CommandResult:
        return CommandResult(False, "", "INSTALL_FAILED_USER_RESTRICTED", 1, [])

    def push(self, local: Path, remote: str, timeout: int = 180) -> CommandResult:
        self.pushed.append(remote)
        return CommandResult(True, f"{local} -> {remote}", "", 0, [])

    def shell(self, command: str, timeout: int = 60) -> CommandResult:
        self.shells.append(command)
        if command.startswith("pm install"):
            return CommandResult(True, "Success", "", 0, [])
        return CommandResult(True, "", "", 0, [])

    def clear_launcher_cache(self):
        return [CommandResult(True, "Success", "", 0, [])]

    def try_root(self) -> CommandResult:
        return CommandResult(False, "", "not rooted", 1, [])

    def try_remount(self) -> CommandResult:
        return CommandResult(False, "", "denied", 1, [])


def test_install_falls_back_to_pm(tmp_path: Path) -> None:
    apk = tmp_path / "demo.apk"
    with zipfile.ZipFile(apk, "w") as zf:
        zf.writestr("AndroidManifest.xml", b"mf")
        zf.writestr("classes.dex", b"dex")

    fake = FakeAdb()
    with patch("hub.installer.sign_apk", return_value=apk):
        report = install_apk(fake, apk, already_signed=True)

    assert report.ok
    assert report.method.startswith("pm install")
    assert fake.pushed
    assert any(cmd.startswith("pm install") for cmd in fake.shells)


def test_install_never_calls_adb_install(tmp_path: Path) -> None:
    apk = tmp_path / "demo.apk"
    with zipfile.ZipFile(apk, "w") as zf:
        zf.writestr("AndroidManifest.xml", b"mf")
        zf.writestr("classes.dex", b"dex")

    fake = FakeAdb()

    def boom(*_args, **_kwargs):
        raise AssertionError("adb install must not be used on Feiyu")

    fake.install_stream = boom  # type: ignore[method-assign]
    steps: list[tuple[str, int]] = []
    with patch("hub.installer.sign_apk", return_value=apk):
        report = install_apk(fake, apk, already_signed=True, progress=lambda m, p: steps.append((m, p)))

    assert report.ok
    assert any("push" in msg.lower() for msg, _ in steps)
    assert any("pm install" in msg.lower() for msg, _ in steps)
    assert steps[0][1] <= steps[-1][1]


def test_classify_install_steps() -> None:
    from hub.installer import classify_install_step

    assert classify_install_step("Шаг 1/5: подпись APK под Changan…") == "sign"
    assert classify_install_step("push → /sdcard/Download/x.apk") == "push"
    assert classify_install_step("выполняю pm install -r -t /sdcard/x") == "pm"
    assert classify_install_step("запуск: am start -n com.changanhub.quickbar/.MainActivity") == "start"


def test_install_reports_no_certificates(tmp_path: Path) -> None:
    apk = tmp_path / "demo.apk"
    with zipfile.ZipFile(apk, "w") as zf:
        zf.writestr("AndroidManifest.xml", b"mf")
        zf.writestr("classes.dex", b"dex")

    fake = FakeAdb()

    def fail_install(command: str, timeout: int = 60) -> CommandResult:
        fake.shells.append(command)
        if command.startswith("pm install"):
            return CommandResult(
                False,
                "Failure [INSTALL_PARSE_FAILED_NO_CERTIFICATES: PKCS9 SMIMECapability attribute not supported.]",
                "",
                1,
                [],
            )
        return CommandResult(True, "", "", 0, [])

    fake.shell = fail_install  # type: ignore[method-assign]
    fake.try_root = lambda: (_ for _ in ()).throw(AssertionError("adb root must not be used"))
    with patch("hub.installer.sign_apk", return_value=apk):
        report = install_apk(fake, apk, already_signed=True)
    assert not report.ok
    assert any("NO_CERTIFICATES" in line or "не установлен" in line.lower() for line in report.log)
