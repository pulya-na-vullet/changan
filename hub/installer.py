"""Install APKs onto a Changan head unit, bypassing the missing vendor cert."""

from __future__ import annotations

import json
import re
import shutil
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from hub.adb import Adb, CommandResult, _no_adb_target
from hub.bundle import (
    BundleSplit,
    bundle_package_name,
    extract_bundle,
    is_apk_bundle,
    parse_install_session,
)
from hub.signer import CHANGAN_SERIAL, apk_certificate_serials, ensure_keystore, sign_apk_with_method

OVERLAY_PACKAGES = (
    "com.changanhub.quickrise",
    "com.changanhub.quickkeep",
    "com.changanhub.quicklane",
    "com.changanhub.quickdock",
    "com.changanhub.quickbar",
)
# Sideloads Feiyu will not delete. A new Hub ZIP mints a new RSA key, so
# pm install -r hits UPDATE_INCOMPATIBLE. Do not uninstall or disable these.
KEEP_EXISTING_PACKAGES = OVERLAY_PACKAGES + (
    "com.changanhub.playrise",
    "com.changanhub.lamoreplayer",
    "com.changanhub.chatrise",
    "com.changanhub.aichat",
)

# Logs from Lamore Feiyu: first push to tmp succeeds; extra folders only add noise.
REMOTE_CANDIDATES = (
    "/data/local/tmp",
    "/sdcard/Download",
)

# Same logs: every flag combo returned the same pm result. Keep the one that
# actually talks to PackageManager (`-g` grants runtime perms on first install).
PM_INSTALL_FLAGS = "-r -t -g"
MAX_SIDELOAD_PROBE = 12 * 1024 * 1024

_INCOMPATIBLE_PKG = re.compile(r"Package ([A-Za-z0-9._]+) signatures", re.I)

# Already-installed third-party apps on this HU — their signing serial is the
# real whitelist, which may differ from the CS75PLUS cookbook value. Russified
# cars often have HackChan/Yandex and never NewPipe.
PROBE_PACKAGES = (
    "org.schabi.newpipe",
    "net.easyconn",
    "gb.xxy.hr",
    "ru.hackchan.launcher",
    "ru.hackchan.settings",
    "ru.hackchan.installer",
    "air.StrelkaHUDFREE",
    "ru.yandex.yandexnavi",
    "ru.yandex.yandexmaps",
    "ru.yandex.music",
    "com.yandex.browser.lite",
    "com.yandex.browser",
    "ru.dublgis.dgismobile",
    "com.navitel",
    "com.vkontakte.android",
    "ru.rutube.app",
)

# Official RU / overlay firmware often has zero /data/app packages.
# Leosin CertificateManager compares the APK serial to a system cert
# (Vecentek/publicKey.cert) and a package list in whitelist.json.
MANAGER_PATHS = (
    "/system/app/VecentekApp/VecentekApp.apk",
    "/system/framework/ext.jar",
    "/system/framework/arm64/boot-ext.vdex",
)
WHITELIST_FILE_PATHS = (
    "/back_up/allow_uninstall/whitelist.json",
    "/back_up/allow_uninstall/publicKey.cert",
    "/system/back_up/allow_uninstall/whitelist.json",
    "/system/back_up/allow_uninstall/publicKey.cert",
    "/data/back_up/allow_uninstall/whitelist.json",
    "/data/back_up/allow_uninstall/publicKey.cert",
    "/sdcard/back_up/allow_uninstall/whitelist.json",
    "/sdcard/back_up/allow_uninstall/publicKey.cert",
    "/storage/emulated/0/back_up/allow_uninstall/whitelist.json",
    "/storage/emulated/0/back_up/allow_uninstall/publicKey.cert",
)
MANAGER_HINTS = ("vecentek", "boot-ext", "certificatemanager", "wutong", "leosin")
WHITELIST_HINTS = ("vecentek", "boot-ext", "certificatemanager", "wutong", "leosin", "ext.jar")
_HEX16 = re.compile(rb"(?<![0-9a-fA-F])([0-9a-fA-F]{16})(?![0-9a-fA-F])")
_AUTH_NEEDLES = (
    b"not auth",
    b"CertificateManager",
    b"is not auth",
    b"install failed!",
    b"ddb66eefd98476f3",
    b"DDB66EEFD98476F3",
    b"allow_uninstall",
    b"getCertnum",
    b"Leosin",
    b"WHITE-LIST",
)
_JUNK_SERIALS = {
    0x0123456789ABCDEF,
    0x123456789ABCDEF,
    0x1234567890ABCDEF,
    0xFEDCBA9876543210,
    0x0FEDCBA987654321,
    0xABCDEF0123456789,
}

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
    if any(
        token in low
        for token in (
            "pm install",
            "pm uninstall",
            "install-create",
            "install-write",
            "install-commit",
            "удал",
            "шаг 3/",
            "шаг 4/",
            "adb root",
            "кэш лаунчера",
        )
    ):
        return "pm"
    if any(token in low for token in ("push", "копир", "шаг 2/", "obb")):
        return "push"
    if any(token in low for token in ("подпис", "переподпис", "шаг 1/", "распаков", "xapk", "сплит")):
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


def _ok_uninstall(result: CommandResult) -> bool:
    blob = (result.stdout + "\n" + result.stderr).lower()
    if result.code == 124:
        return False
    if "not allow delete" in blob or "failure" in blob or "error" in blob:
        return False
    return "success" in blob or result.ok


def _ok_install(result: CommandResult) -> bool:
    blob = (result.stdout + "\n" + result.stderr).lower()
    if "failure" in blob or "error" in blob or "not auth" in blob:
        return False
    if result.code == 124:
        return False
    if "success" in blob:
        return True
    if result.ok and result.stdout.strip():
        return True
    return False


def adb_target_gone(result: CommandResult) -> bool:
    return _no_adb_target(f"{result.stdout or ''}\n{result.stderr or ''}")


