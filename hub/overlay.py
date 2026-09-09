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
    commands = [
        f"appops set {PACKAGE} SYSTEM_ALERT_WINDOW allow",
        f"cmd appops set {PACKAGE} SYSTEM_ALERT_WINDOW allow",
        f"settings put secure enabled_accessibility_services {PACKAGE}/.OverlayService",
        f"dumpsys package {PACKAGE}",
    ]
    for cmd in commands[:2]:
        result = adb.shell(cmd)
        log.append(f"{cmd}: {result.text or result.stderr or 'ok'}")
    return log


def start_overlay(adb: Adb) -> list[str]:
    log = grant_overlay(adb)
    for cmd in (
        f"am start-foreground-service -n {SERVICE}",
        f"am startservice -n {SERVICE}",
        f"am start -n {PACKAGE}/.MainActivity",
        f"am startservice -n {SERVICE} -a {PACKAGE}.SHOW",
    ):
        result = adb.shell(cmd)
        log.append(f"{cmd}: {result.text or result.stderr or 'ok'}")
        blob = (result.stdout + result.stderr).lower()
        if result.ok and "error" not in blob and "exception" not in blob:
            break
    return log


def stop_overlay(adb: Adb) -> list[str]:
    result = adb.shell(f"am force-stop {PACKAGE}")
    return [result.text or result.stderr or "stopped"]


def install_overlay(adb: Adb) -> list[str]:
    apk = overlay_apk()
    if not apk.exists():
        return [f"QuickBar.apk не найден: {apk}. Соберите его через scripts/build_apk.py"]
    lines = [f"Файл панели: {apk} ({apk.stat().st_size} байт)"]
    report = install_apk(adb, apk, already_signed=False)
    lines.extend(report.log)
    installed = adb.package_path(PACKAGE)
    if installed:
        lines.append(f"Проверка: пакет {PACKAGE} стоит по пути {installed}")
        report.ok = True
    else:
        lines.append(f"Проверка: пакета {PACKAGE} на ГУ нет (pm path пустой).")
    if report.ok:
        lines += start_overlay(adb)
        again = adb.package_path(PACKAGE)
        lines.append(f"После запуска панели pm path: {again or 'пусто'}")
        lines.append("Правая панель должна появиться справа поверх всех окон.")
        lines.append("Если её нет — перезагрузите ГУ (громкость «−» 10–20 сек) и нажмите «Только запустить».")
    else:
        lines.append("Установка панели не подтверждена. Весь вывод ADB выше — для отладки.")
    return lines
