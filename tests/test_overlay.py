from pathlib import Path

from hub.overlay import (
    LEGACY_PACKAGE,
    LEGACY_PACKAGES,
    PACKAGE,
    PERSIST_SHELL,
    disable_user_package,
    grant_overlay,
    remove_overlay,
    start_overlay,
)


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


def test_start_overlay_kicks_service_not_activity() -> None:
    fake = FakeAdb()
    start_overlay(fake)
    joined = "\n".join(fake.shells)
    assert "MainActivity" not in joined
    assert "monkey" not in joined
    assert "LOCKED_BOOT_COMPLETED" not in joined
    assert "POWER_CONNECTED" not in joined
    assert "start-foreground-service" in joined or "startservice" in joined
    assert f"pm enable --user 0 {PACKAGE}" in joined
    assert f"am startservice -n {PACKAGE}/com.changanhub.quickbar.OverlayService" in joined
    assert "BootActivity" in joined
    assert "enabled_accessibility_services" in joined
    assert "accessibility_enabled" in joined
    assert f"pm disable-user --user 0 {LEGACY_PACKAGE}" in joined
    assert f"pm disable-user --user 0 com.changanhub.quickdock" in joined
    assert f"pm disable-user --user 0 com.changanhub.quicklane" in joined
    assert f"pm disable-user --user 0 com.changanhub.quickkeep" in joined
    assert f"appops set {LEGACY_PACKAGE} SYSTEM_ALERT_WINDOW ignore" in joined
    assert "pm uninstall" not in joined
    assert f"pm disable {LEGACY_PACKAGE}" not in joined
    assert PACKAGE == "com.changanhub.quickrise"
    assert "com.changanhub.quickdock" in LEGACY_PACKAGES
    assert "com.changanhub.quicklane" in LEGACY_PACKAGES
    assert "com.changanhub.quickkeep" in LEGACY_PACKAGES


def test_remove_overlay_disables_instead_of_uninstall() -> None:
    fake = FakeAdb()
    lines = remove_overlay(fake)
    joined = "\n".join(fake.shells + lines)
    assert "pm uninstall" not in joined
    assert f"pm disable-user --user 0 {LEGACY_PACKAGE}" in joined
    assert f"pm disable-user --user 0 {PACKAGE}" in joined
    assert f"pm disable {PACKAGE}" not in joined
    assert "force-stop" in joined


def test_disable_user_package_uninstalls_when_allowed() -> None:
    fake = FakeAdb()

    def shell(command: str, timeout: int = 60):
        from hub.adb import CommandResult

        fake.shells.append(command)
        if command.startswith("pm uninstall"):
            return CommandResult(True, "Success", "", 0, [])
        return CommandResult(True, "", "", 0, [])

    fake.shell = shell  # type: ignore[method-assign]
    lines = disable_user_package(fake, "mobi.zona")
    joined = "\n".join(fake.shells + lines)
    assert "pm uninstall --user 0 mobi.zona" in joined
    assert "pm disable-user" not in joined
    assert "снят" in joined


def test_disable_user_package_hides_when_auth_blocks_delete() -> None:
    fake = FakeAdb()

    def shell(command: str, timeout: int = 60):
        from hub.adb import CommandResult

        fake.shells.append(command)
        if command.startswith("pm uninstall"):
            return CommandResult(False, "", "is auth app, not allow delete!", 1, [])
        return CommandResult(True, "", "", 0, [])

    fake.shell = shell  # type: ignore[method-assign]
    lines = disable_user_package(fake, "mobi.zona")
    joined = "\n".join(fake.shells + lines)
    assert "pm uninstall --user 0 mobi.zona" in joined
    assert "pm hide mobi.zona" in joined
    assert "pm disable-user --user 0 mobi.zona" in joined
    assert "auth-приложение" in joined


