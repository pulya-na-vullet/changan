"""Deploy and control the right-edge QuickBar overlay."""

from __future__ import annotations

from pathlib import Path

from hub.adb import Adb
from hub.installer import install_apk
from hub.paths import bundled_apps

PACKAGE = "com.changanhub.quickbar"
SERVICE = f"{PACKAGE}/.OverlayService"


def overlay_apk() -> Path:
    return bundled_apps() / "QuickBar.apk"


def grant_overlay(adb: Adb) -> list[str]:
    log = []
    for cmd in (
        f"appops set {PACKAGE} SYSTEM_ALERT_WINDOW allow",
        f"cmd appops set {PACKAGE} SYSTEM_ALERT_WINDOW allow",
    ):
        result = adb.shell(cmd, timeout=10)
        log.append(f"{cmd} code={result.code} out={result.stdout.strip()!r} err={result.stderr.strip()!r}")
    return log


def start_overlay(adb: Adb) -> list[str]:
    log = grant_overlay(adb)
    for cmd in (
        f"am start -n {PACKAGE}/.MainActivity",
        f"monkey -p {PACKAGE} -c android.intent.category.LAUNCHER 1",
        f"am startservice -n {SERVICE}",
        f"am start-foreground-service -n {SERVICE}",
        f"am startservice -n {SERVICE} -a {PACKAGE}.SHOW",
    ):
        result = adb.shell(cmd, timeout=10)
        log.append(f"{cmd} code={result.code} out={result.stdout.strip()!r} err={result.stderr.strip()!r}")
    return log


def stop_overlay(adb: Adb) -> list[str]:
    result = adb.shell(f"am force-stop {PACKAGE}", timeout=10)
    return [f"force-stop code={result.code} {result.text or result.stderr}"]


def install_overlay(adb: Adb) -> list[str]:
    apk = overlay_apk()
    if not apk.exists():
        return [f"QuickBar.apk не найден: {apk}"]
    lines = [f"Файл панели: {apk} ({apk.stat().st_size} байт)"]
    report = install_apk(adb, apk, already_signed=False)
    lines.extend(report.log)
    if report.ok:
        lines.append("Установщик вернул успех. Запускаю панель (иконки в штатном меню Feiyu часто нет).")
    else:
        lines.append("Установщик не подтвердил успех — всё равно пробую запустить, пакет мог встать.")
    lines += start_overlay(adb)
    lines.append("Панель — зелёная колонка СПРАВА поверх экрана, не иконка в меню приложений.")
    lines.append("Если колонки нет: громкость «−» 10–20 сек, затем в Hub «Только запустить».")
    return lines
