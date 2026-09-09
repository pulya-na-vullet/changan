"""Install APKs onto a Changan head unit, bypassing the missing vendor cert."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from hub.adb import Adb, CommandResult
from hub.signer import CHANGAN_SERIAL, apk_certificate_serials, ensure_keystore, sign_apk_with_method

REMOTE_CANDIDATES = (
    "/data/local/tmp",
    "/sdcard/Download",
    "/storage/emulated/0/Download",
    "/sdcard",
    "/storage/emulated/0",
)

# Already-installed third-party apps on this HU — their signing serial is the
# real whitelist, which may differ from the CS75PLUS cookbook value.
PROBE_PACKAGES = (
    "org.schabi.newpipe",
    "net.easyconn",
    "gb.xxy.hr",
    "ru.hackchan.launcher",
    "ru.hackchan.settings",
    "air.StrelkaHUDFREE",
    "ru.yandex.yandexnavi",
    "com.yandex.browser.lite",
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
    if "failure" in blob or "error" in blob or "not auth" in blob:
        return False
    if result.code == 124:
        return False
    if "success" in blob:
        return True
    if result.ok and result.stdout.strip():
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
        hu_serial = discover_hu_signer_serial(adb, step)
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
        store = ensure_keystore(serial=serial)
        step(
            f"Шаг 1/5: подпись APK под Changan (v1+v2, serial 0x{serial:x})…",
            10,
        )
        signed, method = sign_apk_with_method(apk, keystore=store, adb_binary=adb.binary)
        step(f"Подписано ({method}): {signed}", 25)
        for seen in apk_certificate_serials(signed):
            step(f"в подписанном APK serial=0x{seen:x}", 26)
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

    blob = " ".join(report.log).lower()
    if "no_certificates" in blob or "smimecapability" in blob:
        step(
            "ГУ отвергла подпись APK (NO_CERTIFICATES). Пакет не установлен — "
            "в списке com.changanhub.quickbar не появится.",
            100,
        )
        return report
    if "not auth" in blob or "-118" in blob:
        step(
            "ГУ показала «is not auth, install failed» (код -118). Это отказ белого "
            "списка Feiyu: пакет разобрали, сертификат не приняли. В журнале выше — "
            "serial с уже стоящих приложений и способ подписи (apksigner или python).",
            100,
        )
        return report

    step("pm install не прошёл. adb root на Feiyu не трогаю — он рвёт USB.", 100)
    return report


def _after_install(adb: Adb, report: InstallReport) -> None:
    for result in adb.clear_launcher_cache():
        report.add(result.text or result.stderr or "ok")
    report.add("Иконки в штатном меню Feiyu может не быть — это нормально.")


def discover_hu_signer_serial(adb: Adb, step: Progress | None = None) -> int | None:
    """Read signing serials from third-party apps already on the head unit."""
    from hub.paths import app_data

    found: list[int] = []
    probe_dir = app_data() / "probe"
    probe_dir.mkdir(parents=True, exist_ok=True)
    for pkg in PROBE_PACKAGES:
        result = adb.shell(f"pm path {pkg}", timeout=10)
        remote = ""
        for line in result.stdout.splitlines():
            if "package:" in line:
                remote = line.split("package:", 1)[-1].strip()
                break
        if not remote:
            continue
        local = probe_dir / f"{pkg.split('.')[-1]}.apk"
        pulled = adb.raw(["pull", remote, str(local)], timeout=40)
        if not pulled.ok or not local.exists() or local.stat().st_size < 64:
            continue
        try:
            serials = apk_certificate_serials(local)
        except Exception:
            serials = []
        try:
            local.unlink()
        except OSError:
            pass
        if not serials:
            continue
        serial = serials[0]
        found.append(serial)
        if step:
            step(f"на ГУ {pkg} serial=0x{serial:x}", 8)
        if serial == CHANGAN_SERIAL:
            return serial
    return found[0] if found else None