def test_quickbar_is_three_times_taller() -> None:
    src = Path("android/quickbar/src/main/java/com/changanhub/quickbar/OverlayService.java").read_text(
        encoding="utf-8"
    )
    assert "HEIGHT_SCALE = 3" in src
    assert "TEXT_SCALE = 2" in src
    assert "48 * HEIGHT_SCALE" in src
    assert "VERTICAL_MARGIN = 0.20f" in src
    assert "COLLAPSED_W_DP = 64" in src
    assert "keyboardPeek" in src
    assert "imeHeight()" in src
    assert "buildPeekButton" in src
    assert "dockMenu" in src
    assert "dockRecent" in src
    assert "collapsedRecentY" in src
    assert "ignoreImePeek" in src
    assert "FLAG_NOT_TOUCH_MODAL" in src
    assert "displayHeight()" in src
    assert "overlayHeight()" in src
    assert "scheduleWatchdog" in src
    assert "ACTION_KEEPALIVE" in src
    assert "setExactAndAllowWhileIdle" in src


def test_manifest_survives_acc_cycle() -> None:
    mf = Path("android/quickbar/src/main/AndroidManifest.xml").read_text(encoding="utf-8")
    assert "WatchdogReceiver" in mf
    assert "KeepAliveJob" in mf
    assert 'android:versionName="1.3.8"' in mf
    assert "ACTION_BOOT_IPO" in mf
    assert "stopWithTask" in mf
    assert "REQUEST_IGNORE_BATTERY_OPTIMIZATIONS" in mf
    assert "BOOT_COMPLETED" in mf
    assert "ACTION_POWER_CONNECTED" in mf
    assert "directBootAware" in mf
    assert 'package="com.changanhub.quickrise"' in mf
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
    job = Path("android/quickbar/src/main/java/com/changanhub/quickbar/KeepAliveJob.java").read_text(
        encoding="utf-8"
    )
    main = Path("android/quickbar/src/main/java/com/changanhub/quickbar/MainActivity.java").read_text(
        encoding="utf-8"
    )
    overlay = Path("android/quickbar/src/main/java/com/changanhub/quickbar/OverlayService.java").read_text(
        encoding="utf-8"
    )
    assert "scheduleBootRetries" in boot
    assert "isIgnitionWake" in boot
    assert "startTrampoline" in boot
    assert "BootActivity" in boot
    assert "OverlayService.start(app)" not in boot
    assert "keepAlive" in wd
    assert "OverlayService.keepAlive(this)" in job
    assert "setMinimumLatency" in job
    assert "setOverrideDeadline" in job
    assert "setPeriodic" not in job
    assert "OverlayService.start(this)" not in job
    assert "finish();" in main
    assert "com.changanhub.quickdock" in overlay
    assert "com.changanhub.quicklane" in overlay
    assert "com.changanhub.quickkeep" in overlay
    assert "getInstalledApplications" in overlay
    assert "launchIntentFallback" in overlay
    assert "BOOT_RETRY_SEC = {1, 2, 5, 10, 30, 60, 120}" in overlay
    assert "ACTION_KEEPALIVE" in overlay
    assert "getService" in overlay
    assert "KeepAliveAccessibility" in mf
    assert "com.changanhub.quickbar.BootActivity" in mf
    assert "com.fyt.boot.ACCON" in mf
    assert "RECEIVE_LOCKED_BOOT_COMPLETED" in mf
    assert Path("android/quickbar/src/main/res/xml/keep_alive_accessibility.xml").is_file()
    access = Path(
        "android/quickbar/src/main/java/com/changanhub/quickbar/KeepAliveAccessibility.java"
    ).read_text(encoding="utf-8")
    assert "resumeAfterSleep" in access
    assert "startTrampoline" in access
    assert "ACTION_RESUME" in overlay
    assert "reattachOverlay" in overlay
    assert "lastReattachElapsed < 8_000L" in overlay
    assert "pokeOverlay" in overlay
    assert "getWindowVisibleDisplayFrame" not in overlay
    assert "hiddenExpanded || searching" not in overlay
    assert "pendingHidden" in overlay
    assert "RTC_WAKEUP" in overlay
    actions = Path(
        "android/quickbar/src/main/java/com/changanhub/quickbar/PackageActions.java"
    ).read_text(encoding="utf-8")
    assert "COMPONENT_ENABLED_STATE_DISABLED_USER" in actions
    assert "pm disable-user" in actions


