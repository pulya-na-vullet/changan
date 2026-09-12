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

    save_cached_hu_serial(0xA1B2C3D4E5F60718, "AHFPF_OWNER")
    save_cached_hu_serial(0xB2C3D4E5F607189A, "AHFPF_RUS")
    (tmp_path / "certs" / "hu_serial.txt").write_text("0xddb66eefd98476f3", encoding="utf-8")
    assert load_cached_hu_serial("AHFPF_OWNER") == 0xA1B2C3D4E5F60718
    assert load_cached_hu_serial("AHFPF_RUS") == 0xB2C3D4E5F607189A
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
    from hub.installer import extract_embedded_serials, extract_hex_serials
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
    assert 0xAABBCCDDEEFF11 in extract_hex_serials(blob)
    ascii_window = extract_embedded_serials(b"xx is not auth,install failed! yy")
    assert 0x20746F6E20736920 not in ascii_window
    assert 0x123456789ABCDEF not in extract_embedded_serials(b"0123456789abcdef placeholder")
    noise = bytes([0x18, 0x00]) + (0xA1B2C3D4E5F60718).to_bytes(8, "little")
    assert 0xA1B2C3D4E5F60718 not in extract_embedded_serials(noise)


def test_plausible_serial_works_without_bit_count() -> None:
    from hub.installer import _plausible_opcode_serial, _plausible_serial
    from hub.signer import CHANGAN_SERIAL

    assert _plausible_serial(CHANGAN_SERIAL)
    assert _plausible_serial(0xA1B2C3D4E5F60718)
    assert not _plausible_serial(0x123456789ABCDEF)
    assert not _plausible_serial(0x20746F6E20736920)
    assert not _plausible_serial(0x332D1B7402760001)
    assert _plausible_opcode_serial(CHANGAN_SERIAL)
    assert not _plausible_opcode_serial(0x332D1B7402760001)
    assert not _plausible_opcode_serial(0xA190001566F0A19)
    assert not _plausible_opcode_serial(0x1676107003820122)


def _fake_dex(*chunks: bytes) -> bytes:
    payload = b"".join(chunks)
    header = bytearray(64)
    header[0:8] = b"dex\n035\x00"
    total = 64 + len(payload)
    header[32:36] = total.to_bytes(4, "little")
    return bytes(header) + payload


def test_dex_const_wide_and_array_data_serials() -> None:
    from hub.installer import dex_array_data_longs, dex_const_wide_literals, extract_embedded_serials

    serial = 0xA1B2C3D4E5F60718
    insn = bytes([0x18, 0x00]) + serial.to_bytes(8, "little")
    blob = _fake_dex(insn)  # obfuscated Vecentek has no "not auth" string
    assert serial in dex_const_wide_literals(blob)
    assert serial in extract_embedded_serials(blob)

    other = 0xB2C3D4E5F607189A
    array = (0x0300).to_bytes(2, "little") + (8).to_bytes(2, "little") + (1).to_bytes(4, "little")
    array += other.to_bytes(8, "little")
    dex = _fake_dex(array)
    assert other in dex_array_data_longs(dex)
    assert other in extract_embedded_serials(dex)

    cdex_header = bytearray(64)
    cdex_header[0:8] = b"cdex001\x00"
    cdex_payload = bytes([0x18, 0x00]) + serial.to_bytes(8, "little")
    cdex_header[32:36] = (64 + len(cdex_payload)).to_bytes(4, "little")
    cdex = bytes(cdex_header) + cdex_payload
    assert serial in dex_const_wide_literals(cdex)


def test_embedded_serials_in_apk(tmp_path: Path) -> None:
    from hub.installer import embedded_serials_in_apk

    apk = tmp_path / "vecentek.apk"
    with zipfile.ZipFile(apk, "w") as zf:
        zf.writestr("classes.dex", b"xx not auth deadbeefcafebabe yy")
        zf.writestr("AndroidManifest.xml", b"mf")
    found = embedded_serials_in_apk(apk)
    assert 0xDEADBEEFCAFEBABE in found


