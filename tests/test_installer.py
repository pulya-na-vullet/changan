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

    assert apk_package_name(tmp_path / "QuickBar.apk") == "com.changanhub.quickrise"
    assert apk_package_name(tmp_path / "QuickBar-changan.apk") == "com.changanhub.quickrise"
    assert apk_package_name(tmp_path / "quicklane.apk") == "com.changanhub.quickrise"
    assert apk_package_name(tmp_path / "quickkeep.apk") == "com.changanhub.quickrise"


def test_install_skips_uninstall_on_overlay_signature_mismatch(tmp_path: Path) -> None:
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
            return CommandResult(
                False,
                "Failure [INSTALL_FAILED_UPDATE_INCOMPATIBLE: Package com.changanhub.quicklane signatures do not match previously installed version; ignoring!]",
                "",
                1,
                [],
            )
        if command.startswith("pm uninstall"):
            return CommandResult(True, "Success", "", 0, [])
        if command.startswith("pm path"):
            return CommandResult(True, "package:/data/app/demo/base.apk", "", 0, [])
        return CommandResult(True, "", "", 0, [])

    fake.shell = shell  # type: ignore[method-assign]
    with patch("hub.installer.sign_apk_with_method", return_value=(apk, "python-v1v2")):
        report = install_apk(fake, apk, already_signed=True, package="com.changanhub.quickrise")
    assert not report.ok
    assert not any(cmd.startswith("pm uninstall") for cmd in fake.shells)
    assert installs["n"] == 1
    assert any("not allow delete" in line.lower() or "quickrise" in line.lower() for line in report.log)
    assert any("pm disable-user --user 0 com.changanhub.quicklane" in cmd for cmd in fake.shells)


def test_install_retries_uninstall_for_non_overlay_mismatch(tmp_path: Path) -> None:
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
                    "Failure [INSTALL_FAILED_UPDATE_INCOMPATIBLE: Package mobi.zona signatures do not match previously installed version; ignoring!]",
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
        report = install_apk(fake, apk, already_signed=True, package="mobi.zona")
    assert report.ok
    assert any(cmd.startswith("pm uninstall --user 0 mobi.zona") for cmd in fake.shells)
    assert installs["n"] == 2


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
    assert not any(cmd.startswith("pm uninstall --user 0") for cmd in fake.shells)
    assert sum(1 for cmd in fake.shells if cmd.startswith("pm install")) == 1
    assert any("quickrise" in line.lower() or "not allow delete" in line.lower() for line in report.log)


def test_parse_package_paths() -> None:
    from hub.installer import parse_package_paths, parse_pm_path

    text = (
        "please input verify password: verify success!\n"
        "package:/data/app/~~x==/ru.hackchan.launcher-y/base.apk=ru.hackchan.launcher\n"
        "package:/system/priv-app/Settings/Settings.apk=com.android.settings\n"
    )
    mapping = parse_package_paths(text)
    assert mapping["ru.hackchan.launcher"].endswith("base.apk")
    assert mapping["com.android.settings"].endswith("Settings.apk")
    assert parse_pm_path("package:/data/app/foo.apk") == "/data/app/foo.apk"
    assert parse_pm_path(
        "please input verify password: verify success!\npackage:/data/app/foo.apk\n"
    ) == "/data/app/foo.apk"


