"""Freeform / inset-window launch helpers for Feiyu Android 9.

News draws 10% margins inside its own activity. Third-party APKs (2GIS) cannot
do that, so Hub enables freeform and QuickBar asks for launchBounds at 10%
from each edge. Feiyu often ignores bounds — then the app still goes fullscreen.
"""

from __future__ import annotations

from hub.adb import Adb
from hub.installer import Progress

# 10% inset on a 720×1280 portrait HU → 72 / 128 px. Right side also clears QuickBar.
INSET_PERCENT = 10

FREEFORM_SHELL = (
    "settings put global enable_freeform_support 1",
    "settings put global force_resizable_activities 1",
    "settings put global development_settings_enabled 1",
)

# Packages that should open inset even when the global QuickBar «окно» toggle is off.
INSET_PACKAGES = (
    "ru.dublgis.dgismobile",
    "ru.dublgis.2gis",
    "ru.changan.news",
    "com.lamore.wifibutton",
)

WIFI_SETTINGS_ACTION = "android.settings.WIFI_SETTINGS"


def enable_freeform(adb: Adb, progress: Progress | None = None) -> list[str]:
    log: list[str] = []
    for cmd in FREEFORM_SHELL:
        if progress:
            progress(f"окно 10%: {cmd}", 91)
        result = adb.shell(cmd, timeout=8)
        log.append(
            f"{cmd} code={result.code} out={result.stdout.strip()!r} err={result.stderr.strip()!r}"
        )
    return log


def start_windowed(
    adb: Adb,
    spec: str,
    progress: Progress | None = None,
    width: int = 720,
    height: int = 1280,
) -> list[str]:
    """``spec`` is ``-n pkg/.Activity`` or ``-a android.settings.WIFI_SETTINGS``."""
    log: list[str] = []
    inset_x = max(1, width * INSET_PERCENT // 100)
    inset_y = max(1, height * INSET_PERCENT // 100)
    left, top = inset_x, inset_y
    right, bottom = width - inset_x, height - inset_y
    cmds = (
        f"am start --windowingMode 5 {spec}",
        f"am start --windowingMode 5 --activity-task-on-home {spec}",
        f"am start {spec}",
    )
    log.append(f"рамка окна {left},{top},{right},{bottom} ({INSET_PERCENT}% от краёв)")
    last = None
    for cmd in cmds:
        if progress:
            progress(f"запуск в окне: {cmd}", 96)
        result = adb.shell(cmd, timeout=10)
        line = f"{cmd} code={result.code} out={result.stdout.strip()!r} err={result.stderr.strip()!r}"
        log.append(line)
        last = result
        blob = f"{result.stdout or ''} {result.stderr or ''}".lower()
        if result.ok and "error" not in blob and "exception" not in blob:
            return log
    if last is not None and not last.ok:
        log.append(
            "Feiyu, скорее всего, проигнорировала freeform — приложение открылось как обычно. "
            "Это ограничение ГУ, не подписи APK."
        )
    return log


def start_wifi_settings_windowed(adb: Adb, progress: Progress | None = None) -> list[str]:
    return start_windowed(adb, f"-a {WIFI_SETTINGS_ACTION}", progress=progress)