def test_cached_junk_serial_is_ignored(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("hub.paths.app_data", lambda: tmp_path)
    from hub.installer import load_cached_hu_serial, save_cached_hu_serial

    save_cached_hu_serial(0x123456789ABCDEF, "AHFPF_RUS")
    assert load_cached_hu_serial("AHFPF_RUS") is None
    save_cached_hu_serial(0x332D1B7402760001, "AHFPF_RUS")
    assert load_cached_hu_serial("AHFPF_RUS") is None
    save_cached_hu_serial(0xA1B2C3D4E5F60718, "AHFPF_RUS")
    assert load_cached_hu_serial("AHFPF_RUS") == 0xA1B2C3D4E5F60718


def test_discover_uses_vecentek_when_no_sideload(tmp_path: Path) -> None:
    from hub.installer import discover_hu_signer_candidates
    from hub.signer import CHANGAN_SERIAL

    apk = tmp_path / "VecentekApp.apk"
    with zipfile.ZipFile(apk, "w") as zf:
        zf.writestr("classes.dex", b"CertificateManager serial=a1b2c3d4e5f60718\n")
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
    assert 0xA1B2C3D4E5F60718 in candidates
    assert CHANGAN_SERIAL in candidates
    assert 0xFEDCBA9876543210 not in candidates
    assert any("vecentek" in line.lower() for line in notes)
    assert candidates[0] == 0xA1B2C3D4E5F60718
    assert candidates[-1] == CHANGAN_SERIAL


def test_discover_boot_ext_const_wide_skips_services_junk(tmp_path: Path) -> None:
    from hub.installer import discover_hu_signer_candidates
    from hub.signer import CHANGAN_SERIAL

    serial = 0xA1B2C3D4E5F60718
    services_noise = 0xB2C3D4E5F607189A
    vecentek = tmp_path / "VecentekApp.apk"
    with zipfile.ZipFile(vecentek, "w") as zf:
        zf.writestr("classes.dex", _fake_dex())
        zf.writestr("AndroidManifest.xml", b"mf")
    boot_ext = _fake_dex(bytes([0x18, 0x00]) + serial.to_bytes(8, "little"))
    services = _fake_dex(bytes([0x18, 0x00]) + services_noise.to_bytes(8, "little"))

    fake = FakeAdb()

    def shell(command: str, timeout: int = 60) -> CommandResult:
        if command.startswith("pm list packages"):
            return CommandResult(
                True,
                "package:/system/app/VecentekApp/VecentekApp.apk=com.vecentek.decoreapp\n",
                "",
                0,
                [],
            )
        if command.startswith("pm path"):
            raise AssertionError("do not probe missing sideload apps")
        return CommandResult(True, "", "", 0, [])

    def raw(args: list[str], timeout: int = 45, input_text: str | None = None) -> CommandResult:
        if args and args[0] == "pull":
            remote, dest = args[1], Path(args[2])
            if remote.endswith("VecentekApp.apk"):
                dest.write_bytes(vecentek.read_bytes())
            elif remote.endswith("boot-ext.vdex"):
                dest.write_bytes(boot_ext)
            elif remote.endswith("services.jar"):
                dest.write_bytes(services)
            else:
                dest.write_bytes(b"x" * 128)
            return CommandResult(True, "pulled", "", 0, args)
        return CommandResult(True, "", "", 0, args)

    fake.shell = shell  # type: ignore[method-assign]
    fake.raw = raw  # type: ignore[method-assign]
    notes: list[str] = []
    with patch("hub.paths.app_data", return_value=tmp_path):
        candidates = discover_hu_signer_candidates(fake, lambda m, p: notes.append(m))
    assert candidates[0] == serial
    assert services_noise not in candidates
    assert CHANGAN_SERIAL == candidates[-1]
    assert any("const-wide" in line and "0xa1b2c3d4e5f60718" in line.lower() for line in notes)


def test_manager_scan_continues_if_one_file_raises(tmp_path: Path) -> None:
    from hub.installer import _serials_from_manager

    fake = FakeAdb()

    def shell(command: str, timeout: int = 60) -> CommandResult:
        if command.startswith("pm list packages"):
            return CommandResult(
                True,
                "package:/system/app/VecentekApp/VecentekApp.apk=com.vecentek.decoreapp\n",
                "",
                0,
                [],
            )
        return CommandResult(True, "", "", 0, [])

    def raw(args: list[str], timeout: int = 45, input_text: str | None = None) -> CommandResult:
        if args and args[0] == "pull":
            Path(args[2]).write_bytes(b"x" * 128)
            return CommandResult(True, "pulled", "", 0, args)
        return CommandResult(True, "", "", 0, args)

    fake.shell = shell  # type: ignore[method-assign]
    fake.raw = raw  # type: ignore[method-assign]
    notes: list[str] = []
    with (
        patch("hub.paths.app_data", return_value=tmp_path),
        patch("hub.installer.embedded_serial_groups", side_effect=AttributeError("bit_count")),
    ):
        high, low = _serials_from_manager(fake, {"com.vecentek.decoreapp": "/system/app/VecentekApp/VecentekApp.apk"}, lambda m, p: notes.append(m))
    assert high == []
    assert low == []
    assert any("не разобрал" in line for line in notes)


def test_whitelist_extra_paths_keep_boot_ext_skip_am() -> None:
    from hub.installer import MANAGER_PATHS, _whitelist_extra_paths

    fake = FakeAdb()

    def shell(command: str, timeout: int = 60) -> CommandResult:
        fake.shells.append(command)
        if command == "ls /system/framework/arm64":
            return CommandResult(
                True,
                "boot-ext.vdex\nboot-ext.oat\nboot.vdex\nboot-framework.vdex\n",
                "",
                0,
                [],
            )
        if command == "ls /system/framework/oat/arm64":
            return CommandResult(
                True,
                "am.odex\nam.vdex\nservices.odex\nservices.vdex\nbmgr.vdex\n",
                "",
                0,
                [],
            )
        if command == "ls /system/etc":
            return CommandResult(True, "wutong-cert.xml\nhosts\n", "", 0, [])
        return CommandResult(True, "", "", 0, [])

    fake.shell = shell  # type: ignore[method-assign]
    paths = _whitelist_extra_paths(fake)
    joined = " ".join(paths)
    assert any(item.endswith("boot-ext.vdex") for item in MANAGER_PATHS)
    from hub.installer import WHITELIST_FILE_PATHS

    assert any(item.endswith("whitelist.json") for item in WHITELIST_FILE_PATHS)
    assert any(item.endswith("publicKey.cert") for item in WHITELIST_FILE_PATHS)
    assert "am.odex" not in joined
    assert "am.vdex" not in joined
    assert "bmgr.vdex" not in joined
    assert "services.vdex" not in joined
    assert "boot.vdex" not in joined
    assert "boot-framework.vdex" not in joined


def test_whitelist_json_and_cert_serials(tmp_path: Path) -> None:
    import datetime as dt

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    from hub.installer import cert_file_serials, serials_from_whitelist_json

    data = b'{"serial":"a1b2c3d4e5f60718","items":[42]}'
    found = serials_from_whitelist_json(data)
    assert 0xA1B2C3D4E5F60718 in found

    now = dt.datetime.now(dt.timezone.utc)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "HU")]))
        .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "HU")]))
        .public_key(key.public_key())
        .serial_number(0xB2C3D4E5F607189A)
        .not_valid_before(now)
        .not_valid_after(now + dt.timedelta(days=2))
        .sign(key, hashes.SHA256())
    )
    pem = tmp_path / "publicKey.cert"
    pem.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    assert 0xB2C3D4E5F607189A in cert_file_serials(pem)


