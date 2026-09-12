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
    "com.changanhub.quickrise",
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

# Official RU / overlay firmware often has zero /data/app packages. The
# whitelist serial is baked into Vecentek + services.jar, not a sideloaded APK.
MANAGER_PATHS = (
    "/system/app/VecentekApp/VecentekApp.apk",
    "/system/app/VecentekAPP/VecentekAPP.apk",
    "/system/framework/services.jar",
)
MANAGER_HINTS = ("vecentek", "certificatemanager", "wutong")
_HEX16 = re.compile(rb"(?<![0-9a-fA-F])([0-9a-fA-F]{16})(?![0-9a-fA-F])")
_AUTH_NEEDLES = (
    b"not auth",
    b"CertificateManager",
    b"is not auth",
    b"install failed!",
    b"ddb66eefd98476f3",
    b"DDB66EEFD98476F3",
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
    used_serial: int | None = None
    if already_signed:
        signed = apk
        step("Переподпись не нужна.", 15)
    else:
        used_serial, signed, method = _sign_for_hu(adb, apk, package, step)
        package = package or apk_package_name(signed)
    report.signed_apk = signed
    report.package = package

    if package:
        present = adb.shell(f"pm path {package}", timeout=8)
        if "package:" in merged_output(present):
            adb.shell(f"pm enable --user 0 {package}", timeout=8)

    result, remote_apk = _push_and_pm(adb, signed, step)
    if remote_apk is None:
        return report
    blob = merged_output(result)
    if not _ok_install(result) and "update_incompatible" in blob.lower():
        conflict = _package_from_pm_error(blob) or package
        overlay_conflict = bool(
            (conflict and conflict in OVERLAY_PACKAGES) or (package and package in OVERLAY_PACKAGES)
        )
        if overlay_conflict:
            step(
                f"Подпись не совпадает со стоящим {conflict}. Feiyu не даёт удалить "
                "auth-приложение (提示 not allow delete) — pm uninstall не вызываю. "
                "Старую панель отключаю. Рабочая QuickBar — com.changanhub.quickrise.",
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
                    result, remote_apk = _push_and_pm(adb, signed, step, start_pct=74)
                    if remote_apk is None:
                        return report
                else:
                    step(
                        "Feiyu не сняла пакет (提示 not allow delete или timeout). "
                        "Старую панель не трогаю. Новая QuickBar ставится отдельным "
                        "пакетом com.changanhub.quickrise.",
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
            retry = _resign_after_not_auth(adb, apk, package, used_serial, step)
            if retry is not None:
                used_serial, signed, method = retry
                report.signed_apk = signed
                result, remote_apk = _push_and_pm(adb, signed, step)
                if remote_apk is None:
                    return report
                if _ok_install(result):
                    return _finish_ok(adb, report, remote_apk, step)
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


def _finish_ok(
    adb: Adb, report: InstallReport, remote_apk: str, step: Progress
) -> InstallReport:
    report.ok = True
    report.method = f"pm install {PM_INSTALL_FLAGS}"
    adb.shell(f"rm {remote_apk}", timeout=8)
    step("Шаг 4/5: чищу кэш лаунчера…", 85)
    _after_install(adb, report)
    step("Шаг 5/5: пакет установлен.", 100)
    return report


def merged_output(result: CommandResult) -> str:
    return f"{result.stdout or ''}\n{result.stderr or ''}"


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
        if pkg and path:
            mapping[pkg] = path
    return mapping


def parse_pm_path(text: str) -> str:
    for line in (text or "").splitlines():
        line = line.strip()
        if not line.startswith("package:"):
            continue
        rest = line.split("package:", 1)[-1].strip()
        if "=" in rest:
            path, _pkg = rest.rsplit("=", 1)
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
) -> tuple[int, Path, str]:
    # Overlay leftovers are auth apps. Cloning their serial (not the cert)
    # and generating a new keystore makes pm install -r fail with
    # UPDATE_INCOMPATIBLE, then pm uninstall pops 提示 not allow delete.
    # Sign from an already-installed third-party APK on THIS head unit.
    installed_serial = None
    if package and package not in OVERLAY_PACKAGES:
        installed_serial = discover_package_signer_serial(adb, package, step)
    device = getattr(adb, "serial", None)
    hu_serial = None if ignore_cache else load_cached_hu_serial(device)
    if installed_serial:
        step(
            f"Уже стоящий {package} serial=0x{installed_serial:x} — подписываю тем же ключом, "
            "чтобы pm install -r прошёл.",
            8,
        )
        hu_serial = installed_serial
    elif hu_serial:
        step(
            f"Беру сохранённый serial ГУ {device or '?'} 0x{hu_serial:x} "
            "(без скачивания приложений).",
            8,
        )
    else:
        candidates = discover_hu_signer_candidates(adb, step)
        if candidates:
            hu_serial = candidates[0]
            save_cached_hu_serial(hu_serial, device)
        else:
            hu_serial = None
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
    return serial, signed, method


def _resign_after_not_auth(
    adb: Adb,
    apk: Path,
    package: str | None,
    used_serial: int | None,
    step: Progress,
) -> tuple[int, Path, str] | None:
    step(
        "Белый список этой ГУ другой. Снимаю serial из Vecentek/services.jar "
        "и сторонних APK этой машины, без кэша.",
        72,
    )
    device = getattr(adb, "serial", None)
    if device:
        _clear_cached_hu_serial(device)
    for fresh in discover_hu_signer_candidates(adb, step):
        if fresh == used_serial:
            continue
        save_cached_hu_serial(fresh, device)
        step(
            f"Повторная подпись serial=0x{fresh:x} (было 0x{used_serial:x}).",
            82,
        )
        store = ensure_keystore(serial=fresh)
        signed, method = sign_apk_with_method(apk, keystore=store, adb_binary=adb.binary)
        step(f"Подписано ({method}): {signed}", 84)
        for seen in apk_certificate_serials(signed):
            step(f"в подписанном APK serial=0x{seen:x}", 84)
        return fresh, signed, method
    step(
        "Другой serial на этой ГУ не нашёл — гайд Feiyu отвергла, сторонних APK нет. "
        "Смотрите VecentekApp / services.jar в журнале.",
        80,
    )
    return None


def _push_and_pm(
    adb: Adb, signed: Path, step: Progress, start_pct: int = 35
) -> tuple[CommandResult, str | None]:
    step("Шаг 2/5: копирую APK на ГУ (push). adb install пропускаю — на Feiyu он зависает.", start_pct)
    remote_apk = None
    for folder in REMOTE_CANDIDATES:
        remote = f"{folder}/{signed.name.replace(' ', '_')}"
        step(f"push → {remote}", min(start_pct + 5, 45))
        pushed = adb.push(signed, remote, timeout=40)
        step(
            f"push code={pushed.code} stdout={pushed.stdout.strip()!r} stderr={pushed.stderr.strip()!r}",
            min(start_pct + 10, 45),
        )
        if pushed.ok and "error" not in (pushed.stdout + pushed.stderr).lower() and pushed.code != 124:
            remote_apk = remote
            break
    if not remote_apk:
        step("Не удалось скопировать APK. Проверьте ADB-режим (USB切换 → ADB模式).", 45)
        return CommandResult(False, "", "push failed", 1, []), None
    step("Шаг 3/5: pm install на ГУ…", 60)
    cmd = f"pm install {PM_INSTALL_FLAGS} {remote_apk}"
    step(f"выполняю {cmd}", 65)
    result = adb.shell(cmd, timeout=25)
    step(
        f"{cmd} code={result.code} stdout={result.stdout.strip()!r} stderr={result.stderr.strip()!r}",
        70,
    )
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
    return _serial_from_remote_apk(adb, package, remote, step)


def _serial_from_remote_apk(
    adb: Adb, package: str, remote: str, step: Progress | None = None
) -> int | None:
    from hub.paths import app_data

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
    mapping = parse_package_paths(merged_output(result))
    extra = adb.shell("pm list packages -3 -f", timeout=15)
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
    if value in (0xFFFFFFFFFFFFFFFF, 0x7FFFFFFFFFFFFFFF):
        return False
    return True


def extract_embedded_serials(data: bytes) -> list[int]:
    """Whitelist serials baked into Vecentek/services, not the APK signing cert."""
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
    for needle in _AUTH_NEEDLES:
        start = 0
        while True:
            index = data.find(needle, start)
            if index < 0:
                break
            window = data[max(0, index - 96) : index + 96]
            for offset in range(0, max(0, len(window) - 7)):
                add(int.from_bytes(window[offset : offset + 8], "little"))
                add(int.from_bytes(window[offset : offset + 8], "big"))
            start = index + 1
    return found


def embedded_serials_in_apk(apk: Path) -> list[int]:
    found: list[int] = []

    def merge(values: list[int]) -> None:
        for value in values:
            if value not in found:
                found.append(value)

    try:
        merge(extract_embedded_serials(apk.read_bytes()))
    except OSError:
        return found
    try:
        with zipfile.ZipFile(apk) as zf:
            for name in zf.namelist():
                lower = name.lower()
                if not lower.endswith((".dex", ".jar", ".cer", ".crt", ".der", ".pem")):
                    continue
                blob = zf.read(name)
                merge(extract_embedded_serials(blob))
                if lower.endswith((".cer", ".crt", ".der", ".pem")):
                    try:
                        from cryptography import x509

                        cert = (
                            x509.load_pem_x509_certificate(blob)
                            if b"BEGIN CERTIFICATE" in blob
                            else x509.load_der_x509_certificate(blob)
                        )
                        if cert.serial_number not in found:
                            found.append(cert.serial_number)
                    except Exception:
                        pass
    except zipfile.BadZipFile:
        pass
    return found


def _manager_targets(mapping: dict[str, str]) -> list[tuple[str, str]]:
    targets: list[tuple[str, str]] = []
    seen: set[str] = set()
    for pkg, path in mapping.items():
        blob = f"{pkg} {path}".lower()
        if any(hint in blob for hint in MANAGER_HINTS):
            if path not in seen:
                targets.append((pkg, path))
                seen.add(path)
    for path in MANAGER_PATHS:
        if path not in seen:
            name = path.rsplit("/", 1)[-1]
            targets.append((name, path))
            seen.add(path)
    return targets


def _serials_from_manager(
    adb: Adb, mapping: dict[str, str], step: Progress | None = None
) -> list[int]:
    found: list[int] = []
    for pkg, remote in _manager_targets(mapping):
        timeout = 90 if remote.endswith(".jar") else 40
        from hub.paths import app_data

        probe_dir = app_data() / "probe"
        probe_dir.mkdir(parents=True, exist_ok=True)
        local = probe_dir / remote.rsplit("/", 1)[-1]
        if step:
            step(f"читаю белый список: {remote}", 7)
        pulled = adb.raw(["pull", remote, str(local)], timeout=timeout)
        if not pulled.ok or not local.exists() or local.stat().st_size < 64:
            if step:
                step(
                    f"не скачал {remote} code={pulled.code} err={pulled.stderr.strip()[:120]!r}",
                    7,
                )
            continue
        serials = embedded_serials_in_apk(local)
        if step:
            shown = ", ".join(f"0x{item:x}" for item in serials[:6]) or "пусто"
            step(f"{pkg}: вшитые serial {shown}", 8)
        for item in serials:
            if item not in found:
                found.append(item)
        try:
            local.unlink()
        except OSError:
            pass
        # Vecentek is enough when it already yielded a non-cookbook serial.
        if any(item != CHANGAN_SERIAL for item in found) and "vecentek" in pkg.lower():
            break
    return found


def discover_hu_signer_candidates(adb: Adb, step: Progress | None = None) -> list[int]:
    """Ordered serials to try on this HU: sideloaded APKs, then Vecentek, then cookbook."""
    if step:
        step("Снимаю serial со сторонних приложений и Vecentek этой ГУ.", 6)
    mapping = _all_package_paths(adb, step)
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
        step("сторонних APK нет (русификация в /system). Читаю Vecentek.", 7)

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

    embedded = _serials_from_manager(adb, mapping, step)
    other = [item for item in embedded if item != CHANGAN_SERIAL]
    ordered: list[int] = []
    for item in third + other:
        if item not in ordered:
            ordered.append(item)
    if CHANGAN_SERIAL in embedded and CHANGAN_SERIAL not in ordered:
        ordered.append(CHANGAN_SERIAL)
    if step and ordered:
        step("кандидаты serial: " + ", ".join(f"0x{item:x}" for item in ordered[:6]), 8)
    return ordered


def discover_hu_signer_serial(adb: Adb, step: Progress | None = None) -> int | None:
    """Read signing serials from third-party apps or Vecentek on this head unit."""
    candidates = discover_hu_signer_candidates(adb, step)
    return candidates[0] if candidates else None


def apk_package_name(apk: Path) -> str | None:
    """Best-effort package id from filename / catalog / binary manifest."""
    from hub.catalog import CATALOG

    stem = apk.name.lower()
    if any(token in stem for token in ("quickbar", "quickdock", "quicklane", "quickkeep", "quickrise")):
        return "com.changanhub.quickrise"
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
        return int(path.read_text(encoding="utf-8").strip(), 0)
    except (OSError, ValueError):
        return None


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
