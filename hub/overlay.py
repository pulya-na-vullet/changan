"""Deploy and control the right-edge QuickBar overlay."""

from __future__ import annotations

from pathlib import Path

from hub.adb import Adb
from hub.installer import Progress, install_apk
from hub.paths import bundled_apps

PACKAGE = "com.changanhub.quickbar"
SERVICE = f"{PACKAGE}/.OverlayService"


def overlay_apk() -> Path:
    return bundled_apps() / "QuickBar.apk"


def grant_overlay(adb: Adb, progress: Progress | None = None) -> list[str]:
    log = []
    for cmd in (
        f"appops set {PACKAGE} SYSTEM_ALERT_WINDOW allow",
        f"cmd appops set {PACKAGE} SYSTEM_ALERT_WINDOW allow",
    ):
        if progress:
            progress(f"разрешение: {cmd}", 90)
        result = adb.shell(cmd, timeout=10)
        log.append(f"{cmd} code={result.code} out={result.stdout.strip()!r} err={result.stderr.strip()!r}")
    return log


def start_overlay(adb: Adb, progress: Progress | None = None) -> list[str]:
    log = grant_overlay(adb, progress=progress)
    for cmd in (
        f"am start -n {PACKAGE}/.MainActivity",
        f"monkey -p {PACKAGE} -c android.intent.category.LAUNCHER 1",
        f"am startservice -n {SERVICE}",
        f"am start-foreground-service -n {SERVICE}",
        f"am startservice -n {SERVICE} -a {PACKAGE}.SHOW",
    ):
        if progress:
            progress(f"запуск: {cmd}", 95)
        result = adb.shell(cmd, timeout=10)
        log.append(f"{cmd} code={result.code} out={result.stdout.strip()!r} err={result.stderr.strip()!r}")
    return log


def stop_overlay(adb: Adb) -> list[str]:
    result = adb.shell(f"am force-stop {PACKAGE}", timeout=10)
    return [f"force-stop code={result.code} {result.text or result.stderr}"]


def install_overlay(adb: Adb, progress: Progress | None = None) -> list[str]:
    apk = overlay_apk()
    if not apk.exists():
        return [f"QuickBar.apk не найден: {apk}"]
    lines = [f"Файл панели: {apk} ({apk.stat().st_size} байт)"]
    if progress:
        progress(lines[0], 5)
    report = install_apk(adb, apk, already_signed=False, progress=progress)
    lines.extend(report.log)
    if not report.ok:
        lines.append(
            "Пакет НЕ установлен. В «Приложения ГУ» не будет com.changanhub.quickbar, "
            "на экране машины — тоже. Имя после успеха: QuickBar / com.changanhub.quickbar."
        )
        if progress:
            progress("Установка не удалась — пакета в списке не будет.", 100)
        return lines
    lines.append("Пакет установлен. В списке ГУ: QuickBar · com.changanhub.quickbar")
    lines += start_overlay(adb, progress=progress)
    if progress:
        progress("Готово. Ищите зелёную колонку СПРАВА, не иконку в меню.", 100)
    lines.append("Панель — зелёная колонка СПРАВА поверх экрана, не пункт в меню приложений.")
    return lines
