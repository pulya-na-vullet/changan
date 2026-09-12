import json
import zipfile
from pathlib import Path
from unittest.mock import patch

from hub.adb import CommandResult
from hub.bundle import (
    bundle_package_name,
    extract_bundle,
    is_apk_bundle,
    parse_install_session,
)
from hub.installer import apk_package_name, install_apk


class FakeAdb:
    def __init__(self) -> None:
        self.connected_flag = True
        self.pushed: list[str] = []
        self.shells: list[str] = []
        self.binary = Path("adb")

    def connected(self) -> bool:
        return True

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


def _mini_apk(path: Path, package: str = "ru.kinopoisk") -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("AndroidManifest.xml", package.encode("utf-16-le"))
        zf.writestr("classes.dex", b"dex")


def _xapk(path: Path, *, splits: int = 2, obb: bool = False) -> None:
    base = path.parent / "_base.apk"
    cfg = path.parent / "_cfg.apk"
    _mini_apk(base, "ru.kinopoisk")
    _mini_apk(cfg, "ru.kinopoisk")
    manifest = {
        "package_name": "ru.kinopoisk",
        "split_apks": [{"file": "ru.kinopoisk.apk", "id": "base"}],
    }
    if splits > 1:
        manifest["split_apks"].append({"file": "config.arm64_v8a.apk", "id": "config.arm64_v8a"})
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.write(base, "ru.kinopoisk.apk")
        if splits > 1:
            zf.write(cfg, "config.arm64_v8a.apk")
        if obb:
            zf.writestr("Android/obb/ru.kinopoisk/main.1.ru.kinopoisk.obb", b"obb-bytes")
    base.unlink(missing_ok=True)
    cfg.unlink(missing_ok=True)


def test_is_apk_bundle_detects_xapk_and_nested_apk(tmp_path: Path) -> None:
    xapk = tmp_path / "app.xapk"
    _xapk(xapk)
    assert is_apk_bundle(xapk)
    assert bundle_package_name(xapk) == "ru.kinopoisk"
    assert apk_package_name(xapk) == "ru.kinopoisk"

    nested = tmp_path / "Кинопоиск_2.266.0_APKPure-changan.apk"
    _xapk(nested)
    assert is_apk_bundle(nested)

    real = tmp_path / "real.apk"
    _mini_apk(real)
    assert not is_apk_bundle(real)


def test_extract_bundle_reads_splits_and_obb(tmp_path: Path) -> None:
    xapk = tmp_path / "app.xapk"
    _xapk(xapk, obb=True)
    extracted = extract_bundle(xapk, tmp_path / "out")
    assert extracted.package == "ru.kinopoisk"
    names = {item.name for item in extracted.splits}
    assert "base" in names
    assert "config.arm64_v8a" in names
    assert len(extracted.obb) == 1
    assert extracted.obb[0].name.endswith(".obb")


def test_parse_install_session() -> None:
    assert parse_install_session("Success: created install session [42]") == "42"
    assert parse_install_session("created session 99\n") == "99"
    assert parse_install_session("nope") is None


def test_install_single_apk_xapk_uses_pm_install(tmp_path: Path) -> None:
    xapk = tmp_path / "one.xapk"
    _xapk(xapk, splits=1)
    fake = FakeAdb()

    def sign(src, **_kwargs):
        return src, "python-v1v2"

    with (
        patch("hub.paths.app_data", return_value=tmp_path),
        patch("hub.installer.load_cached_hu_serial", return_value=0xD42599C0446BDAFC),
        patch("hub.installer.sign_apk_with_method", side_effect=sign),
        patch("hub.installer.ensure_keystore"),
        patch("hub.installer.apk_certificate_serials", return_value=[0xD42599C0446BDAFC]),
        patch("hub.installer.save_cached_hu_serial"),
    ):
        report = install_apk(fake, xapk)
    assert report.ok
    assert any(cmd.startswith("pm install -r -t -g ") for cmd in fake.shells)
    assert not any("install-create" in cmd for cmd in fake.shells)
    assert any("xapk" in line.lower() or "внутренн" in line.lower() for line in report.log)


def test_install_xapk_uses_session(tmp_path: Path) -> None:
    xapk = tmp_path / "app.xapk"
    _xapk(xapk, splits=2, obb=True)
    fake = FakeAdb()

    def shell(command: str, timeout: int = 60) -> CommandResult:
        fake.shells.append(command)
        if command.startswith("pm install-create"):
            return CommandResult(True, "Success: created install session [7]", "", 0, [])
        if command.startswith("pm install-write"):
            return CommandResult(True, "Success", "", 0, [])
        if command.startswith("pm install-commit"):
            return CommandResult(True, "Success", "", 0, [])
        if command.startswith("pm install "):
            raise AssertionError("split xapk must not use single pm install")
        if command.startswith("pm path"):
            return CommandResult(True, "package:/data/app/ru.kinopoisk/base.apk", "", 0, [])
        return CommandResult(True, "", "", 0, [])

    fake.shell = shell  # type: ignore[method-assign]

    def sign(src, **_kwargs):
        return src, "python-v1v2"

    with (
        patch("hub.paths.app_data", return_value=tmp_path),
        patch("hub.installer.load_cached_hu_serial", return_value=0xD42599C0446BDAFC),
        patch("hub.installer.sign_apk_with_method", side_effect=sign),
        patch("hub.installer.ensure_keystore"),
        patch("hub.installer.apk_certificate_serials", return_value=[0xD42599C0446BDAFC]),
        patch("hub.installer.save_cached_hu_serial"),
        patch("hub.installer.time.sleep"),
    ):
        report = install_apk(fake, xapk)
    assert report.ok
    assert any(cmd.startswith("pm install-create") for cmd in fake.shells)
    assert any(cmd.startswith("pm install-write") for cmd in fake.shells)
    assert any(cmd.startswith("pm install-commit") for cmd in fake.shells)
    assert any("obb" in cmd.lower() or "Android/obb" in cmd for cmd in fake.shells)
    assert len(fake.pushed) >= 2
    assert any(remote.startswith("/data/local/tmp/hub-7-") for remote in fake.pushed)


def test_usb_lists_xapk(tmp_path: Path, monkeypatch) -> None:
    from hub.usb import list_usb_apks

    xapk = tmp_path / "Кинопоиск.xapk"
    xapk.write_bytes(b"PK\x03\x04" + b"\x00" * 40)
    monkeypatch.setattr("hub.usb.removable_roots", lambda: [tmp_path])
    found = {item.name for item in list_usb_apks()}
    assert "Кинопоиск.xapk" in found