def test_quickbar_groups_and_usb_install() -> None:
    src = Path("android/quickbar/src/main/java/com/changanhub/quickbar/OverlayService.java").read_text(
        encoding="utf-8"
    )
    assert 'sectionHeader("Сторонние")' in src
    assert 'foldHeader("Системные"' in src
    assert 'foldHeader("Скрытые"' in src
    assert 'sectionHeader("Скрытые")' not in src
    assert "R.drawable.ic_delete" not in src
    assert "R.drawable.ic_eye_off" in src
    assert "R.drawable.ic_check" in src
    assert "R.drawable.ic_close" in src
    assert "R.drawable.ic_reorder" in src
    assert "R.drawable.ic_arrow_up" in src
    assert "R.drawable.ic_arrow_down" in src
    assert "KEY_HIDDEN" in src
    assert "KEY_ORDER" in src
    assert "pendingHidePkg" in src
    assert "setHidden" in src
    assert "moveUserApp" in src
    assert "reorderMode" in src
    assert "systemExpanded" in src
    assert "hiddenExpanded" in src
    assert "pendingHidden" in src
    assert "hiddenExpanded || searching" not in src
    assert "TEXT_SCALE = 2" in src
    assert "setTextSize(textSp(" in src
    assert "R.drawable.ic_usb" in src
    assert "R.drawable.logo_itm" not in src
    assert "expandToIcons" not in src
    assert "R.drawable.ic_grid" not in src
    assert "expandToFull" in src
    assert "recentZone" in src
    assert "evenSpacer" in src
    assert "COLLAPSED_W_DP = 64" in src
    assert "COLLAPSED_ICON_DP" in src
    assert "collapsedZones" not in src
    assert "buildPeekButton" in src
    assert "keyboardPeek" in src
    assert "collapsedMenuY" in src
    assert "collapsedRecentY" in src
    assert 'tools.addView(toolIcon(R.drawable.ic_menu' not in src
    assert "LEGACY_PACKAGE" in src
    assert "KEY_RECENT" in src
    assert "UsbStorage.apkFiles" in src
    assert "PackageActions.copyToCache" in src
    assert "uninstallUserApp" not in src
    assert "PackageActions.uninstall" not in src
    assert "PackageActions.install" in src
    assert (Path("android/quickbar/src/main/java/com/changanhub/quickbar/KeepAliveJob.java")).is_file()
    job = Path("android/quickbar/src/main/java/com/changanhub/quickbar/KeepAliveJob.java").read_text(
        encoding="utf-8"
    )
    assert "setPersisted(true)" in job
    assert "LATENCY_MS = 3_000L" in job
    assert "DEADLINE_MS = 12_000L" in job
    assert "setMinimumLatency" in job
    assert Path("android/quickbar/src/main/java/com/changanhub/quickbar/UsbStorage.java").is_file()
    assert Path("android/quickbar/src/main/java/com/changanhub/quickbar/PackageActions.java").is_file()
    assert (Path("android/quickbar/src/main/java/com/changanhub/quickbar/UsbStorage.java")).is_file()
    assert (Path("android/quickbar/src/main/java/com/changanhub/quickbar/PackageActions.java")).is_file()


