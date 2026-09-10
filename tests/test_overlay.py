from pathlib import Path

from hub.overlay import LEGACY_PACKAGE, PACKAGE, PERSIST_SHELL, grant_overlay, remove_overlay, start_overlay


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
    assert f"pm disable-user --user 0 {LEGACY_PACKAGE}" in joined
    assert f"appops set {LEGACY_PACKAGE} SYSTEM_ALERT_WINDOW ignore" in joined
    assert "pm uninstall" not in joined
    assert f"{PACKAGE}/com.changanhub.quickbar.MainActivity" in joined
    assert PACKAGE == "com.changanhub.quickdock"


def test_remove_overlay_disables_instead_of_uninstall() -> None:
    fake = FakeAdb()
    lines = remove_overlay(fake)
    joined = "\n".join(fake.shells + lines)
    assert "pm uninstall" not in joined
    assert f"pm disable-user --user 0 {LEGACY_PACKAGE}" in joined
    assert "force-stop" in joined


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
    assert 'package="com.changanhub.quickdock"' in mf
    assert "android:persistent" not in mf
    assert "KILL_BACKGROUND_PROCESSES" in mf
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
    assert "R.drawable.logo_itm" not in src
    assert "expandToIcons" not in src
    assert "R.drawable.ic_grid" not in src
    assert "expandToFull" in src
    assert "collapsedZones" in src
    assert "recentZone" in src
    assert "evenSpacer" in src
    assert "COLLAPSED_W_DP = 144" in src
    assert "LEGACY_PACKAGE" in src
    assert "KEY_RECENT" in src
    assert "UsbStorage.apkFiles" in src
    assert "PackageActions.uninstall" in src
    assert "PackageActions.install" in src
    assert (Path("android/quickbar/src/main/java/com/changanhub/quickbar/UsbStorage.java")).is_file()
    assert (Path("android/quickbar/src/main/java/com/changanhub/quickbar/PackageActions.java")).is_file()


def test_quickbar_icons_exist() -> None:
    res = Path("android/quickbar/src/main/res/drawable")
    for name in (
        "ic_logo.xml",
        "ic_menu.xml",
        "ic_usb.xml",
        "ic_delete.xml",
        "ic_collapse.xml",
        "ic_refresh.xml",
        "ic_install.xml",
    ):
        assert (res / name).is_file(), name
    assert not (res / "logo_itm.xml").exists()
    assert not (res / "ic_grid.xml").exists()
    app_name = Path("android/quickbar/src/main/res/values/strings.xml").read_text(encoding="utf-8")
    assert ">QuickBar<" in app_name
    assert "IT-m" not in app_name
    joined = "\n".join(PERSIST_SHELL)
    assert "REQUEST_INSTALL_PACKAGES" in joined
    assert "GET_USAGE_STATS" in joined
