"""Install APKs onto a Changan head unit, bypassing the missing vendor cert."""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from hub.adb import Adb, CommandResult
from hub.signer import CHANGAN_SERIAL, apk_certificate_serials, ensure_keystore, sign_apk_with_method

OVERLAY_PACKAGES = (
    "com.changanhub.quickkeep",
    "com.changanhub.quicklane",
    "com.changanhub.quickdock",
    "com.changanhub.quickbar",
)

# Logs from Lamore Feiyu: first push to tmp succeeds; extra folders only add noise.
REMOTE_CANDIDATES = (
    "/data/local/tmp",
    "/sdcard/Download",
)

# Same logs: every flag combo returned the same pm result. Keep the one that
# actually talks to PackageManager (`-g` grants runtime perms on first install).
PM_INSTALL_FLAGS = "-r -t -g"

_INCOMPATIBLE_PKG = re.compile(r"Package ([A-Za-z0-9._]+) signatures", re.I)

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
    if any(
        token in low
        for token in ("pm install", "pm uninstall", "удал", "шаг 3/", "шаг 4/", "adb root", "кэш лаунчера")
    ):
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
    package = package or apk_package_name(apk)
    if already_signed:
        signed = apk
        step("Переподпись не нужна.", 15)
    else:
        # Overlay leftovers are auth apps. Cloning their serial (not the cert)
        # and generating a new keystore makes pm install -r fail with
        # UPDATE_INCOMPATIBLE, then pm uninstall pops 提示 not allow delete.
        # Sign from NewPipe/EasyConn probe serial instead.
        installed_serial = None
        if package and package not in OVERLAY_PACKAGES:
            installed_serial = discover_package_signer_serial(adb, package, step)
        hu_serial = load_cached_hu_serial()
        if installed_serial:
            step(
                f"Уже стоящий {package} serial=0x{installed_serial:x} — подписываю тем же ключом, "
                "чтобы pm install -r прошёл.",
                8,
            )
            hu_serial = installed_serial
        elif hu_serial:
            step(f"Беру сохранённый serial ГУ 0x{hu_serial:x} (без скачивания приложений).", 8)
        else:
            hu_serial = discover_hu_signer_serial(adb, step)
            if hu_serial:
                save_cached_hu_serial(hu_serial)
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
        package = package or apk_package_name(signed)
    report.signed_apk = signed
    report.package = package

    # Overlay re-signs can disagree with a leftover disabled package. Enable
    # first so pm install -r can replace a matching signature; mismatched
    # signatures get a short uninstall --user 0, not a 20s auth-delete hang.
    if package:
        present = adb.shell(f"pm path {package}", timeout=8)
        if "package:" in (present.stdout or ""):
            adb.shell(f"pm enable --user 0 {package}", timeout=8)

    # Working path from the HU log: push → /data/local/tmp + pm install -r -t -g.
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
    cmd = f"pm install {PM_INSTALL_FLAGS} {remote_apk}"
    step(f"выполняю {cmd}", 65)
    result = adb.shell(cmd, timeout=25)
    step(
        f"{cmd} code={result.code} stdout={result.stdout.strip()!r} stderr={result.stderr.strip()!r}",
        70,
    )
    blob = f"{result.stdout}\n{result.stderr}"
    if not _ok_install(result) and "update_incompatible" in blob.lower():
        conflict = _package_from_pm_error(blob) or package
        overlay_conflict = bool(
            (conflict and conflict in OVERLAY_PACKAGES) or (package and package in OVERLAY_PACKAGES)
        )
        if overlay_conflict:
            step(
                f"Подпись не совпадает со стоящим {conflict}. Feiyu не даёт удалить "
                "auth-приложение (提示 not allow delete) — pm uninstall не вызываю. "
                "Старую панель отключаю. Рабочая QuickBar — com.changanhub.quickkeep.",
                72,
            )
            if conflict:
                uninstall_package(adb, conflict, step)
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
                    step(f"выполняю {cmd}", 74)
                    result = adb.shell(cmd, timeout=25)
                    step(
                        f"{cmd} code={result.code} stdout={result.stdout.strip()!r} "
                        f"stderr={result.stderr.strip()!r}",
                        75,
                    )
                else:
                    step(
                        "Feiyu не сняла пакет (提示 not allow delete или timeout). "
                        "Старую панель не трогаю. Новая QuickBar ставится отдельным "
                        "пакетом com.changanhub.quickkeep.",
                        75,
                    )
    if _ok_install(result):
        report.ok = True
        report.method = f"pm install {PM_INSTALL_FLAGS}"
        adb.shell(f"rm {remote_apk}", timeout=8)
        step("Шаг 4/5: чищу кэш лаунчера…", 85)
        _after_install(adb, report)
        step("Шаг 5/5: пакет установлен.", 100)
        return report

    blob = " ".join(report.log).lower()
    if "no_certificates" in blob or "smimecapability" in blob:
        step(
            "ГУ отвергла подпись APK (NO_CERTIFICATES). Пакет не установлен — "
            "в списке com.changanhub.quickkeep не появится.",
            100,
        )
        return report
    if "not auth" in blob or "-118" in blob:
        step(
            "ГУ показала «is not auth, install failed» (код -118). Это отказ белого "
            "списка Feiyu при установке, не при удалении. Старую панель Hub не снимал. "
            "В журнале выше — serial с уже стоящих приложений и способ подписи.",
            100,
        )
        return report

    step("pm install не прошёл. adb root на Feiyu не трогаю — он рвёт USB.", 100)
    return report


