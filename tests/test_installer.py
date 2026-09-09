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