def test_quickbar_icons_exist() -> None:
    res = Path("android/quickbar/src/main/res/drawable")
    for name in (
        "ic_logo.xml",
        "ic_menu.xml",
        "ic_usb.xml",
        "ic_eye_off.xml",
        "ic_check.xml",
        "ic_close.xml",
        "ic_reorder.xml",
        "ic_arrow_up.xml",
        "ic_arrow_down.xml",
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


# Keep in sync with OverlayService VERTICAL_MARGIN / collapsedRecentY / overlayTop.
_MARGIN = 0.20


def _collapsed_layout(screen: int, menu_h: int, recent_h: int) -> tuple[int, int, int, int]:
    gap = round(screen * _MARGIN)
    menu_y = gap
    recent_y = max(screen - gap - recent_h, menu_y + menu_h + gap)
    between = recent_y - (menu_y + menu_h)
    peek_y = gap
    return menu_y, recent_y, between, peek_y


def test_collapsed_gap_leaves_yandex_passthrough() -> None:
    src = Path("android/quickbar/src/main/java/com/changanhub/quickbar/OverlayService.java").read_text(
        encoding="utf-8"
    )
    assert "no WindowManager view" in src
    assert "getInputMethodWindowVisibleHeight" in src
    for screen, menu_h, recent_h in (
        (1920, 112, 280),
        (1920, 168, 400),
        (1600, 100, 240),
        (1280, 84, 200),
    ):
        menu_y, recent_y, between, peek_y = _collapsed_layout(screen, menu_h, recent_h)
        gap = round(screen * _MARGIN)
        assert menu_y == gap
        assert peek_y == gap
        assert between >= gap - 1
        if menu_h + recent_h + 3 * gap <= screen:
            assert recent_y + recent_h == screen - gap
            assert menu_y + menu_h + between + recent_h + gap == screen


def test_accessibility_dedupes_and_skips_huge_lists() -> None:
    from hub.overlay import ACCESS_COMPONENT, accessibility_services_value, enable_accessibility

    assert accessibility_services_value("", ACCESS_COMPONENT) == ACCESS_COMPONENT
    assert accessibility_services_value("null", ACCESS_COMPONENT) == ACCESS_COMPONENT
    dup = ":".join(["com.incall/.A", "com.iflytek/.B"] * 40)
    value = accessibility_services_value(dup, ACCESS_COMPONENT)
    assert value is not None
    assert value.count("com.incall/.A") == 1
    assert ACCESS_COMPONENT in value.split(":")
    assert len(f"settings put secure enabled_accessibility_services {value}") < 500
    huge = ":".join(f"com.pkg{i}/.Svc" for i in range(400))
    assert accessibility_services_value(huge, ACCESS_COMPONENT) == ACCESS_COMPONENT

    fake = FakeAdb()

    def shell(command: str, timeout: int = 60):
        from hub.adb import CommandResult

        fake.shells.append(command)
        if command.startswith("settings get"):
            return CommandResult(True, dup, "", 0, [])
        return CommandResult(True, "", "", 0, [])

    fake.shell = shell  # type: ignore[method-assign]
    enable_accessibility(fake)
    puts = [c for c in fake.shells if c.startswith("settings put secure enabled_accessibility_services")]
    assert len(puts) == 1
    assert len(puts[0]) < 500
    assert "accessibility_enabled 1" in "\n".join(fake.shells)

    huge_fake = FakeAdb()

    def huge_shell(command: str, timeout: int = 60):
        from hub.adb import CommandResult

        huge_fake.shells.append(command)
        if command.startswith("settings get"):
            return CommandResult(True, huge, "", 0, [])
        return CommandResult(True, "", "", 0, [])

    huge_fake.shell = huge_shell  # type: ignore[method-assign]
    lines = enable_accessibility(huge_fake)
    huge_puts = [
        c for c in huge_fake.shells if c.startswith("settings put secure enabled_accessibility_services")
    ]
    assert len(huge_puts) == 1
    assert huge_puts[0].endswith(ACCESS_COMPONENT)
    assert len(huge_puts[0]) < 500
    assert any("только компонент" in line for line in lines)


def test_launch_overlay_target_uses_working_package() -> None:
    from hub.overlay import PACKAGE, launch_overlay_target

    assert launch_overlay_target(PACKAGE) == PACKAGE
    assert launch_overlay_target("com.changanhub.quickkeep") == PACKAGE
    assert launch_overlay_target("com.changanhub.quicklane") == PACKAGE
    assert launch_overlay_target("mobi.zona") is None


def test_disable_overlay_never_uninstalls() -> None:
    fake = FakeAdb()
    lines = disable_user_package(fake, PACKAGE)
    joined = "\n".join(fake.shells)
    assert not any(cmd.startswith("pm uninstall") for cmd in fake.shells)
    assert f"pm disable-user --user 0 {PACKAGE}" in joined
    assert "auth-панель" in "\n".join(lines)


def test_adb_raw_swallows_filename_too_long(monkeypatch) -> None:
    import subprocess

    from hub.adb import Adb

    def boom(*_a, **_k):
        exc = OSError("The filename or extension is too long")
        exc.winerror = 206
        raise exc

    monkeypatch.setattr(subprocess, "run", boom)
    adb = object.__new__(Adb)
    adb.binary = Path("adb")
    adb.serial = None
    adb.on_log = None
    result = Adb.raw(adb, ["shell", "settings put secure enabled_accessibility_services x"])
    assert not result.ok
    assert result.code == 206
    assert "too long" in result.stderr.lower() or "OSError" in result.stderr
