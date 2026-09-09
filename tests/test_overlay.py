from pathlib import Path

from hub.overlay import PERSIST_SHELL, PACKAGE, grant_overlay, start_overlay


class FakeAdb:
    def __init__(self) -> None:
        self.shells: list[str] = []

    def shell(self, command: str, timeout: int = 60):
        from hub.adb import CommandResult

        self.shells.append(command)
        return CommandResult(True, "", "", 0, [])


def test_grant_overlay_keeps_process_alive() -> None:
    fake = FakeAdb()
    grant_overlay(fake)
    joined = "\n".join(fake.shells)
    assert PACKAGE in joined
    assert "SYSTEM_ALERT_WINDOW" in joined
    assert "deviceidle whitelist" in joined
    assert "RUN_IN_BACKGROUND" in joined
    assert "RUN_ANY_IN_BACKGROUND" in joined
    assert f"am set-inactive {PACKAGE} false" in joined
    assert any("deviceidle whitelist +" in cmd for cmd in PERSIST_SHELL)


def test_start_overlay_kicks_boot_intents() -> None:
    fake = FakeAdb()
    start_overlay(fake)
    joined = "\n".join(fake.shells)
    assert "BOOT_COMPLETED" in joined
    assert "USER_PRESENT" in joined
    assert "MainActivity" in joined
    assert "start-foreground-service" in joined or "startservice" in joined


def test_quickbar_is_three_times_taller() -> None:
    src = Path("android/quickbar/src/main/java/com/changanhub/quickbar/OverlayService.java").read_text(
        encoding="utf-8"
    )
    assert "HEIGHT_SCALE = 3" in src
    assert "48 * HEIGHT_SCALE" in src
    assert "220 * HEIGHT_SCALE" in src
    assert "displayHeight()" in src
    assert "scheduleWatchdog" in src
    assert "ACTION_KEEPALIVE" in src


def test_manifest_survives_acc_cycle() -> None:
    mf = Path("android/quickbar/src/main/AndroidManifest.xml").read_text(encoding="utf-8")
    assert "WatchdogReceiver" in mf
    assert "REQUEST_IGNORE_BATTERY_OPTIMIZATIONS" in mf
    assert "BOOT_COMPLETED" in mf
    assert "ACTION_POWER_CONNECTED" in mf
    assert "directBootAware" in mf
    assert "REQUEST_INSTALL_PACKAGES" in mf
    assert "InstallResultReceiver" in mf
    boot = Path("android/quickbar/src/main/java/com/changanhub/quickbar/BootReceiver.java").read_text(
        encoding="utf-8"
    )
    wd = Path("android/quickbar/src/main/java/com/changanhub/quickbar/WatchdogReceiver.java").read_text(
        encoding="utf-8"
    )
    assert "scheduleBootRetries" in boot
    assert "keepAlive" in wd


def test_quickbar_groups_and_usb_install() -> None:
    src = Path("android/quickbar/src/main/java/com/changanhub/quickbar/OverlayService.java").read_text(
        encoding="utf-8"
    )
    assert 'sectionHeader("Сторонние")' in src
    assert 'sectionHeader("Системные")' in src
    assert "R.drawable.ic_delete" in src
    assert "R.drawable.ic_usb" in src
    assert "R.drawable.logo_itm" in src
    assert "expandToIcons" in src
    assert "expandToFull" in src
    assert "collapsedZones" in src
    assert "UsbStorage.apkFiles" in src
    assert "PackageActions.uninstall" in src
    assert "PackageActions.install" in src
    assert (Path("android/quickbar/src/main/java/com/changanhub/quickbar/UsbStorage.java")).is_file()
    assert (Path("android/quickbar/src/main/java/com/changanhub/quickbar/PackageActions.java")).is_file()


def test_itm_logo_and_icons_exist() -> None:
    res = Path("android/quickbar/src/main/res/drawable")
    for name in (
        "logo_itm.xml",
        "ic_grid.xml",
        "ic_menu.xml",
        "ic_usb.xml",
        "ic_delete.xml",
        "ic_collapse.xml",
        "ic_refresh.xml",
        "ic_install.xml",
    ):
        assert (res / name).is_file(), name
    logo = (res / "logo_itm.xml").read_text(encoding="utf-8")
    assert "IT•m" in logo or "3DDC97" in logo
    joined = "\n".join(PERSIST_SHELL)
    assert "REQUEST_INSTALL_PACKAGES" in joined
    assert "install_non_market_apps" in joined
