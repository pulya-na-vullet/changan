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
        self.binary = Path("adb")

    def connected(self) -> bool:
        return True

    def install_stream(self, apk: Path, timeout: int = 180) -> CommandResult:
        return CommandResult(False, "", "INSTALL_FAILED_USER_RESTRICTED", 1, [])

    def push(self, local: Path, remote: str, timeout: int = 180) -> CommandResult:
        self.pushed.append(remote)
        return CommandResult(True, f"{local} -> {remote}", "", 0, [])

    def raw(self, args: list[str], timeout: int = 45, input_text: str | None = None) -> CommandResult:
        return CommandResult(True, "", "", 0, args)

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
    with patch("hub.installer.sign_apk_with_method", return_value=(apk, "python-v1v2")):
        report = install_apk(fake, apk, already_signed=True)

    assert report.ok
    assert report.method.startswith("pm install")
    assert fake.pushed
    installs = [cmd for cmd in fake.shells if cmd.startswith("pm install")]
    assert len(installs) == 1
    assert installs[0].startswith("pm install -r -t -g ")
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
    with patch("hub.installer.sign_apk_with_method", return_value=(apk, "python-v1v2")):
        report = install_apk(fake, apk, already_signed=True, progress=lambda m, p: steps.append((m, p)))

    assert report.ok
    assert any("push" in msg.lower() for msg, _ in steps)
    assert any("pm install" in msg.lower() for msg, _ in steps)
    assert steps[0][1] <= steps[-1][1]


def test_classify_install_steps() -> None:
    from hub.installer import classify_install_step

    assert classify_install_step("Шаг 1/5: подпись APK под Changan…") == "sign"
    assert classify_install_step("push → /sdcard/Download/x.apk") == "push"
    assert classify_install_step("выполняю pm install -r -t -g /data/local/tmp/x") == "pm"
    assert classify_install_step("выполняю pm uninstall com.changanhub.quickbar") == "pm"
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
    with patch("hub.installer.sign_apk_with_method", return_value=(apk, "python-v1v2")):
        report = install_apk(fake, apk, already_signed=True)
    assert not report.ok
    assert any("NO_CERTIFICATES" in line or "не установлен" in line.lower() for line in report.log)


def test_install_reports_not_auth(tmp_path: Path) -> None:
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
                "Failure [-118: com.changanhub.quickbar is not auth,install failed!]",
                "please input verify password: verify success!",
                1,
                [],
            )
        return CommandResult(True, "", "", 0, [])

    fake.shell = fail_install  # type: ignore[method-assign]
    fake.try_root = lambda: (_ for _ in ()).throw(AssertionError("adb root must not be used"))
    with patch("hub.installer.sign_apk_with_method", return_value=(apk, "python-v1v2")):
        report = install_apk(fake, apk, already_signed=True, package="com.changanhub.quickbar")
    assert not report.ok
    assert any("-118" in line or "not auth" in line.lower() for line in report.log)
    assert any("белого" in line.lower() or "списка" in line.lower() for line in report.log)
    assert not any(cmd.startswith("pm uninstall") for cmd in fake.shells)
    assert any("не снимал" in line.lower() for line in report.log)


def test_discover_hu_signer_serial(tmp_path: Path) -> None:
    from hub.installer import discover_hu_signer_serial
    from hub.signer import CHANGAN_SERIAL, sign_apk, ensure_keystore
    from unittest.mock import patch
    import zipfile

    apk = tmp_path / "newpipe.apk"
    with zipfile.ZipFile(apk, "w") as zf:
        zf.writestr("AndroidManifest.xml", b"mf")
        zf.writestr("classes.dex", b"dex")
    store = ensure_keystore(tmp_path / "certs")
    with patch("hub.signer.find_apksigner", return_value=None):
        signed = sign_apk(apk, tmp_path / "newpipe-signed.apk", keystore=store)

    fake = FakeAdb()

    def shell(command: str, timeout: int = 60) -> CommandResult:
        if command.startswith("pm path org.schabi.newpipe"):
            return CommandResult(True, "package:/data/app/newpipe.apk", "", 0, [])
        return CommandResult(True, "", "", 0, [])

    def raw(args: list[str], timeout: int = 45, input_text: str | None = None) -> CommandResult:
        if args and args[0] == "pull":
            Path(args[2]).write_bytes(signed.read_bytes())
            return CommandResult(True, "pulled", "", 0, args)
        return CommandResult(True, "", "", 0, args)

    fake.shell = shell  # type: ignore[method-assign]
    fake.raw = raw  # type: ignore[method-assign]
    notes: list[str] = []
    serial = discover_hu_signer_serial(fake, lambda m, p: notes.append(m))
    assert serial == CHANGAN_SERIAL
    assert any("newpipe" in line.lower() for line in notes)


