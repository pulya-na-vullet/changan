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
    report = install_apk(adb, apk, already_signed=False)
    lines = list(report.log)
    if report.ok:
        lines += start_overlay(adb)
        lines.append("Правая панель должна появиться поверх всех окон.")
        lines.append("Сверните её жестом вправо, разверните тапом по ▸. Удержание иконки — в избранное.")
    return lines
