"""Deploy and control the right-edge QuickBar overlay."""

from __future__ import annotations

from pathlib import Path

from hub.adb import Adb
from hub.installer import Progress, install_apk
from hub.paths import bundled_apps

# New applicationId: Feiyu forbids deleting already-installed auth packages
# (提示 «is auth app, not allow delete!»). quickbar then quickdock stay on the
# HU; this id is a first install so a new signature can land.
PACKAGE = "com.changanhub.quicklane"
LEGACY_PACKAGES = (
    "com.changanhub.quickbar",
    "com.changanhub.quickdock",
)
LEGACY_PACKAGE = LEGACY_PACKAGES[0]
JAVA_SERVICE = "com.changanhub.quickbar.OverlayService"
SERVICE = f"{PACKAGE}/{JAVA_SERVICE}"

# Keep the panel alive after ACC off→on. Feiyu drops BOOT_COMPLETED;
# deviceidle + background appops stop the HU from freezing the process.
PERSIST_SHELL = (
    f"appops set {PACKAGE} SYSTEM_ALERT_WINDOW allow",
    f"appops set {PACKAGE} RUN_IN_BACKGROUND allow",
    f"appops set {PACKAGE} RUN_ANY_IN_BACKGROUND allow",
    f"dumpsys deviceidle whitelist +{PACKAGE}",
    f"am set-inactive {PACKAGE} false",
    f"appops set {PACKAGE} REQUEST_INSTALL_PACKAGES allow",
    f"appops set {PACKAGE} GET_USAGE_STATS allow",
    f"pm grant {PACKAGE} android.permission.READ_EXTERNAL_STORAGE",
    f"pm grant {PACKAGE} android.permission.WRITE_EXTERNAL_STORAGE",
    "settings put secure install_non_market_apps 1",
)


def overlay_apk() -> Path:
    return bundled_apps() / "QuickBar.apk"


def grant_overlay(adb: Adb, progress: Progress | None = None) -> list[str]:
    log = []
    for cmd in PERSIST_SHELL:
        if progress:
            progress(f"разрешение: {cmd}", 90)
        result = adb.shell(cmd, timeout=10)
        log.append(f"{cmd} code={result.code} out={result.stdout.strip()!r} err={result.stderr.strip()!r}")
    return log


def _retire_package(adb: Adb, pkg: str, progress: Progress | None = None) -> list[str]:
    """Hide an undeletable old overlay. ``pm uninstall`` shows 提示 «not allow delete»
    and times out; Feiyu never removes an auth package. Do not call ``pm disable``
    without ``--user`` — shell gets SecurityException then hangs the retry."""
    log: list[str] = []
    for cmd in (
        f"am startservice -n {pkg}/{JAVA_SERVICE} -a com.changanhub.quickbar.HIDE",
        f"am startservice -n {pkg}/{JAVA_SERVICE} -a com.changanhub.quickbar.PAUSE",
        f"am force-stop {pkg}",
        f"appops set {pkg} SYSTEM_ALERT_WINDOW ignore",
        f"dumpsys deviceidle whitelist -{pkg}",
        f"pm disable-user --user 0 {pkg}",
    ):
        if progress:
            progress(f"старая панель: {cmd}", 88)
        result = adb.shell(cmd, timeout=8)
        log.append(f"{cmd} code={result.code} out={result.stdout.strip()!r} err={result.stderr.strip()!r}")
    return log


def retire_legacy(adb: Adb, progress: Progress | None = None) -> list[str]:
    log: list[str] = []
    for pkg in LEGACY_PACKAGES:
        log += _retire_package(adb, pkg, progress=progress)
    return log


def start_overlay(adb: Adb, progress: Progress | None = None) -> list[str]:
    log = retire_legacy(adb, progress=progress)
    if progress:
        progress(f"включаю пакет {PACKAGE}", 89)
    enabled = adb.shell(f"pm enable --user 0 {PACKAGE}", timeout=8)
    log.append(
        f"pm enable --user 0 {PACKAGE} code={enabled.code} "
        f"out={enabled.stdout.strip()!r} err={enabled.stderr.strip()!r}"
    )
    log += grant_overlay(adb, progress=progress)
    # Only the overlay service. am start / monkey would pop MainActivity over
    # the map; boot broadcasts would expand a collapsed dock.
    for cmd in (
        f"am startservice -n {SERVICE}",
        f"am start-foreground-service -n {SERVICE}",
        f"am startservice -n {SERVICE} -a com.changanhub.quickbar.SHOW",
    ):
        if progress:
            progress(f"запуск: {cmd}", 95)
        result = adb.shell(cmd, timeout=10)
        log.append(f"{cmd} code={result.code} out={result.stdout.strip()!r} err={result.stderr.strip()!r}")
    return log


def stop_overlay(adb: Adb) -> list[str]:
    lines = []
    for pkg in (PACKAGE, *LEGACY_PACKAGES):
        result = adb.shell(f"am force-stop {pkg}", timeout=10)
        lines.append(f"force-stop {pkg} code={result.code} {result.text or result.stderr}")
    return lines


def remove_overlay(adb: Adb, progress: Progress | None = None) -> list[str]:
    lines: list[str] = []

    def step(message: str, percent: int) -> None:
        lines.append(message)
        if progress:
            progress(message, percent)

    step("Feiyu не удаляет auth-приложение (提示 not allow delete). Отключаю панели.", 40)
    lines += retire_legacy(adb, progress=progress)
    lines += _retire_package(adb, PACKAGE, progress=progress)
    return lines


def install_overlay(adb: Adb, progress: Progress | None = None) -> list[str]:
    apk = overlay_apk()
    if not apk.exists():
        return [f"QuickBar.apk не найден: {apk}"]
    lines = [f"Файл панели: {apk} ({apk.stat().st_size} байт)"]
    if progress:
        progress(lines[0], 5)
    report = install_apk(adb, apk, already_signed=False, progress=progress, package=PACKAGE)
    lines.extend(report.log)
    if not report.ok:
        if any("not auth" in line.lower() or "-118" in line for line in report.log):
            lines.append(
                "Пакет НЕ установлен. Белое окно 提示 «is not auth, install failed!» — "
                "отказ белого списка Feiyu (pm -118), не краш. "
                f"Имя после успеха: QuickBar / {PACKAGE}."
            )
        else:
            lines.append(
                f"Пакет НЕ установлен. В «Приложения ГУ» не будет {PACKAGE}. "
                f"Имя после успеха: QuickBar / {PACKAGE}."
            )
        if progress:
            progress("Установка не удалась — пакета в списке не будет.", 100)
        return lines
    lines.append(f"Пакет установлен. В списке ГУ: QuickBar · {PACKAGE}")
    lines += start_overlay(adb, progress=progress)
    if progress:
        progress("Готово. Ищите зелёную колонку СПРАВА, не иконку в меню.", 100)
    lines.append("Панель — зелёная колонка СПРАВА поверх экрана, не пункт в меню приложений.")
    lines.append(
        "Старые com.changanhub.quickbar и com.changanhub.quickdock Feiyu не даёт удалить "
        "(auth, not allow delete) — Hub их отключает и ставит новую com.changanhub.quicklane."
    )
    return lines