def test_matching_signature_replaces_without_uninstall(tmp_path: Path) -> None:
    apk = tmp_path / "QuickBar.apk"
    with zipfile.ZipFile(apk, "w") as zf:
        zf.writestr("AndroidManifest.xml", b"mf")
        zf.writestr("classes.dex", b"dex")

    fake = FakeAdb()
    with patch("hub.installer.sign_apk_with_method", return_value=(apk, "python-v1v2")):
        report = install_apk(fake, apk, already_signed=True, package="com.changanhub.quickbar")
    assert report.ok
    assert not any(cmd.startswith("pm uninstall") for cmd in fake.shells)
    installs = [cmd for cmd in fake.shells if cmd.startswith("pm install")]
    assert len(installs) == 1
    assert "-r -t -g" in installs[0]


def test_apk_package_name_quickbar_is_new_id(tmp_path: Path) -> None:
    from hub.installer import apk_package_name

    assert apk_package_name(tmp_path / "QuickBar.apk") == "com.changanhub.quicklane"
    assert apk_package_name(tmp_path / "QuickBar-changan.apk") == "com.changanhub.quicklane"


def test_install_retries_after_short_uninstall_on_signature_mismatch(tmp_path: Path) -> None:
    apk = tmp_path / "demo.apk"
    with zipfile.ZipFile(apk, "w") as zf:
        zf.writestr("AndroidManifest.xml", b"mf")
        zf.writestr("classes.dex", b"dex")

    fake = FakeAdb()
    installs = {"n": 0}

    def shell(command: str, timeout: int = 60) -> CommandResult:
        fake.shells.append(command)
        if command.startswith("pm install"):
            installs["n"] += 1
            if installs["n"] == 1:
                return CommandResult(
                    False,
                    "Failure [INSTALL_FAILED_UPDATE_INCOMPATIBLE: Package com.changanhub.quicklane signatures do not match previously installed version; ignoring!]",
                    "",
                    1,
                    [],
                )
            return CommandResult(True, "Success", "", 0, [])
        if command.startswith("pm uninstall"):
            return CommandResult(True, "Success", "", 0, [])
        return CommandResult(True, "", "", 0, [])

    fake.shell = shell  # type: ignore[method-assign]
    with patch("hub.installer.sign_apk_with_method", return_value=(apk, "python-v1v2")):
        report = install_apk(fake, apk, already_signed=True, package="com.changanhub.quicklane")
    assert report.ok
    assert any(cmd.startswith("pm uninstall --user 0 com.changanhub.quicklane") for cmd in fake.shells)
    assert installs["n"] == 2
    assert any("pm enable --user 0 com.changanhub.quicklane" in cmd for cmd in fake.shells)


def test_install_keeps_auth_package_if_uninstall_blocked(tmp_path: Path) -> None:
    apk = tmp_path / "demo.apk"
    with zipfile.ZipFile(apk, "w") as zf:
        zf.writestr("AndroidManifest.xml", b"mf")
        zf.writestr("classes.dex", b"dex")

    fake = FakeAdb()

    def shell(command: str, timeout: int = 60) -> CommandResult:
        fake.shells.append(command)
        if command.startswith("pm install"):
            return CommandResult(
                False,
                "Failure [INSTALL_FAILED_UPDATE_INCOMPATIBLE: Package com.changanhub.quickdock signatures do not match previously installed version; ignoring!]",
                "",
                1,
                [],
            )
        if command.startswith("pm uninstall"):
            return CommandResult(False, "", "is auth app, not allow delete!", 1, [])
        return CommandResult(True, "", "", 0, [])

    fake.shell = shell  # type: ignore[method-assign]
    with patch("hub.installer.sign_apk_with_method", return_value=(apk, "python-v1v2")):
        report = install_apk(fake, apk, already_signed=True, package="com.changanhub.quickdock")
    assert not report.ok
    assert any(cmd.startswith("pm uninstall --user 0") for cmd in fake.shells)
    assert sum(1 for cmd in fake.shells if cmd.startswith("pm install")) == 1
    assert any("quicklane" in line.lower() or "not allow delete" in line.lower() for line in report.log)

