"""Install APKs onto a Changan head unit, bypassing the missing vendor cert."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from hub.adb import Adb, CommandResult
from hub.signer import sign_apk

REMOTE_CANDIDATES = (
    "/data/media/0/Download",
    "/storage/emulated/0/Download",
    "/sdcard/Download",
    "/storage/emulated/0",
    "/sdcard",
)

Progress = Callable[[str, int], None]

# Visible pipeline in the Hub loader. Order matters for the checklist UI.
PROCESS_STAGES = (
    ("sign", "Подпись APK"),
    ("push", "Копирование на ГУ"),
    ("pm", "pm install"),
    ("start", "Запуск панели"),
)


def classify_install_step(message: str) -> str | None:
    """Map a live log line onto a PROCESS_STAGES key for the loader."""
    low = message.lower()
    if any(token in low for token in ("запуск:", "разрешение:", "колонк")):
        return "start"
    if any(token in low for token in ("pm install", "шаг 3/", "шаг 4/", "adb root", "кэш лаунчера")):
        return "pm"
    if any(token in low for token in ("push", "копир", "шаг 2/")):
        return "push"
    if any(token in low for token in ("подпис", "переподпис", "шаг 1/")):
        return "sign"
    return None


@dataclass
class InstallReport:
    ok: bool
    signed_apk: Path | None
    method: str
    log: list[str] = field(default_factory=list)
    package: str | None = None

    def add(self, line: str) -> None:
        self.log.append(line)


def _ok_install(result: CommandResult) -> bool:
    blob = (result.stdout + "\n" + result.stderr).lower()
    if "success" in blob:
        return True
    if result.code == 124:
        return False
    if result.ok and "error" not in blob and "fail" not in blob and result.stdout.strip():
        return True
    return False


def install_apk(
    adb: Adb,
    apk: Path,
    already_signed: bool = False,
    progress: Progress | None = None,
) -> InstallReport:
    apk = Path(apk)
    report = InstallReport(ok=False, signed_apk=None, method="")

    def step(message: str, percent: int) -> None:
        report.add(message)
        if progress:
            progress(message, percent)

    if not apk.exists():
        step(f"Файл не найден: {apk}", 0)
        return report

    step(f"Начинаю установку {apk.name}", 5)
    if already_signed:
        signed = apk
        step("Переподпись не нужна.", 15)
    else:
        step("Шаг 1/5: подпись APK под Changan…", 10)
        signed = sign_apk(apk)
        step(f"Подписано: {signed}", 25)
    report.signed_apk = signed

    # Feiyu: `adb install` with anything on stdin hangs until timeout (180s).
    # Skip it and push + pm install, which is the working community method.
    step("Шаг 2/5: копирую APK на ГУ (push). adb install пропускаю — на Feiyu он зависает.", 35)
    remote_apk = None
    for folder in REMOTE_CANDIDATES:
        remote = f"{folder}/{signed.name.replace(' ', '_')}"
        step(f"push → {remote}", 40)
        pushed = adb.push(signed, remote, timeout=40)
        step(
            f"push code={pushed.code} stdout={pushed.stdout.strip()!r} stderr={pushed.stderr.strip()!r}",
            45,
        )
        if pushed.ok and "error" not in (pushed.stdout + pushed.stderr).lower() and pushed.code != 124:
            remote_apk = remote
            break
    if not remote_apk:
        step("Не удалось скопировать APK. Проверьте ADB-режим (USB切换 → ADB模式).", 45)
        return report

    step("Шаг 3/5: pm install на ГУ…", 60)
    for flag in ("-r -t -g", "-r -t", "-t", "-r"):
        cmd = f"pm install {flag} {remote_apk}".replace("  ", " ")
        step(f"выполняю {cmd}", 65)
        result = adb.shell(cmd, timeout=25)
        step(
            f"{cmd} code={result.code} stdout={result.stdout.strip()!r} stderr={result.stderr.strip()!r}",
            70,
        )
        if _ok_install(result):
            report.ok = True
            report.method = f"pm install {flag}"
            adb.shell(f"rm {remote_apk}", timeout=8)
            step("Шаг 4/5: чищу кэш лаунчера…", 85)
            _after_install(adb, report)
            step("Шаг 5/5: пакет установлен.", 100)
            return report

    step("pm install не прошёл. Пробую adb root (часто недоступен)…", 75)
    root = adb.try_root()
    step(f"adb root: {root.text or root.stderr}", 78)
    remount = adb.try_remount()
    step(f"adb remount: {remount.text or remount.stderr}", 80)
    if remount.ok:
        sys_path = "/system/app/ChanganHubSideload/" + signed.name
        adb.shell("mkdir -p /system/app/ChanganHubSideload", timeout=8)
        pushed = adb.push(signed, sys_path, timeout=40)
        step(f"system push: {pushed.text or pushed.stderr}", 90)
        adb.shell(f"chmod 644 {sys_path}", timeout=8)
        report.ok = True
        report.method = "system/app push"
        step("Файл в /system/app. Перезагрузите ГУ.", 100)
        return report

    step("Установка не удалась. Смотрите строки pm install выше.", 100)
    return report


def _after_install(adb: Adb, report: InstallReport) -> None:
    for result in adb.clear_launcher_cache():
        report.add(result.text or result.stderr or "ok")
    report.add("Иконки в штатном меню Feiyu может не быть — это нормально.")
