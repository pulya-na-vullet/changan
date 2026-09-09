"""Install APKs onto a Changan head unit, bypassing the missing vendor cert."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from hub.adb import Adb, CommandResult
from hub.signer import sign_apk

REMOTE_CANDIDATES = (
    "/data/media/0/Download",
    "/storage/emulated/0/Download",
    "/sdcard/Download",
    "/storage/emulated/0",
    "/sdcard",
)


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
    if result.ok and "error" not in blob and "fail" not in blob:
        return True
    return False


def install_apk(adb: Adb, apk: Path, already_signed: bool = False) -> InstallReport:
    apk = Path(apk)
    report = InstallReport(ok=False, signed_apk=None, method="")
    if not apk.exists():
        report.add(f"Файл не найден: {apk}")
        return report

    if already_signed:
        signed = apk
        report.add("Пропускаю переподпись — файл уже подготовлен.")
    else:
        report.add("Подписываю APK серийным номером Changan (без сертификата разработчика).")
        signed = sign_apk(apk)
        report.add(f"Подписано: {signed}")
    report.signed_apk = signed

    report.add("Пробую adb install…")
    streamed = adb.install_stream(signed)
    report.add(streamed.text or streamed.stderr)
    if _ok_install(streamed):
        report.ok = True
        report.method = "adb install"
        _after_install(adb, report)
        return report
    report.add("adb install отклонён (так бывает на Feiyu). Гружу файл и ставлю через pm.")

    remote_apk = None
    for folder in REMOTE_CANDIDATES:
        remote = f"{folder}/{signed.name.replace(' ', '_')}"
        pushed = adb.push(signed, remote)
        report.add(f"push → {remote}: {pushed.text or pushed.stderr or pushed.code}")
        if pushed.ok and "error" not in (pushed.stdout + pushed.stderr).lower():
            remote_apk = remote
            break
    if not remote_apk:
        report.add("Не удалось скопировать APK на ГУ. Проверьте кабель и ADB-режим.")
        return report

    for flag in ("-r -t -g", "-r -t", "-t", "-r"):
        cmd = f"pm install {flag} {remote_apk}".replace("  ", " ")
        result = adb.shell(cmd, timeout=180)
        report.add(f"{cmd}: {result.text or result.stderr}")
        if _ok_install(result):
            report.ok = True
            report.method = f"pm install {flag}"
            adb.shell(f"rm {remote_apk}")
            _after_install(adb, report)
            return report

    report.add("Пробую adb root + system install (не на всех прошивках работает).")
    root = adb.try_root()
    report.add(root.text or root.stderr)
    remount = adb.try_remount()
    report.add(remount.text or remount.stderr)
    if remount.ok:
        sys_path = "/system/app/ChanganHubSideload/" + signed.name
        adb.shell("mkdir -p /system/app/ChanganHubSideload")
        pushed = adb.push(signed, sys_path)
        report.add(pushed.text or pushed.stderr)
        chmod = adb.shell(f"chmod 644 {sys_path}")
        report.add(chmod.text or chmod.stderr)
        report.add("Файл положен в /system/app. Нужна перезагрузка ГУ.")
        report.ok = True
        report.method = "system/app push"
        return report

    report.add("Установка не удалась. Смотрите лог: часто это «not auth» без правильной подписи.")
    return report


def _after_install(adb: Adb, report: InstallReport) -> None:
    report.add("Чищу кэш штатного лаунчера, чтобы иконка появилась.")
    for result in adb.clear_launcher_cache():
        report.add(result.text or result.stderr or "ok")
    report.add("Если иконки нет на рабочем столе — перезагрузите ГУ (громкость «−» 10–20 сек).")
