"""Install the Lamore floating Wi-Fi button (changan_wifi APK, unmodified)."""

from __future__ import annotations

from pathlib import Path

from hub.adb import Adb
from hub.installer import Progress, install_apk
from hub.paths import bundled_apps
from hub.windowed import enable_freeform, start_wifi_settings_windowed

# APK from https://github.com/pulya-na-vullet/changan_wifi — source is not copied here.
PACKAGE = "com.lamore.wifibutton"
JAVA_MAIN = "com.lamore.wifibutton.MainActivity"
JAVA_SERVICE = "com.lamore.wifibutton.FloatingService"
SOURCE_URL = "https://github.com/pulya-na-vullet/changan_wifi"

GRANT_SHELL = (
    f"appops set {PACKAGE} SYSTEM_ALERT_WINDOW allow",
    f"appops set {PACKAGE} RUN_IN_BACKGROUND allow",
    f"appops set {PACKAGE} RUN_ANY_IN_BACKGROUND allow",
    f"appops set {PACKAGE} START_FOREGROUND allow",
    f"dumpsys deviceidle whitelist +{PACKAGE}",
    f"am set-inactive {PACKAGE} false",
)


def wifi_apk() -> Path:
    return bundled_apps() / "WifiButton.apk"


def is_wifi_package(package: str) -> bool:
    return package == PACKAGE


def grant_wifi(adb: Adb, progress: Progress | None = None) -> list[str]:
    log: list[str] = []
    for cmd in GRANT_SHELL:
        if progress:
            progress(f"разрешение: {cmd}", 90)
        result = adb.shell(cmd, timeout=10)
        log.append(f"{cmd} code={result.code} out={result.stdout.strip()!r} err={result.stderr.strip()!r}")
    return log


def start_wifi(adb: Adb, progress: Progress | None = None, second_vision: bool = True) -> list[str]:
    """Show the floating button and optionally open Wi-Fi settings in a 10% inset window."""
    log: list[str] = []
    if progress:
        progress(f"включаю {PACKAGE}", 92)
    enabled = adb.shell(f"pm enable --user 0 {PACKAGE}", timeout=8)
    log.append(
        f"pm enable --user 0 {PACKAGE} code={enabled.code} "
        f"out={enabled.stdout.strip()!r} err={enabled.stderr.strip()!r}"
    )
    log += grant_wifi(adb, progress=progress)
    log += enable_freeform(adb, progress=progress)
    for cmd in (
        f"am startservice -n {PACKAGE}/{JAVA_SERVICE}",
        f"am start-foreground-service -n {PACKAGE}/{JAVA_SERVICE}",
        f"am start -n {PACKAGE}/{JAVA_MAIN}",
    ):
        if progress:
            progress(f"запуск: {cmd}", 95)
        result = adb.shell(cmd, timeout=10)
        log.append(f"{cmd} code={result.code} out={result.stdout.strip()!r} err={result.stderr.strip()!r}")
    if second_vision:
        log.append("второй экран Wi-Fi: системные настройки в окне с полями 10%.")
        log += start_wifi_settings_windowed(adb, progress=progress)
    return log


def install_wifi(adb: Adb, progress: Progress | None = None) -> list[str]:
    apk = wifi_apk()
    if not apk.exists():
        return [
            f"WifiButton.apk не найден: {apk}. "
            f"Скачайте wifi-button-lamore-debug.apk из {SOURCE_URL} в apps/WifiButton.apk."
        ]
    lines = [f"Файл Wi-Fi кнопки: {apk} ({apk.stat().st_size} байт)"]
    if progress:
        progress(lines[0], 5)
    report = install_apk(adb, apk, already_signed=False, progress=progress, package=PACKAGE)
    lines.extend(report.log)
    if not report.ok:
        lines.append(f"Wi-Fi кнопка НЕ установлена. В списке ГУ не будет {PACKAGE}.")
        return lines
    lines.append(f"Пакет установлен. В списке ГУ: Wi-Fi ГУ Changan · {PACKAGE}")
    lines += start_wifi(adb, progress=progress, second_vision=True)
    lines.append(
        "Плавающая кнопка поверх карты: тап — вкл/выкл Wi-Fi, шестерёнка — настройки. "
        "Hub сразу открывает ещё и системные настройки Wi-Fi в окне (второй экран), "
        "чтобы карта оставалась видна по краям, если Feiyu умеет freeform. "
        "Исходники changan_wifi Hub не трогает."
    )
    return lines