def test_hu_serial_cache_is_per_device(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("hub.paths.app_data", lambda: tmp_path)
    from hub.installer import load_cached_hu_serial, save_cached_hu_serial

    save_cached_hu_serial(0x111, "AHFPF_OWNER")
    save_cached_hu_serial(0x222, "AHFPF_RUS")
    (tmp_path / "certs" / "hu_serial.txt").write_text("0xddb66eefd98476f3", encoding="utf-8")
    assert load_cached_hu_serial("AHFPF_OWNER") == 0x111
    assert load_cached_hu_serial("AHFPF_RUS") == 0x222
    assert load_cached_hu_serial("OTHER") is None
    assert load_cached_hu_serial(None) is None


def test_discover_uses_third_party_list(tmp_path) -> None:
    from hub.installer import discover_hu_signer_serial
    from hub.signer import CHANGAN_SERIAL, sign_apk, ensure_keystore

    apk = tmp_path / "hack.apk"
    with zipfile.ZipFile(apk, "w") as zf:
        zf.writestr("AndroidManifest.xml", b"mf")
        zf.writestr("classes.dex", b"dex")
    store = ensure_keystore(tmp_path / "certs")
    with patch("hub.signer.find_apksigner", return_value=None):
        signed = sign_apk(apk, tmp_path / "hack-signed.apk", keystore=store)

    fake = FakeAdb()
    path_calls: list[str] = []

    def shell(command: str, timeout: int = 60) -> CommandResult:
        if command.startswith("pm list packages"):
            return CommandResult(
                True,
                "package:/data/app/hack/base.apk=ru.hackchan.launcher",
                "",
                0,
                [],
            )
        if command.startswith("pm path"):
            path_calls.append(command)
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
    assert not path_calls
    assert any("hackchan" in line.lower() for line in notes)


def test_install_resigns_on_118_when_hu_serial_differs(tmp_path) -> None:
    from hub.signer import CHANGAN_SERIAL

    apk = tmp_path / "QuickBar.apk"
    with zipfile.ZipFile(apk, "w") as zf:
        zf.writestr("AndroidManifest.xml", b"mf")
        zf.writestr("classes.dex", b"dex")

    fake = FakeAdb()
    fake.serial = "AHFPF6643S69270176"
    installs = {"n": 0}

    def shell(command: str, timeout: int = 60) -> CommandResult:
        fake.shells.append(command)
        if command.startswith("pm install"):
            installs["n"] += 1
            if installs["n"] == 1:
                return CommandResult(
                    False,
                    "Failure [-118: com.changanhub.quickrise is not auth,install failed!]",
                    "please input verify password: verify success!",
                    1,
                    [],
                )
            return CommandResult(True, "Success", "", 0, [])
        return CommandResult(True, "", "", 0, [])

    fake.shell = shell  # type: ignore[method-assign]
    other = 0xABCDEF
    with (
        patch("hub.paths.app_data", return_value=tmp_path),
        patch("hub.installer.load_cached_hu_serial", return_value=None),
        patch("hub.installer.discover_hu_signer_candidates", side_effect=[[], [other]]),
        patch("hub.installer.sign_apk_with_method", return_value=(apk, "python-v1v2")),
        patch("hub.installer.ensure_keystore") as ek,
        patch("hub.installer.apk_certificate_serials", return_value=[CHANGAN_SERIAL]),
        patch("hub.installer.save_cached_hu_serial"),
    ):
        report = install_apk(fake, apk, already_signed=False, package="com.changanhub.quickrise")
    assert report.ok
    assert installs["n"] == 2
    serials = [call.kwargs.get("serial") for call in ek.call_args_list]
    assert CHANGAN_SERIAL in serials
    assert other in serials
    assert any("повторная" in line.lower() or "другой" in line.lower() for line in report.log)


def test_extract_embedded_serials_finds_cookbook_and_other() -> None:
    from hub.installer import extract_embedded_serials
    from hub.signer import CHANGAN_SERIAL

    blob = (
        b"xxCertificateManager"
        + CHANGAN_SERIAL.to_bytes(8, "little")
        + b"not auth"
        + (0xABCDEF123456).to_bytes(8, "little")
        + b" serial=00aabbccddeeff11 "
    )
    found = extract_embedded_serials(blob)
    assert CHANGAN_SERIAL in found
    assert 0xAABBCCDDEEFF11 in found


def test_embedded_serials_in_apk(tmp_path: Path) -> None:
    from hub.installer import embedded_serials_in_apk

    apk = tmp_path / "vecentek.apk"
    with zipfile.ZipFile(apk, "w") as zf:
        zf.writestr("classes.dex", b"xx not auth 0011223344556677 yy")
        zf.writestr("AndroidManifest.xml", b"mf")
    found = embedded_serials_in_apk(apk)
    assert 0x11223344556677 in found


def test_discover_uses_vecentek_when_no_sideload(tmp_path: Path) -> None:
    from hub.installer import discover_hu_signer_candidates

    apk = tmp_path / "VecentekApp.apk"
    with zipfile.ZipFile(apk, "w") as zf:
        zf.writestr("classes.dex", b"CertificateManager serial=fedcba9876543210\n")
        zf.writestr("AndroidManifest.xml", b"mf")

    fake = FakeAdb()

    def shell(command: str, timeout: int = 60) -> CommandResult:
        if command.startswith("pm list packages"):
            return CommandResult(
                True,
                "package:/system/app/VecentekApp/VecentekApp.apk=com.vecentek.decoreapp\n"
                "package:/system/priv-app/Settings/Settings.apk=com.android.settings\n",
                "",
                0,
                [],
            )
        if command.startswith("pm path"):
            raise AssertionError("do not probe missing sideload apps")
        return CommandResult(True, "", "", 0, [])

    def raw(args: list[str], timeout: int = 45, input_text: str | None = None) -> CommandResult:
        if args and args[0] == "pull":
            Path(args[2]).write_bytes(apk.read_bytes())
            return CommandResult(True, "pulled", "", 0, args)
        return CommandResult(True, "", "", 0, args)

    fake.shell = shell  # type: ignore[method-assign]
    fake.raw = raw  # type: ignore[method-assign]
    notes: list[str] = []
    candidates = discover_hu_signer_candidates(fake, lambda m, p: notes.append(m))
    assert 0xFEDCBA9876543210 in candidates
    assert any("vecentek" in line.lower() for line in notes)