def test_discover_prefers_vecentek_signing_serial(tmp_path: Path) -> None:
    from hub.installer import discover_hu_signer_candidates
    from hub.signer import CHANGAN_SERIAL

    apk = tmp_path / "VecentekApp.apk"
    with zipfile.ZipFile(apk, "w") as zf:
        zf.writestr("classes.dex", b"dex")
        zf.writestr("AndroidManifest.xml", b"mf")

    fake = FakeAdb()
    signed = 0xC0FFEE123456789A

    def shell(command: str, timeout: int = 60) -> CommandResult:
        if command.startswith("pm list packages"):
            return CommandResult(
                True,
                "package:/system/app/VecentekApp/VecentekApp.apk=com.vecentek.decoreapp\n",
                "",
                0,
                [],
            )
        return CommandResult(True, "", "", 0, [])

    def raw(args: list[str], timeout: int = 45, input_text: str | None = None) -> CommandResult:
        if args and args[0] == "pull":
            Path(args[2]).write_bytes(apk.read_bytes())
            return CommandResult(True, "pulled", "", 0, args)
        return CommandResult(True, "", "", 0, args)

    fake.shell = shell  # type: ignore[method-assign]
    fake.raw = raw  # type: ignore[method-assign]
    notes: list[str] = []
    with (
        patch("hub.paths.app_data", return_value=tmp_path),
        patch("hub.installer.apk_certificate_serials", return_value=[signed]),
    ):
        candidates = discover_hu_signer_candidates(fake, lambda m, p: notes.append(m))
    assert candidates[0] == signed
    assert CHANGAN_SERIAL == candidates[-1]
    assert any("подпись" in line for line in notes)


def test_probe_paths_keep_unique_local_names() -> None:
    from hub.installer import _probe_local

    folder = Path("/tmp/probe")
    first = _probe_local(folder, "/system/framework/arm64/boot-ext.vdex")
    second = _probe_local(folder, "/system/framework/boot-ext.vdex")
    assert first != second


def test_install_tries_remaining_serials_without_rediscover(tmp_path: Path) -> None:
    from hub.signer import CHANGAN_SERIAL

    apk = tmp_path / "QuickBar.apk"
    with zipfile.ZipFile(apk, "w") as zf:
        zf.writestr("AndroidManifest.xml", b"mf")
        zf.writestr("classes.dex", b"dex")

    fake = FakeAdb()
    fake.serial = "AHFPF6643S69270176"
    installs = {"n": 0}
    discovers = {"n": 0}
    first = 0xA1B2C3D4E5F60718
    second = 0xB2C3D4E5F607189A

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

    def discover(_adb, _step=None):
        discovers["n"] += 1
        return [first, second]

    fake.shell = shell  # type: ignore[method-assign]
    with (
        patch("hub.paths.app_data", return_value=tmp_path),
        patch("hub.installer.load_cached_hu_serial", return_value=None),
        patch("hub.installer.discover_hu_signer_candidates", side_effect=discover),
        patch("hub.installer.sign_apk_with_method", return_value=(apk, "python-v1v2")),
        patch("hub.installer.ensure_keystore") as ek,
        patch("hub.installer.apk_certificate_serials", return_value=[CHANGAN_SERIAL]),
        patch("hub.installer.save_cached_hu_serial"),
    ):
        report = install_apk(fake, apk, already_signed=False, package="com.changanhub.quickrise")
    assert report.ok
    assert installs["n"] == 2
    assert discovers["n"] == 1
    serials = [call.kwargs.get("serial") for call in ek.call_args_list]
    assert serials == [first, second]
    assert any("следующие serial" in line.lower() or "повторная" in line.lower() for line in report.log)