def _after_install(adb: Adb, report: InstallReport) -> None:
    for result in adb.clear_launcher_cache():
        report.add(result.text or result.stderr or "ok")
    report.add("Иконки в штатном меню Feiyu может не быть — это нормально.")


def discover_package_signer_serial(
    adb: Adb, package: str, step: Progress | None = None
) -> int | None:
    """Read the signing serial of a package already on the head unit."""
    from hub.paths import app_data

    result = adb.shell(f"pm path {package}", timeout=10)
    remote = ""
    for line in result.stdout.splitlines():
        if "package:" in line:
            remote = line.split("package:", 1)[-1].strip()
            break
    if not remote:
        return None
    probe_dir = app_data() / "probe"
    probe_dir.mkdir(parents=True, exist_ok=True)
    local = probe_dir / f"{package.split('.')[-1]}.apk"
    pulled = adb.raw(["pull", remote, str(local)], timeout=40)
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


def discover_hu_signer_serial(adb: Adb, step: Progress | None = None) -> int | None:
    """Read signing serials from third-party apps already on the head unit."""
    for pkg in PROBE_PACKAGES:
        serial = discover_package_signer_serial(adb, pkg, step)
        if serial:
            return serial
    return None


def apk_package_name(apk: Path) -> str | None:
    """Best-effort package id from filename / catalog / binary manifest."""
    from hub.catalog import CATALOG

    stem = apk.name.lower()
    if any(token in stem for token in ("quickbar", "quickdock", "quicklane", "quickkeep")):
        return "com.changanhub.quickkeep"
    if any(token in stem for token in ("player", "lamoreplayer")):
        return "com.changanhub.lamoreplayer"
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
    note(f"не вызываю pm uninstall для {package} — на Feiyu это 提示 not allow delete")
    return False


def _package_from_pm_error(text: str) -> str | None:
    match = _INCOMPATIBLE_PKG.search(text)
    return match.group(1) if match else None


def _serial_cache_path() -> Path:
    from hub.paths import app_data

    return app_data() / "certs" / "hu_serial.txt"


def load_cached_hu_serial() -> int | None:
    path = _serial_cache_path()
    if not path.exists():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip(), 0)
    except (OSError, ValueError):
        return None


def save_cached_hu_serial(serial: int) -> None:
    path = _serial_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(hex(serial), encoding="utf-8")