def _transfer_timeout(path: Path, minimum: int = 40) -> int:
    size = path.stat().st_size if path.exists() else 0
    mb = max(1, size // (1024 * 1024))
    return min(180, max(minimum, 20 + mb))


def _pm_timeout(path: Path) -> int:
    size = path.stat().st_size if path.exists() else 0
    mb = size // (1024 * 1024)
    return min(180, max(45, 30 + mb // 2))


def _remote_apk_basename(signed: Path, package: str | None) -> str:
    base = package or signed.stem
    ascii_name = "".join(
        ch if ch.isascii() and (ch.isalnum() or ch in "._-") else "_" for ch in base
    )
    ascii_name = re.sub(r"_+", "_", ascii_name).strip("._") or "app"
    if ascii_name[0].isdigit():
        ascii_name = "hub-" + ascii_name
    if not ascii_name.lower().endswith(".apk"):
        ascii_name += ".apk"
    return ascii_name[:120]


def _confirm_installed(adb: Adb, package: str | None, step: Progress, attempts: int = 10) -> bool:
    if not package:
        return False
    for index in range(attempts):
        result = adb.shell(f"pm path {package}", timeout=10)
        if adb_target_gone(result):
            return False
        if "package:" in merged_output(result):
            return True
        if index + 1 < attempts:
            time.sleep(3)
            step(
                f"жду появления {package} в pm path ({index + 1}/{attempts})…",
                72,
            )
    return False


def install_apk(
    adb: Adb,
    apk: Path,
    already_signed: bool = False,
    progress: Progress | None = None,
    package: str | None = None,
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
    if is_apk_bundle(apk):
        return _install_bundle(adb, apk, report, step, package=package)

    package = package or apk_package_name(apk)
    used_serial: int | None = None
    remaining: list[int] = []
    if already_signed:
        signed = apk
        step("Переподпись не нужна.", 15)
    else:
        used_serial, signed, method, remaining = _sign_for_hu(adb, apk, package, step)
        package = package or apk_package_name(signed)
    report.signed_apk = signed
    report.package = package

    if package:
        present = adb.shell(f"pm path {package}", timeout=8)
        if "package:" in merged_output(present):
            adb.shell(f"pm enable --user 0 {package}", timeout=8)

    result, remote_apk = _push_and_pm(adb, signed, step, package=package)
    if remote_apk is None:
        return report
    blob = merged_output(result)
    kept = _keep_working_overlay(adb, report, result, blob, package, step, remote_apk)
    if kept is not None:
        return kept
    if not _ok_install(result) and "update_incompatible" in blob.lower():
        conflict = _package_from_pm_error(blob) or package
        overlay_conflict = bool(
            (conflict and conflict in OVERLAY_PACKAGES) or (package and package in OVERLAY_PACKAGES)
        )
        keep_conflict = bool(
            (conflict and conflict in KEEP_EXISTING_PACKAGES)
            or (package and package in KEEP_EXISTING_PACKAGES)
        )
        if keep_conflict and conflict and package and conflict == package:
            step(
                f"Подпись не совпадает со стоящим {conflict}. Рабочий пакет не отключаю.",
                72,
            )
        elif overlay_conflict:
            step(
                f"Подпись не совпадает со стоящим {conflict}. Feiyu не даёт удалить "
                "auth-приложение (提示 not allow delete) — pm uninstall не вызываю. "
                "Старую панель отключаю. Рабочая QuickBar — com.changanhub.quickrise.",
                72,
            )
            if conflict:
                uninstall_package(adb, conflict, step)
        elif keep_conflict:
            step(
                f"Подпись не совпадает со стоящим {conflict}. Feiyu не даёт удалить "
                "auth-приложение — pm uninstall не вызываю. Плеер и чат не отключаю. "
                "Новые пакеты: com.changanhub.playrise и com.changanhub.chatrise.",
                72,
            )
        else:
            step(
                f"Подпись не совпадает со стоящим {conflict}. Пробую pm uninstall --user 0 "
                "(лимит 8с), затем повторную установку.",
                72,
            )
            if conflict:
                gone = adb.shell(f"pm uninstall --user 0 {conflict}", timeout=8)
                step(
                    f"pm uninstall --user 0 {conflict} code={gone.code} "
                    f"stdout={gone.stdout.strip()!r} stderr={gone.stderr.strip()!r}",
                    73,
                )
                if _ok_uninstall(gone):
                    result, remote_apk = _push_and_pm(
                        adb, signed, step, start_pct=74, package=package
                    )
                    if remote_apk is None:
                        return report
                else:
                    step(
                        "Feiyu не сняла пакет (提示 not allow delete или timeout). "
                        "Не отключаю. Ставьте новый id из этого Hub.",
                        75,
                    )
    if _ok_install(result):
        return _finish_ok(adb, report, remote_apk, step)

    blob = " ".join(report.log).lower()
    if "no_certificates" in blob or "smimecapability" in blob:
        step(
            "ГУ отвергла подпись APK (NO_CERTIFICATES). Пакет не установлен — "
            "в списке com.changanhub.quickrise не появится.",
            100,
        )
        return report
    if "not auth" in blob or "-118" in blob:
        if not already_signed:
            logcat_serials = _auth_logcat_serials(adb, step)
            retry = list(remaining)
            for item in logcat_serials:
                if item != used_serial and item not in retry:
                    retry.insert(0, item)
            for fresh in _next_auth_serials(adb, used_serial, retry, step):
                used_serial, signed, method = _sign_with_serial(
                    adb, apk, fresh, step, retry=True
                )
                report.signed_apk = signed
                result, remote_apk = _push_and_pm(adb, signed, step, package=package)
                if remote_apk is None:
                    return report
                if _ok_install(result):
                    return _finish_ok(adb, report, remote_apk, step)
        step(
            "ГУ показала «is not auth, install failed» (код -118). Это отказ белого "
            "списка Feiyu при установке, не при удалении. Старую панель Hub не снимал. "
            "Файлы VecentekApp.apk, boot-ext.vdex, whitelist.json и publicKey.cert — "
            "в data\\probe, пришлите их с журналом.",
            100,
        )
        return report

    if "extract native libraries" in blob or (
        "install_failed_invalid_apk" in blob and "androidmanifest.xml" not in blob
    ):
        step(
            "APK с native .so Feiyu не распаковала (extract native libraries). "
            "Ставьте исходный файл (не *-changan.apk) этой сборкой Hub — подпись "
            "сохраняет несжатые библиотеки.",
            100,
        )
        return report

    if _is_older_sdk(blob):
        _explain_older_sdk(step)
        return report

    if _is_missing_manifest(blob):
        _explain_missing_manifest(step)
        return report

    step("pm install не прошёл. adb root на Feiyu не трогаю — он рвёт USB.", 100)
    return report


def _after_install(adb: Adb, report: InstallReport) -> None:
    for result in adb.clear_launcher_cache():
        report.add(result.text or result.stderr or "ok")
    report.add(
        "В штатном меню Feiyu сторонней иконки не будет — это нормально. "
        "Откройте приложение из зелёной колонки QuickBar справа или из «Приложения ГУ»."
    )


def _finish_ok(
    adb: Adb, report: InstallReport, remote_apk: str | None, step: Progress
) -> InstallReport:
    report.ok = True
    report.method = report.method or f"pm install {PM_INSTALL_FLAGS}"
    if remote_apk:
        adb.shell(f"rm {remote_apk}", timeout=8)
    step("Шаг 4/5: чищу кэш лаунчера…", 85)
    _after_install(adb, report)
    step("Шаг 5/5: пакет установлен.", 100)
    return report


def _keep_kind(package: str) -> str:
    if package in OVERLAY_PACKAGES:
        return "overlay"
    if package in ("com.changanhub.playrise", "com.changanhub.lamoreplayer"):
        return "player"
    return "chat"


def _finish_keep_overlay(
    adb: Adb,
    report: InstallReport,
    step: Progress,
    remote_apk: str | None = None,
    kind: str = "overlay",
) -> InstallReport:
    report.ok = True
    report.method = "keep-existing"
    if remote_apk:
        adb.shell(f"rm {remote_apk}", timeout=8)
    if kind == "player":
        msg = (
            "Плеер с этой подписью уже стоит. Не отключаю. "
            "Lamore Player 1.1 — пакет com.changanhub.playrise, раздел «Плеер»."
        )
    elif kind == "chat":
        msg = (
            "Чат с этой подписью уже стоит. Не отключаю. "
            "AI Chat — пакет com.changanhub.chatrise, раздел «Чат ИИ»."
        )
    else:
        msg = (
            "Рабочая панель уже стоит на ГУ. Этот APK не обновляет — подпись другого Hub. "
            "Колонку не отключаю. Дальше: «Только запустить», не повторная установка."
        )
    step(msg, 100)
    return report


def _keep_working_overlay(
    adb: Adb,
    report: InstallReport,
    result: CommandResult,
    blob: str,
    package: str | None,
    step: Progress,
    remote_apk: str | None,
) -> InstallReport | None:
    if _ok_install(result) or "update_incompatible" not in blob.lower():
        return None
    conflict = _package_from_pm_error(blob) or package
    if not conflict or not package or conflict != package:
        return None
    if conflict not in KEEP_EXISTING_PACKAGES:
        return None
    kind = _keep_kind(conflict)
    if kind == "overlay":
        step(
            f"Не обновляю {package}: подпись этого Hub не совпадает с уже стоящей. "
            "Рабочую колонку не отключаю.",
            72,
        )
    elif kind == "player":
        step(
            f"Не обновляю {package}: подпись этого Hub не совпадает с уже стоящей. "
            "Рабочий плеер не отключаю. Новый пакет — com.changanhub.playrise.",
            72,
        )
    else:
        step(
            f"Не обновляю {package}: подпись этого Hub не совпадает с уже стоящей. "
            "Рабочий чат не отключаю. Новый пакет — com.changanhub.chatrise.",
            72,
        )
    if _confirm_installed(adb, package, step, attempts=2):
        return _finish_keep_overlay(adb, report, step, remote_apk, kind=kind)
    return None


def _is_older_sdk(blob: str) -> bool:
    low = blob.lower()
    return "older_sdk" in low or "requires newer sdk" in low


def _is_missing_manifest(blob: str) -> bool:
    low = blob.lower()
    return "androidmanifest.xml" in low or "failed to parse apk" in low


def _explain_older_sdk(step: Progress) -> None:
    step(
        "Этот APK требует Android 10+ (SDK 29), а ГУ Feiyu — Android 9 (SDK 28). "
        "Свежий Chrome так не встанет. На ГУ уже есть Яндекс Браузер Лайт "
        "(com.yandex.browser.lite). Нужен Chrome с minSdk ≤ 28 или Fennec с F-Droid.",
        100,
    )


def _explain_missing_manifest(step: Progress) -> None:
    step(
        "Это не одиночный APK, а контейнер (XAPK/APKM): нет AndroidManifest.xml. "
        "Выберите исходный .xapk — Hub распакует внутренние APK и поставит их сессией.",
        100,
    )


def _bundle_work_dir(apk: Path) -> Path:
    from hub.paths import app_data

    stem = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in apk.stem)[:80] or "bundle"
    return app_data() / "bundle" / stem


def _install_bundle(
    adb: Adb,
    apk: Path,
    report: InstallReport,
    step: Progress,
    package: str | None = None,
) -> InstallReport:
    step("Это XAPK/APKM — распаковываю внутренние APK, контейнер на ГУ не ставлю.", 6)
    work = _bundle_work_dir(apk)
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    try:
        extracted = extract_bundle(apk, work)
    except Exception as exc:  # noqa: BLE001 — bad zip must not crash Hub
        step(
            f"Не разобрал контейнер ({type(exc).__name__}: {exc}). "
            "Нужен исходный .xapk с APKPure, не пустой zip.",
            100,
        )
        return report

    package = package or extracted.package or bundle_package_name(apk)
    if not package and extracted.splits:
        package = apk_package_name(extracted.splits[0].path)
    report.package = package
    step(
        f"внутри {len(extracted.splits)} APK"
        + (f", пакет {package}" if package else "")
        + (f", OBB {len(extracted.obb)}" if extracted.obb else ""),
        8,
    )

    used_serial, signed_splits, remaining = _sign_bundle_splits(
        adb, extracted.splits, package, step
    )
    if not signed_splits:
        step("Не подписал сплиты XAPK.", 100)
        return report
    report.signed_apk = next(
        (item.path for item in signed_splits if item.name == "base"), signed_splits[0].path
    )

    if package:
        present = adb.shell(f"pm path {package}", timeout=8)
        if "package:" in merged_output(present):
            adb.shell(f"pm enable --user 0 {package}", timeout=8)

    if len(signed_splits) == 1:
        result, remote_apk = _push_and_pm(adb, signed_splits[0].path, step, package=package)
        remotes = [remote_apk] if remote_apk else []
    else:
        result, remotes = _session_install(adb, signed_splits, step, package=package)
        remote_apk = remotes[-1] if remotes else None
    if not remotes and not _ok_install(result):
        return report

    blob = merged_output(result)
    kept = _keep_working_overlay(adb, report, result, blob, package, step, remote_apk)
    if kept is not None:
        return kept

    if _ok_install(result):
        _install_obb(adb, package, extracted.obb, step)
        report.method = (
            f"pm install {PM_INSTALL_FLAGS}"
            if len(signed_splits) == 1
            else "pm install-create/write/commit"
        )
        for extra in remotes[:-1]:
            adb.shell(f"rm {extra}", timeout=8)
        return _finish_ok(adb, report, remotes[-1] if remotes else None, step)

    if "not auth" in blob.lower() or "-118" in blob.lower():
        for fresh in _next_auth_serials(adb, used_serial, remaining, step):
            used_serial, signed_splits, remaining = _sign_bundle_splits(
                adb, extracted.splits, package, step, serial=fresh
            )
            report.signed_apk = signed_splits[0].path if signed_splits else report.signed_apk
            if len(signed_splits) == 1:
                result, remote_apk = _push_and_pm(
                    adb, signed_splits[0].path, step, package=package
                )
                remotes = [remote_apk] if remote_apk else []
            else:
                result, remotes = _session_install(adb, signed_splits, step, package=package)
            if _ok_install(result):
                _install_obb(adb, package, extracted.obb, step)
                report.method = "pm install-create/write/commit"
                return _finish_ok(adb, report, remotes[-1] if remotes else None, step)
        step(
            "ГУ показала «is not auth, install failed» (код -118) на сплитах XAPK. "
            "Старую панель Hub не снимал.",
            100,
        )
        return report

    log_blob = " ".join(report.log).lower()
    if _is_older_sdk(log_blob):
        _explain_older_sdk(step)
        return report
    if _is_missing_manifest(log_blob):
        _explain_missing_manifest(step)
        return report
    step("pm install сплитов не прошёл. adb root на Feiyu не трогаю — он рвёт USB.", 100)
    return report


def _sign_bundle_splits(
    adb: Adb,
    splits: list[BundleSplit],
    package: str | None,
    step: Progress,
    serial: int | None = None,
) -> tuple[int | None, list[BundleSplit], list[int]]:
    if not splits:
        return serial, [], []
    remaining: list[int] = []
    if serial is None:
        used_serial, signed_first, _method, remaining = _sign_for_hu(
            adb, splits[0].path, package, step
        )
    else:
        used_serial, signed_first, _method = _sign_with_serial(
            adb, splits[0].path, serial, step, retry=True
        )
    store = ensure_keystore(serial=used_serial)
    signed = [
        BundleSplit(path=signed_first, name=splits[0].name, size=signed_first.stat().st_size)
    ]
    for split in splits[1:]:
        path, method = sign_apk_with_method(split.path, keystore=store, adb_binary=adb.binary)
        signed.append(BundleSplit(path=path, name=split.name, size=path.stat().st_size))
        step(f"подписан сплит {split.name} ({method}): {path.name}", 25)
    return used_serial, signed, remaining


def _session_install(
    adb: Adb, splits: list[BundleSplit], step: Progress, package: str | None = None
) -> tuple[CommandResult, list[str]]:
    total = sum(item.size or (item.path.stat().st_size if item.path.exists() else 0) for item in splits)
    step(
        f"Шаг 2/5: сессия pm install-create на {len(splits)} сплитов "
        f"({total} байт). adb install-multiple на Feiyu не вызываю.",
        35,
    )
    create_cmd = f"pm install-create {PM_INSTALL_FLAGS} -S {total}"
    step(f"выполняю {create_cmd}", 40)
    created = adb.shell(create_cmd, timeout=15)
    step(
        f"{create_cmd} code={created.code} stdout={created.stdout.strip()!r} "
        f"stderr={created.stderr.strip()!r}",
        42,
    )
    if adb_target_gone(created):
        return created, []
    session = parse_install_session(merged_output(created))
    if not session:
        step("pm install-create не вернул session id.", 45)
        return CommandResult(False, created.stdout, created.stderr, created.code or 1, []), []

    remotes: list[str] = []
    try:
        for index, split in enumerate(splits):
            remote = f"/data/local/tmp/hub-{session}-{index}.apk"
            step(f"push сплит {split.name} → {remote}", 45)
            pushed = adb.push(split.path, remote, timeout=_transfer_timeout(split.path))
            step(
                f"push code={pushed.code} stdout={pushed.stdout.strip()!r} "
                f"stderr={pushed.stderr.strip()!r}",
                50,
            )
            if adb_target_gone(pushed) or not pushed.ok or "error" in (pushed.stdout + pushed.stderr).lower():
                adb.shell(f"pm install-abandon {session}", timeout=8)
                return pushed, remotes
            remotes.append(remote)
            adb.shell(f"chmod 644 {remote}", timeout=8)
            size = split.size or split.path.stat().st_size
            write_cmd = f"pm install-write -S {size} {session} {split.name} {remote}"
            step(f"выполняю {write_cmd}", 60)
            written = adb.shell(write_cmd, timeout=_pm_timeout(split.path))
            step(
                f"{write_cmd} code={written.code} stdout={written.stdout.strip()!r} "
                f"stderr={written.stderr.strip()!r}",
                65,
            )
            write_blob = merged_output(written).lower()
            if adb_target_gone(written) or "failure" in write_blob or "error" in write_blob:
                adb.shell(f"pm install-abandon {session}", timeout=8)
                return written, remotes
        commit_cmd = f"pm install-commit {session}"
        step(f"выполняю {commit_cmd}", 68)
        commit_timeout = min(180, max(45, 30 + total // (2 * 1024 * 1024)))
        committed = adb.shell(commit_cmd, timeout=commit_timeout)
        step(
            f"{commit_cmd} code={committed.code} stdout={committed.stdout.strip()!r} "
            f"stderr={committed.stderr.strip()!r}",
            70,
        )
        if adb_target_gone(committed):
            return committed, remotes
        if not _ok_install(committed) and (
            committed.code == 124 or "timeout" in (committed.stderr or "").lower()
        ):
            step("pm install-commit не ответил вовремя — проверяю pm path.", 72)
            if _confirm_installed(adb, package, step):
                committed = CommandResult(
                    True, "Success", "confirmed via pm path after timeout", 0, []
                )
                step(f"пакет {package} уже в pm path — установка сплитов прошла.", 74)
        if not _ok_install(committed):
            commit_blob = merged_output(committed).lower()
            if committed.code == 0 and "failure" not in commit_blob and "error" not in commit_blob:
                if not package or _confirm_installed(adb, package, step, attempts=2):
                    committed = CommandResult(True, "Success", "session commit", 0, [])
            if not _ok_install(committed):
                adb.shell(f"pm install-abandon {session}", timeout=8)
        return committed, remotes
    except Exception:
        adb.shell(f"pm install-abandon {session}", timeout=8)
        raise


def _install_obb(adb: Adb, package: str | None, files: list[Path], step: Progress) -> None:
    if not files or not package:
        return
    folder = f"/sdcard/Android/obb/{package}"
    step(f"копирую OBB в {folder}", 80)
    adb.shell(f"mkdir -p {folder}", timeout=8)
    for item in files:
        remote = f"{folder}/{item.name}"
        pushed = adb.push(item, remote, timeout=_transfer_timeout(item, minimum=20))
        step(
            f"obb {item.name} code={pushed.code} stdout={pushed.stdout.strip()!r} "
            f"stderr={pushed.stderr.strip()!r}",
            82,
        )


def merged_output(result: CommandResult) -> str:
    return f"{result.stdout or ''}\n{result.stderr or ''}"


def _pm_path_package_suffix(maybe_pkg: str) -> bool:
    """True when the token after the last '=' is a package id, not an APK path."""
    token = (maybe_pkg or "").strip()
    if not token or "/" in token or " " in token:
        return False
    return "." in token and token[0].isalpha()


def parse_package_paths(text: str) -> dict[str, str]:
    """Parse ``pm list packages -f`` lines: package:/path/base.apk=pkg.name"""
    mapping: dict[str, str] = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line.startswith("package:"):
            continue
        rest = line.split("package:", 1)[-1].strip()
        if "=" not in rest:
            continue
        path, pkg = rest.rsplit("=", 1)
        path, pkg = path.strip(), pkg.strip()
        if pkg and path and _pm_path_package_suffix(pkg):
            mapping[pkg] = path
    return mapping


def parse_pm_path(text: str) -> str:
    """Parse ``pm path`` output. Android 9 paths contain ``==`` hashes — keep them."""
    for line in (text or "").splitlines():
        line = line.strip()
        if not line.startswith("package:"):
            continue
        rest = line.split("package:", 1)[-1].strip()
        if "=" in rest:
            path, maybe_pkg = rest.rsplit("=", 1)
            if _pm_path_package_suffix(maybe_pkg):
                return path.strip()
        return rest
    return ""


def _sign_for_hu(
    adb: Adb,
    apk: Path,
    package: str | None,
    step: Progress,
    *,
    ignore_cache: bool = False,
) -> tuple[int, Path, str, list[int]]:
    # Overlay leftovers are auth apps. Cloning their serial (not the cert)
    # and generating a new keystore makes pm install -r fail with
    # UPDATE_INCOMPATIBLE, then pm uninstall pops 提示 not allow delete.
    # Sign from an already-installed third-party APK on THIS head unit.
    installed_serial = None
    if package and package not in OVERLAY_PACKAGES:
        installed_serial = discover_package_signer_serial(adb, package, step)
    device = getattr(adb, "serial", None)
    cached = None if ignore_cache else load_cached_hu_serial(device)
    # Cookbook is the default guess; russified images already rejected it (-118).
    # Do not skip boot-ext/Vecentek because a previous run cached the guide serial.
    if cached == CHANGAN_SERIAL:
        cached = None
    candidates: list[int] = []
    if installed_serial:
        step(
            f"Уже стоящий {package} serial=0x{installed_serial:x} — подписываю тем же ключом, "
            "чтобы pm install -r прошёл.",
            8,
        )
        hu_serial = installed_serial
        candidates = [installed_serial]
    elif cached:
        step(
            f"сохранённый serial ГУ {device or '?'} 0x{cached:x} — им и подписываю, "
            "без повторного скачивания Яндекса/whitelist.",
            8,
        )
        hu_serial = cached
        candidates = [cached]
    else:
        discovered = discover_hu_signer_candidates(adb, step)
        for item in discovered:
            if item not in candidates:
                candidates.append(item)
        if CHANGAN_SERIAL in candidates:
            candidates = [item for item in candidates if item != CHANGAN_SERIAL] + [CHANGAN_SERIAL]
        hu_serial = candidates[0] if candidates else None
    serial = hu_serial or CHANGAN_SERIAL
    if hu_serial and hu_serial != CHANGAN_SERIAL:
        step(
            f"На установленных приложениях ГУ serial=0x{hu_serial:x} "
            f"(не cookbook 0x{CHANGAN_SERIAL:x}). Подписываю как на ГУ.",
            8,
        )
    elif hu_serial:
        step(f"На ГУ те же приложения с serial=0x{hu_serial:x} — совпадает с гайдом.", 8)
    else:
        step(
            f"Не снял serial с приложений ГУ, беру гайд 0x{CHANGAN_SERIAL:x}.",
            8,
        )
    signed_serial, signed, method = _sign_with_serial(adb, apk, serial, step)
    remaining = [item for item in candidates if item != signed_serial]
    return signed_serial, signed, method, remaining


def _sign_with_serial(
    adb: Adb, apk: Path, serial: int, step: Progress, *, retry: bool = False
) -> tuple[int, Path, str]:
    device = getattr(adb, "serial", None)
    save_cached_hu_serial(serial, device)
    store = ensure_keystore(serial=serial)
    if retry:
        step(f"Повторная подпись serial=0x{serial:x}.", 82)
    else:
        step(
            f"Шаг 1/5: подпись APK под Changan (v1+v2, serial 0x{serial:x})…",
            10,
        )
    signed, method = sign_apk_with_method(apk, keystore=store, adb_binary=adb.binary)
    step(f"Подписано ({method}): {signed}", 84 if retry else 25)
    for seen in apk_certificate_serials(signed):
        step(f"в подписанном APK serial=0x{seen:x}", 84 if retry else 26)
    return serial, signed, method


MAX_SERIAL_RETRIES = 8


def _next_auth_serials(
    adb: Adb,
    used_serial: int | None,
    remaining: list[int],
    step: Progress,
) -> list[int]:
    ordered: list[int] = []
    for item in remaining:
        if item != used_serial and item not in ordered:
            ordered.append(item)
    if ordered:
        step(
            "Белый список этой ГУ другой. Пробую следующие serial с этой машины, "
            "без повторного скачивания Vecentek.",
            72,
        )
        return ordered[:MAX_SERIAL_RETRIES]
    step(
        "Белый список этой ГУ другой. Снимаю serial из boot-ext.vdex/Vecentek "
        "и сторонних APK этой машины, без кэша.",
        72,
    )
    device = getattr(adb, "serial", None)
    if device:
        _clear_cached_hu_serial(device)
    for fresh in discover_hu_signer_candidates(adb, step):
        if fresh != used_serial and fresh not in ordered:
            ordered.append(fresh)
    if not ordered:
        step(
            "Другой serial на этой ГУ не нашёл — гайд Feiyu отвергла, сторонних APK нет. "
            "Смотрите VecentekApp.apk, boot-ext.vdex, whitelist.json и publicKey.cert в data\\probe.",
            80,
        )
    return ordered[:MAX_SERIAL_RETRIES]


def _push_and_pm(
    adb: Adb, signed: Path, step: Progress, start_pct: int = 35, package: str | None = None
) -> tuple[CommandResult, str | None]:
    step("Шаг 2/5: копирую APK на ГУ (push). adb install пропускаю — на Feiyu он зависает.", start_pct)
    remote_apk = None
    remote_name = _remote_apk_basename(signed, package)
    push_timeout = _transfer_timeout(signed)
    for folder in REMOTE_CANDIDATES:
        remote = f"{folder}/{remote_name}"
        step(f"push → {remote}", min(start_pct + 5, 45))
        pushed = adb.push(signed, remote, timeout=push_timeout)
        step(
            f"push code={pushed.code} stdout={pushed.stdout.strip()!r} stderr={pushed.stderr.strip()!r}",
            min(start_pct + 10, 45),
        )
        if adb_target_gone(pushed):
            step("ГУ отвалилась от USB. Верните ADB-режим (USB切换 → ADB模式).", 45)
            return CommandResult(False, pushed.stdout, pushed.stderr, pushed.code, []), None
        if pushed.ok and "error" not in (pushed.stdout + pushed.stderr).lower() and pushed.code != 124:
            remote_apk = remote
            break
    if not remote_apk:
        step("Не удалось скопировать APK. Проверьте ADB-режим (USB切换 → ADB模式).", 45)
        return CommandResult(False, "", "push failed", 1, []), None
    step("Шаг 3/5: pm install на ГУ…", 60)
    cmd = f"pm install {PM_INSTALL_FLAGS} {remote_apk}"
    step(f"выполняю {cmd}", 65)
    result = adb.shell(cmd, timeout=_pm_timeout(signed))
    step(
        f"{cmd} code={result.code} stdout={result.stdout.strip()!r} stderr={result.stderr.strip()!r}",
        70,
    )
    if adb_target_gone(result):
        return result, remote_apk
    if not _ok_install(result) and (
        result.code == 124 or "timeout" in (result.stderr or "").lower()
    ):
        step(
            "pm install не ответил вовремя — проверяю, не встал ли пакет сам "
            "(большие APK на Feiyu так делают).",
            72,
        )
        if _confirm_installed(adb, package, step):
            result = CommandResult(True, "Success", "confirmed via pm path after timeout", 0, [])
            step(f"пакет {package} уже в pm path — установка прошла.", 74)
    return result, remote_apk


def discover_package_signer_serial(
    adb: Adb, package: str, step: Progress | None = None, remote: str | None = None
) -> int | None:
    """Read the signing serial of a package already on the head unit."""
    if package in OVERLAY_PACKAGES:
        return None
    if not remote:
        result = adb.shell(f"pm path {package}", timeout=10)
        remote = parse_pm_path(merged_output(result))
    if not remote:
        remote = _code_path_from_dumpsys(adb, package)
    if not remote:
        return None
    size = _remote_size(adb, remote)
    if size < 0:
        return None
    if size > MAX_SIDELOAD_PROBE:
        if step:
            step(
                f"не качаю {package} ({size} байт) ради serial — слишком большой APK.",
                8,
            )
        return None
    return _serial_from_remote_apk(adb, package, remote, step)


def _remote_size(adb: Adb, path: str) -> int:
    quoted = path.replace("'", "'\\''")
    result = adb.shell(f"stat -c %s '{quoted}'", timeout=8)
    if adb_target_gone(result):
        return -1
    for token in merged_output(result).replace(",", " ").split():
        if token.isdigit() and int(token) > 32:
            return int(token)
    result = adb.shell(f"ls -l '{quoted}'", timeout=8)
    if adb_target_gone(result):
        return -1
    for token in merged_output(result).split():
        if token.isdigit() and int(token) > 32:
            return int(token)
    return 0


def _serial_from_remote_apk(
    adb: Adb, package: str, remote: str, step: Progress | None = None
) -> int | None:
    from hub.paths import app_data

    size = _remote_size(adb, remote)
    if size < 0:
        return None
    if size > MAX_SIDELOAD_PROBE:
        if step:
            step(
                f"не качаю {package} ({size} байт) ради serial — слишком большой APK.",
                8,
            )
        return None
    probe_dir = app_data() / "probe"
    probe_dir.mkdir(parents=True, exist_ok=True)
    local = probe_dir / f"{package.split('.')[-1]}.apk"
    pulled = adb.raw(["pull", remote, str(local)], timeout=40)
    if adb_target_gone(pulled):
        return None
    if not pulled.ok or not local.exists() or local.stat().st_size < 64:
        return None
    try:
        serials = apk_certificate_serials(local)
    except Exception:
        serials = []
    try:
        local.unlink()
    except OSError:
        pass
    if not serials:
        return None
    serial = serials[0]
    if step:
        step(f"на ГУ {package} serial=0x{serial:x}", 8)
    return serial


def _code_path_from_dumpsys(adb: Adb, package: str) -> str:
    result = adb.shell(f"dumpsys package {package}", timeout=12)
    code_path = ""
    for line in merged_output(result).splitlines():
        stripped = line.strip()
        if stripped.startswith("codePath="):
            code_path = stripped.split("=", 1)[1].strip()
        elif stripped.startswith("resourcePath=") and not code_path:
            code_path = stripped.split("=", 1)[1].strip()
    if not code_path:
        return ""
    if code_path.endswith(".apk"):
        return code_path
    return code_path.rstrip("/") + "/base.apk"


def _all_package_paths(adb: Adb, step: Progress | None = None) -> dict[str, str]:
    result = adb.shell("pm list packages -f", timeout=25)
    if adb_target_gone(result):
        if step:
            step("ГУ нет в ADB (device not found).", 6)
        return {}
    mapping = parse_package_paths(merged_output(result))
    extra = adb.shell("pm list packages -3 -f", timeout=15)
    if adb_target_gone(extra):
        if step:
            step("ГУ отвалилась при pm list -3.", 6)
        return mapping
    mapping.update(parse_package_paths(merged_output(extra)))
    if step:
        step(f"пакетов на ГУ: {len(mapping)}", 6)
    return mapping


def _is_sideload_path(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()
    return any(
        token in normalized
        for token in ("/data/app", "/data/priv-app", "/oem/", "/product/app", "/mnt/expand")
    )


def _third_party_paths(adb: Adb, step: Progress | None = None) -> dict[str, str]:
    mapping = _all_package_paths(adb, step)
    data_app = {
        pkg: path
        for pkg, path in mapping.items()
        if _is_sideload_path(path) and pkg not in OVERLAY_PACKAGES
    }
    if step and data_app:
        shown = ", ".join(sorted(data_app)[:12])
        extra = "…" if len(data_app) > 12 else ""
        step(f"сторонние APK на этой ГУ: {shown}{extra}", 7)
    elif step:
        step("сторонних APK нет — сниму serial из Vecentek/services.jar.", 7)
    return data_app


def _candidate_packages(paths: dict[str, str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for pkg in PROBE_PACKAGES:
        if pkg in paths and pkg not in seen:
            ordered.append(pkg)
            seen.add(pkg)
    for pkg in sorted(paths):
        if pkg not in seen:
            ordered.append(pkg)
            seen.add(pkg)
    return ordered


def _plausible_serial(value: int) -> bool:
    if value <= 0xFFFFFFFF or value >= (1 << 64):
        return False
    if value in (
        0xFFFFFFFFFFFFFFFF,
        0x7FFFFFFFFFFFFFFF,
        *_JUNK_SERIALS,
    ):
        return False
    raw = value.to_bytes(8, "little")
    if raw.count(0) >= 2:
        return False
    ascii_n = sum(1 for byte in raw if 0x20 <= byte < 0x7F)
    if ascii_n >= 5:
        return False
    if all(0x20 <= byte < 0x7F for byte in raw):
        return False
    if all(0x20 <= byte < 0x7F for byte in value.to_bytes(8, "big")):
        return False
    if len(set(raw)) < 6:
        return False
    pairs = tuple(raw[i : i + 2] for i in range(0, 8, 2))
    if len(set(pairs)) <= 1:
        return False
    if (value & 0xFFFF) == 1:
        return False
    bits = bin(value).count("1")
    if bits < 16 or bits > 48:
        return False
    if (value & 0x0000FFFF0000FFFF) == 0:
        return False
    if (value & 0xFFFF0000FFFF0000) == 0:
        return False
    return True


def _plausible_opcode_serial(value: int) -> bool:
    """Stricter than hex strings: DEX debug ids often end in 0001 and contain 0x00."""
    if not _plausible_serial(value):
        return False
    raw = value.to_bytes(8, "little")
    if raw.count(0):
        return False
    if sum(1 for byte in raw if byte < 0x20) >= 3:
        return False
    return True


def _dex_blobs(data: bytes) -> list[bytes]:
    """DEX and compact DEX (cdex) inside APK/VDEX. boot-ext.vdex uses both."""
    blobs: list[bytes] = []
    for magic in (b"dex\n", b"cdex"):
        start = 0
        while True:
            index = data.find(magic, start)
            if index < 0:
                break
            file_size = 0
            if index + 36 <= len(data):
                file_size = int.from_bytes(data[index + 32 : index + 36], "little")
            if 64 <= file_size <= len(data) - index:
                blobs.append(data[index : index + file_size])
                start = index + max(file_size, 4)
            else:
                start = index + 4
    return blobs


def _dex_has_auth(data: bytes) -> bool:
    low = data.lower()
    return any(needle.lower() in low for needle in _AUTH_NEEDLES) or b"certificatemanager" in low


def dex_const_wide_literals(data: bytes) -> list[int]:
    """Dalvik ``const-wide`` (op 0x18) 64-bit literals from a DEX blob."""
    found: list[int] = []
    for blob in _dex_blobs(data):
        offset = 0
        while offset + 10 <= len(blob):
            if blob[offset] == 0x18:
                value = int.from_bytes(blob[offset + 2 : offset + 10], "little")
                if _plausible_opcode_serial(value) and value not in found:
                    found.append(value)
                offset += 10
                continue
            offset += 2
    return found


def dex_array_data_longs(data: bytes) -> list[int]:
    """DEX ``array-data`` payloads with 8-byte elements (long[] whitelist)."""
    found: list[int] = []
    for blob in _dex_blobs(data):
        offset = 0
        while offset + 16 <= len(blob):
            if int.from_bytes(blob[offset : offset + 2], "little") != 0x0300:
                offset += 2
                continue
            width = int.from_bytes(blob[offset + 2 : offset + 4], "little")
            size = int.from_bytes(blob[offset + 4 : offset + 8], "little")
            start = offset + 8
            if width == 1 and size == 8:
                end = start + 8
                if end > len(blob):
                    offset += 2
                    continue
                for value in (
                    int.from_bytes(blob[start:end], "big"),
                    int.from_bytes(blob[start:end], "little"),
                ):
                    if _plausible_opcode_serial(value) and value not in found:
                        found.append(value)
                offset = end if end % 2 == 0 else end + 1
                continue
            if width != 8 or size < 1 or size > 64:
                offset += 2
                continue
            end = start + size * 8
            if end > len(blob):
                offset += 2
                continue
            for index in range(size):
                value = int.from_bytes(blob[start + index * 8 : start + (index + 1) * 8], "little")
                if _plausible_opcode_serial(value) and value not in found:
                    found.append(value)
            offset = end if end % 2 == 0 else end + 1
    return found


def extract_hex_serials(data: bytes) -> list[int]:
    """Serials written as hex / cookbook bytes, not opcode false positives."""
    found: list[int] = []

    def add(value: int) -> None:
        if not _plausible_serial(value) or value in found:
            return
        found.append(value)

    le = CHANGAN_SERIAL.to_bytes(8, "little")
    be = CHANGAN_SERIAL.to_bytes(8, "big")
    if le in data or be in data:
        add(CHANGAN_SERIAL)
    hex_token = format(CHANGAN_SERIAL, "x").encode("ascii")
    if hex_token in data or hex_token.upper() in data:
        add(CHANGAN_SERIAL)
    wide = format(CHANGAN_SERIAL, "x").encode("utf-16-le")
    if wide in data or format(CHANGAN_SERIAL, "X").encode("utf-16-le") in data:
        add(CHANGAN_SERIAL)
    for match in _HEX16.finditer(data):
        add(int(match.group(1), 16))
    for match in re.finditer(rb"0x([0-9a-fA-F]{8,16})", data):
        add(int(match.group(1), 16))
    return found


def extract_opcode_serials(data: bytes) -> list[int]:
    found: list[int] = []
    for value in dex_array_data_longs(data):
        if value not in found:
            found.append(value)
    for value in dex_const_wide_literals(data):
        if value not in found:
            found.append(value)
    return found


def dex_const_wide_raw(data: bytes, limit: int = 16) -> list[int]:
    """Unfiltered const-wide >32bit, for the journal when filters empty the list."""
    found: list[int] = []
    for blob in _dex_blobs(data):
        offset = 0
        while offset + 10 <= len(blob) and len(found) < limit:
            if blob[offset] == 0x18:
                value = int.from_bytes(blob[offset + 2 : offset + 10], "little")
                if value > 0xFFFFFFFF:
                    found.append(value)
                offset += 10
                continue
            offset += 2
    return found


def _is_whitelist_blob(pkg: str, remote: str) -> bool:
    blob = f"{pkg} {remote}".lower()
    return any(hint in blob for hint in WHITELIST_HINTS)


def _take_opcodes(pkg: str, remote: str, data: bytes) -> bool:
    blob = f"{pkg} {remote}".lower()
    if "vecentek" in blob:
        return False
    if any(hint in blob for hint in ("boot-ext", "ext.jar", "certificatemanager")):
        return True
    return _dex_has_auth(data)


def _probe_local(probe_dir: Path, remote: str) -> Path:
    name = remote.strip("/").replace("/", "_") or "probe.bin"
    return probe_dir / name[:180]


def _min_probe_size(remote: str) -> int:
    lower = remote.lower()
    if lower.endswith((".json", ".cert", ".crt", ".cer", ".pem", ".txt", ".xml")):
        return 8
    return 64


def _load_x509(data: bytes):
    from cryptography import x509

    if b"BEGIN CERTIFICATE" in data:
        return x509.load_pem_x509_certificate(data)
    return x509.load_der_x509_certificate(data)


def cert_file_serials(path: Path) -> list[int]:
    try:
        data = path.read_bytes()
    except OSError:
        return []
    try:
        cert = _load_x509(data)
    except Exception:
        return []
    serial = cert.serial_number
    return [serial] if serial > 0 else []


def serials_from_whitelist_json(data: bytes) -> list[int]:
    found: list[int] = list(extract_hex_serials(data))
    try:
        obj = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return found

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, str):
            for item in extract_hex_serials(node.encode("ascii", "replace")):
                if item not in found:
                    found.append(item)
        elif isinstance(node, int) and node > 0 and node not in found:
            found.append(node)

    walk(obj)
    return found


def _auth_logcat_serials(adb: Adb, step: Progress | None = None) -> list[int]:
    dumped = adb.shell("logcat -d -t 400 -s Leosin-CertificateM:D VecentekPMS:D", timeout=12)
    blob = f"{dumped.stdout or ''}\n{dumped.stderr or ''}"
    lines = [
        line.strip()
        for line in blob.splitlines()
        if line.strip() and "password" not in line.lower()
    ]
    keep = [
        line
        for line in lines
        if any(
            token in line.lower()
            for token in ("cert", "auth", "white", "serial", "leosin", "vecentek", "check")
        )
    ]
    shown = keep[-16:] or lines[-8:]
    if step and shown:
        step("logcat auth: " + " | ".join(shown)[:1500], 74)
    return extract_hex_serials(blob.encode("utf-8", "replace"))


def extract_embedded_serials(data: bytes) -> list[int]:
    """Whitelist serials baked into Vecentek/services, not the APK signing cert."""
    found: list[int] = []
    for value in extract_hex_serials(data) + extract_opcode_serials(data):
        if value not in found:
            found.append(value)
    return found


def _interesting_strings(data: bytes, limit: int = 16) -> list[str]:
    found: list[str] = []
    for raw in re.findall(rb"[\x20-\x7e]{6,80}", data):
        low = raw.lower()
        if any(needle.lower() in low for needle in _AUTH_NEEDLES) or any(
            token in low
            for token in (
                b"serial",
                b"cert",
                b"vecentek",
                b"whitelist",
                b"install",
                b"fail",
                b"leosin",
                b"back_up",
                b"allow_uninstall",
                b"publickey",
            )
        ):
            text = raw.decode("ascii", "replace")
            if text not in found:
                found.append(text)
            if len(found) >= limit:
                break
    return found


def embedded_serial_groups(apk: Path) -> tuple[list[int], list[int]]:
    high: list[int] = []
    low: list[int] = []

    def merge(target: list[int], values: list[int]) -> None:
        for value in values:
            if value not in target and _plausible_serial(value):
                target.append(value)

    try:
        whole = apk.read_bytes()
    except OSError:
        return high, low
    try:
        with zipfile.ZipFile(apk) as zf:
            merge(high, extract_hex_serials(whole))
            for name in zf.namelist():
                lower = name.lower()
                if lower.endswith((".xml", ".txt", ".json")):
                    merge(high, extract_hex_serials(zf.read(name)))
                    continue
                if not lower.endswith(
                    (".dex", ".jar", ".vdex", ".odex", ".cer", ".crt", ".der", ".pem", ".cert")
                ):
                    continue
                blob = zf.read(name)
                merge(high, extract_hex_serials(blob))
                if lower.endswith((".dex", ".vdex", ".odex", ".jar")):
                    merge(low, extract_opcode_serials(blob))
                if lower.endswith((".cer", ".crt", ".der", ".pem", ".cert")):
                    try:
                        from cryptography import x509

                        cert = (
                            x509.load_pem_x509_certificate(blob)
                            if b"BEGIN CERTIFICATE" in blob
                            else x509.load_der_x509_certificate(blob)
                        )
                        merge(high, [cert.serial_number])
                    except Exception:
                        pass
            return high, low
    except zipfile.BadZipFile:
        pass
    merge(high, extract_hex_serials(whole))
    merge(low, extract_opcode_serials(whole))
    return high, low


def embedded_serials_in_apk(apk: Path) -> list[int]:
    high, low = embedded_serial_groups(apk)
    found = list(high)
    for value in low:
        if value not in found:
            found.append(value)
    return found


def _manager_targets(mapping: dict[str, str], extra_paths: list[str] | None = None) -> list[tuple[str, str]]:
    targets: list[tuple[str, str]] = []
    seen: set[str] = set()
    for pkg, path in mapping.items():
        blob = f"{pkg} {path}".lower()
        if any(hint in blob for hint in MANAGER_HINTS):
            if path not in seen:
                targets.append((pkg, path))
                seen.add(path)
    for path in list(MANAGER_PATHS) + list(WHITELIST_FILE_PATHS) + list(extra_paths or []):
        if path not in seen:
            name = path.rsplit("/", 1)[-1]
            targets.append((name, path))
            seen.add(path)
    return targets


def _serials_from_manager(
    adb: Adb, mapping: dict[str, str], step: Progress | None = None
) -> tuple[list[int], list[int]]:
    high: list[int] = []
    low: list[int] = []
    extras = _whitelist_extra_paths(adb, step)
    for pkg, remote in _manager_targets(mapping, extras):
        timeout = 90 if remote.endswith((".jar", ".vdex", ".odex")) else 40
        from hub.paths import app_data

        probe_dir = app_data() / "probe"
        probe_dir.mkdir(parents=True, exist_ok=True)
        local = _probe_local(probe_dir, remote)
        reused = local.exists() and local.stat().st_size >= _min_probe_size(remote)
        if step:
            if reused:
                step(f"уже скачан: {local.name} ({local.stat().st_size} байт)", 7)
            else:
                step(f"читаю белый список: {remote}", 7)
        if not reused:
            pulled = adb.raw(["pull", remote, str(local)], timeout=timeout)
            if adb_target_gone(pulled):
                if step:
                    step("ГУ отключилась — белый список дальше не читаю.", 7)
                break
            if not pulled.ok or not local.exists() or local.stat().st_size < _min_probe_size(remote):
                if step:
                    step(
                        f"не скачал {remote} code={pulled.code} err={pulled.stderr.strip()[:120]!r}",
                        7,
                    )
                continue
        try:
            group_high, group_low = embedded_serial_groups(local)
        except Exception as exc:  # noqa: BLE001 — one bad jar must not abort install
            if step:
                step(f"{pkg}: не разобрал ({type(exc).__name__}: {exc})", 8)
            continue
        signing: list[int] = []
        lower_remote = remote.lower()
        try:
            if lower_remote.endswith((".apk", ".jar")) or zipfile.is_zipfile(local):
                signing = [item for item in apk_certificate_serials(local) if item > 0]
        except Exception:
            signing = []
        if lower_remote.endswith((".cert", ".crt", ".cer", ".der", ".pem")):
            for item in cert_file_serials(local):
                if item not in signing:
                    signing.append(item)
        if lower_remote.endswith(".json"):
            try:
                text = local.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            if step and text:
                step(f"{pkg} json: {' '.join(text.split())[:1500]}", 8)
            for item in serials_from_whitelist_json(local.read_bytes()):
                if item not in group_high:
                    group_high.append(item)
        if step:
            if signing:
                step(
                    f"{pkg} подпись APK/cert: " + ", ".join(f"0x{item:x}" for item in signing[:6]),
                    8,
                )
            shown = ", ".join(f"0x{item:x}" for item in (group_high + group_low)[:6]) or "пусто"
            step(f"{pkg}: вшитые serial {shown}", 8)
            try:
                with zipfile.ZipFile(local) as zf:
                    names = zf.namelist()
                    dex_names = [
                        name
                        for name in names
                        if name.lower().endswith((".dex", ".xml", ".json", ".cert", ".rsa"))
                    ]
                    step(f"{pkg} содержимое: " + ", ".join((dex_names or names)[:12]), 8)
                    inner_hints: list[str] = []
                    for name in names:
                        if name.lower().endswith((".dex", ".xml", ".json")):
                            inner_hints.extend(_interesting_strings(zf.read(name)))
                    if inner_hints:
                        step(f"{pkg} строки: " + " | ".join(inner_hints[:8]), 8)
            except zipfile.BadZipFile:
                hints = _interesting_strings(local.read_bytes())
                if hints:
                    step(f"{pkg} строки: " + " | ".join(hints[:8]), 8)
            if local.suffix.lower() == ".xml":
                try:
                    text = local.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    text = ""
                if text:
                    step(f"{pkg} xml: {' '.join(text.split())[:1200]}", 8)
        try:
            take_opcodes = _take_opcodes(pkg, remote, local.read_bytes())
        except OSError:
            take_opcodes = False
        for item in signing + group_high:
            if item not in high:
                high.append(item)
        if take_opcodes:
            if step and group_low:
                step(
                    f"{pkg} const-wide: " + ", ".join(f"0x{item:x}" for item in group_low[:12]),
                    8,
                )
            elif step:
                raw_wide = dex_const_wide_raw(local.read_bytes())
                if raw_wide:
                    step(
                        f"{pkg} const-wide сырые (фильтр отбросил): "
                        + ", ".join(f"0x{item:x}" for item in raw_wide[:12]),
                        8,
                    )
            for item in group_low:
                if item not in low and item not in high:
                    low.append(item)
        elif step and group_low:
            step(f"{pkg}: opcode serial из {pkg} не беру.", 8)
        # Keep probe copies for the next log. Do not unlink.
    return high, low


def discover_hu_signer_candidates(adb: Adb, step: Progress | None = None) -> list[int]:
    """Ordered serials to try on this HU: sideloaded APKs, then Vecentek, then cookbook."""
    if step:
        step("Снимаю serial со сторонних приложений и Vecentek этой ГУ.", 6)
    mapping = _all_package_paths(adb, step)
    if not mapping:
        ping = adb.shell("getprop ro.product.model", timeout=8)
        if adb_target_gone(ping):
            if step:
                step("ГУ отвалилась от USB. Верните ADB-режим, не ставьте APK вхолостую.", 7)
            return []
    sideload = {
        pkg: path
        for pkg, path in mapping.items()
        if _is_sideload_path(path) and pkg not in OVERLAY_PACKAGES
    }
    if step and sideload:
        shown = ", ".join(sorted(sideload)[:12])
        extra = "…" if len(sideload) > 12 else ""
        step(f"сторонние APK на этой ГУ: {shown}{extra}", 7)
    elif step:
        step("сторонних APK нет (русификация в /system). Читаю подпись Vecentek и whitelist.json.", 7)
        ident = adb.shell("getprop ro.build.display.id", timeout=8)
        build = (ident.stdout or "").strip().splitlines()
        build_id = next((line.strip() for line in reversed(build) if line.strip() and "password" not in line.lower()), "")
        if build_id:
            step(f"прошивка: {build_id}", 7)

    third: list[int] = []
    for pkg in _candidate_packages(sideload):
        serial = _serial_from_remote_apk(adb, pkg, sideload[pkg], step)
        if serial and serial not in third:
            third.append(serial)
        if len(third) >= 2:
            break
    if not mapping:
        for pkg in PROBE_PACKAGES:
            serial = discover_package_signer_serial(adb, pkg, step)
            if serial and serial not in third:
                third.append(serial)
                break
    if third:
        if step:
            step("кандидаты serial: " + ", ".join(f"0x{item:x}" for item in third[:6]), 8)
        return third

    high, low = _serials_from_manager(adb, mapping, step)
    ordered: list[int] = []
    for item in third + high + low[:8]:
        if item != CHANGAN_SERIAL and item not in ordered:
            ordered.append(item)
    ordered.append(CHANGAN_SERIAL)
    if step and ordered:
        step("кандидаты serial: " + ", ".join(f"0x{item:x}" for item in ordered[:8]), 8)
    return ordered


def _ls_names(result: CommandResult) -> list[str]:
    names: list[str] = []
    for token in (result.stdout or "").replace("\r", "\n").split():
        low = token.lower().strip(":,")
        if low in {"please", "input", "verify", "password", "success", "success!"}:
            continue
        if "password" in low:
            continue
        names.append(token)
    return names


def _whitelist_extra_paths(adb: Adb, step: Progress | None = None) -> list[str]:
    folders = (
        ("/system/app/VecentekApp", True),
        ("/system/app/VecentekApp/oat/arm64", True),
        ("/system/framework", False),
        ("/system/framework/arm64", False),
        ("/back_up/allow_uninstall", True),
        ("/system/back_up/allow_uninstall", True),
        ("/data/back_up/allow_uninstall", True),
        ("/sdcard/back_up/allow_uninstall", True),
        ("/storage/emulated/0/back_up/allow_uninstall", True),
        ("/data/deCOREIDPS", True),
    )
    suffixes = (".vdex", ".apk", ".jar", ".json", ".cert", ".crt", ".pem", ".der", ".txt")
    hints = WHITELIST_HINTS
    found: list[str] = []
    for folder, take_all in folders:
        listed = adb.shell(f"ls {folder}", timeout=8)
        if adb_target_gone(listed):
            if step:
                step("ГУ отключилась — whitelist не читаю.", 7)
            return found
        names = _ls_names(listed)
        if step and names and "No such" not in (listed.stdout or "") and "No such" not in (listed.stderr or ""):
            step(f"ls {folder}: " + " ".join(names[:16]), 7)
        for name in names:
            lower = name.lower()
            if not lower.endswith(suffixes):
                continue
            if not take_all and not any(hint in lower for hint in hints):
                continue
            path = f"{folder}/{name}"
            if path not in MANAGER_PATHS and path not in WHITELIST_FILE_PATHS and path not in found:
                found.append(path)
    return found[:16]


def discover_hu_signer_serial(adb: Adb, step: Progress | None = None) -> int | None:
    """Read signing serials from third-party apps or Vecentek on this head unit."""
    candidates = discover_hu_signer_candidates(adb, step)
    return candidates[0] if candidates else None


def apk_package_name(apk: Path) -> str | None:
    """Best-effort package id from filename / catalog / binary manifest."""
    from hub.catalog import CATALOG

    if is_apk_bundle(apk):
        return bundle_package_name(apk)

    stem = apk.name.lower()
    if any(token in stem for token in ("quickbar", "quickdock", "quicklane", "quickkeep", "quickrise")):
        return "com.changanhub.quickrise"
    if any(token in stem for token in ("player", "lamoreplayer", "playrise")):
        return "com.changanhub.playrise"
    if any(token in stem for token in ("aichat", "ai-chat", "lamorechat", "chatrise")):
        return "com.changanhub.chatrise"
    raw = b""
    try:
        raw = zipfile.ZipFile(apk).read("AndroidManifest.xml")
    except Exception:
        pass
    for item in CATALOG:
        needle = item.package.encode("ascii", "ignore")
        if needle and (needle in raw or item.package.lower() in stem):
            return item.package
        wide = item.package.encode("utf-16-le")
        if wide and wide in raw:
            return item.package
    cleaned = apk.stem
    while cleaned.lower().endswith("-changan"):
        cleaned = cleaned[: -len("-changan")]
    if re.fullmatch(r"[A-Za-z][\w]*(?:\.[A-Za-z][\w]*){2,}", cleaned) and not re.search(
        r"\d{3,}", cleaned
    ):
        return cleaned
    return _package_from_manifest(raw)


def _package_from_manifest(raw: bytes) -> str | None:
    if not raw:
        return None
    text = raw.decode("utf-16-le", errors="ignore")
    found = re.findall(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*){2,}", text)
    skip = (
        "android.permission",
        "android.intent",
        "android.hardware",
        "android.os",
        "com.android.internal",
    )
    for item in found:
        low = item.lower()
        if any(low.startswith(prefix) for prefix in skip):
            continue
        if "permission" in low or "intent" in low or "hardware" in low:
            continue
        return item
    return None


def uninstall_package(adb: Adb, package: str, step: Progress | None = None) -> bool:
    """Feiyu refuses to delete whitelist-signed apps (提示 not allow delete).

    Do not call ``pm uninstall`` — it only shows that dialog and times out.
    Overlay packages are disabled instead; other packages are left in place.
    """

    def note(message: str, percent: int = 58) -> None:
        if step:
            step(message, percent)

    if package in OVERLAY_PACKAGES:
        note(
            f"{package} — auth-приложение, Feiyu не удаляет (提示 not allow delete). "
            "Отключаю, не длинный uninstall.",
        )
        adb.shell(f"am force-stop {package}", timeout=8)
        adb.shell(f"appops set {package} SYSTEM_ALERT_WINDOW ignore", timeout=8)
        adb.shell(f"pm disable-user --user 0 {package}", timeout=8)
        return False
    if package in KEEP_EXISTING_PACKAGES:
        note(
            f"не вызываю pm uninstall для {package} — на Feiyu это 提示 not allow delete. "
            "Плеер и чат не отключаю."
        )
        return False
    note(f"не вызываю pm uninstall для {package} — на Feiyu это 提示 not allow delete")
    return False


def _package_from_pm_error(text: str) -> str | None:
    match = _INCOMPATIBLE_PKG.search(text)
    return match.group(1) if match else None


def _serial_cache_dir() -> Path:
    from hub.paths import app_data

    path = app_data() / "certs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_device(device: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in device)[:80]


def _serial_cache_path(device: str | None = None) -> Path:
    folder = _serial_cache_dir()
    if device:
        return folder / f"hu_serial_{_safe_device(device)}.txt"
    return folder / "hu_serial.txt"


def load_cached_hu_serial(device: str | None = None) -> int | None:
    """Per-device cache only. A global file from another car caused -118 on rus HUs."""
    if not device:
        return None
    path = _serial_cache_path(device)
    if not path.exists():
        return None
    try:
        value = int(path.read_text(encoding="utf-8").strip(), 0)
    except (OSError, ValueError):
        return None
    if value <= 0:
        return None
    if not _plausible_serial(value):
        try:
            path.unlink()
        except OSError:
            pass
        return None
    return value


def save_cached_hu_serial(serial: int, device: str | None = None) -> None:
    if not device:
        return
    path = _serial_cache_path(device)
    path.write_text(hex(serial), encoding="utf-8")


def _clear_cached_hu_serial(device: str | None = None) -> None:
    if not device:
        return
    path = _serial_cache_path(device)
    try:
        path.unlink()
    except OSError:
        pass
