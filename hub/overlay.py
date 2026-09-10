"""Deploy and control the right-edge QuickBar overlay."""

from __future__ import annotations

from pathlib import Path

from hub.adb import Adb
from hub.installer import Progress, install_apk
from hub.paths import bundled_apps

# New applicationId: Feiyu forbids deleting already-installed auth packages
# (提示 «is auth app, not allow delete!»). quickbar / quickdock / quicklane stay
# on the HU; this id is a first install so a new signature can land.
PACKAGE = "com.changanhub.quickkeep"
LEGACY_PACKAGES = (
    "com.changanhub.quickbar",
    "com.changanhub.quickdock",
    "com.changanhub.quicklane",
)
LEGACY_PACKAGE = LEGACY_PACKAGES[0]
# Windows CreateProcess (~32k). Feiyu duplicates accessibility services; a
# settings put of the raw string raises WinError 206 and kills Hub.
_MAX_SETTINGS_CMD = 3500
JAVA_SERVICE = "com.changanhub.quickbar.OverlayService"
JAVA_BOOT = "com.changanhub.quickbar.BootActivity"
JAVA_ACCESS = "com.changanhub.quickbar.KeepAliveAccessibility"
SERVICE = f"{PACKAGE}/{JAVA_SERVICE}"
ACCESS_COMPONENT = f"{PACKAGE}/{JAVA_ACCESS}"

# Keep the panel alive after ACC off→on. Feiyu drops BOOT_COMPLETED and
# force-stops third-party apps; accessibility + deviceidle keep a wake path.
PERSIST_SHELL = (
    f"appops set {PACKAGE} SYSTEM_ALERT_WINDOW allow",
    f"appops set {PACKAGE} RUN_IN_BACKGROUND allow",
    f"appops set {PACKAGE} RUN_ANY_IN_BACKGROUND allow",
    f"appops set {PACKAGE} START_FOREGROUND allow",
    f"dumpsys deviceidle whitelist +{PACKAGE}",
    f"am set-inactive {PACKAGE} false",
    f"appops set {PACKAGE} REQUEST_INSTALL_PACKAGES allow",
    f"appops set {PACKAGE} GET_USAGE_STATS allow",
    f"pm grant {PACKAGE} android.permission.READ_EXTERNAL_STORAGE",
    f"pm grant {PACKAGE} android.permission.WRITE_EXTERNAL_STORAGE",
    "settings put secure install_non_market_apps 1",
)


def overlay_apk() -> Path:
    return bundled_apps() / "QuickBar.apk"


def grant_overlay(adb: Adb, progress: Progress | None = None) -> list[str]:
    log = []
    for cmd in PERSIST_SHELL:
        if progress:
            progress(f"разрешение: {cmd}", 90)
        result = adb.shell(cmd, timeout=10)
        log.append(f"{cmd} code={result.code} out={result.stdout.strip()!r} err={result.stderr.strip()!r}")
    return log


def _retire_package(adb: Adb, pkg: str, progress: Progress | None = None) -> list[str]:
    """Hide an undeletable old overlay. ``pm uninstall`` shows 提示 «not allow delete»
    and times out; Feiyu never removes an auth package. Do not call ``pm disable``
    without ``--user`` — shell gets SecurityException then hangs the retry."""
    log: list[str] = []
    for cmd in (
        f"am startservice -n {pkg}/{JAVA_SERVICE} -a com.changanhub.quickbar.HIDE",
        f"am startservice -n {pkg}/{JAVA_SERVICE} -a com.changanhub.quickbar.PAUSE",
        f"am force-stop {pkg}",
        f"appops set {pkg} SYSTEM_ALERT_WINDOW ignore",
        f"dumpsys deviceidle whitelist -{pkg}",
        f"pm disable-user --user 0 {pkg}",
    ):
        if progress:
            progress(f"старая панель: {cmd}", 88)
        result = adb.shell(cmd, timeout=8)
        log.append(f"{cmd} code={result.code} out={result.stdout.strip()!r} err={result.stderr.strip()!r}")
    return log


def retire_legacy(adb: Adb, progress: Progress | None = None) -> list[str]:
    log: list[str] = []
    for pkg in LEGACY_PACKAGES:
        log += _retire_package(adb, pkg, progress=progress)
    return log


def accessibility_services_value(raw: str, component: str, max_cmd: int = _MAX_SETTINGS_CMD) -> str | None:
    """Deduped ``enabled_accessibility_services`` value, or None if still too long.

    Feiyu repeats incall/iflytek components dozens of times. Rewriting that
    string with ``settings put`` blows the Windows command line (WinError 206).
    Putting only our component would wipe Incall — skip the rewrite instead.
    """
    parts: list[str] = []
    seen: set[str] = set()
    blob = (raw or "").strip()
    if blob and blob not in ("null", "0"):
        for item in blob.split(":"):
            item = item.strip()
            if not item or item in seen:
                continue
            seen.add(item)
            parts.append(item)
    if component not in seen:
        parts.append(component)
    value = ":".join(parts)
    cmd = f"settings put secure enabled_accessibility_services {value}"
    if len(cmd) > max_cmd:
        return None
    return value


def enable_accessibility(adb: Adb, progress: Progress | None = None) -> list[str]:
    """Feiyu rebinds enabled accessibility services after ACC even without BOOT_COMPLETED."""
    log: list[str] = []
    current = adb.shell("settings get secure enabled_accessibility_services", timeout=8)
    raw = (current.stdout or "").strip()
    value = accessibility_services_value(raw, ACCESS_COMPONENT)
    cmds: list[str] = []
    if value is None:
        log.append(
            "enabled_accessibility_services слишком длинный даже после дедупа — "
            "не вызываю settings put (WinError 206). Только accessibility_enabled 1."
        )
    else:
        cmds.append(f"settings put secure enabled_accessibility_services {value}")
    cmds.append("settings put secure accessibility_enabled 1")
    for cmd in cmds:
        if progress:
            progress(f"автозапуск ACC: {cmd}", 92)
        result = adb.shell(cmd, timeout=8)
        log.append(f"{cmd} code={result.code} out={result.stdout.strip()!r} err={result.stderr.strip()!r}")
    return log


def disable_user_package(adb: Adb, package: str, progress: Progress | None = None) -> list[str]:
    """Feiyu refuses pm uninstall on whitelist-signed apps. Disable instead."""
    log: list[str] = []

    def step(message: str, percent: int = 70) -> None:
        log.append(message)
        if progress:
            progress(message, percent)

    if package == PACKAGE or package in LEGACY_PACKAGES:
        step(
            f"{package} — auth-панель, pm uninstall покажет 提示 not allow delete. "
            "Отключаю без удаления.",
            60,
        )
        log += _retire_package(adb, package, progress=progress)
        return log

    step(f"пробую pm uninstall --user 0 {package} (лимит 8с)", 60)
    gone = adb.shell(f"pm uninstall --user 0 {package}", timeout=8)
    log.append(
        f"pm uninstall --user 0 {package} code={gone.code} "
        f"out={gone.stdout.strip()!r} err={gone.stderr.strip()!r}"
    )
    blob = f"{gone.stdout}\n{gone.stderr}".lower()
    if gone.code != 124 and "success" in blob and "failure" not in blob and "not allow" not in blob:
        step(f"{package} снят", 100)
        return log
    step("Feiyu не удаляет auth-приложение. Скрываю и отключаю пакет.", 70)
    for cmd in (
        f"am force-stop {package}",
        f"pm hide {package}",
        f"cmd package hide {package}",
        f"pm disable-user --user 0 {package}",
    ):
        result = adb.shell(cmd, timeout=8)
        log.append(f"{cmd} code={result.code} out={result.stdout.strip()!r} err={result.stderr.strip()!r}")
    return log


def start_overlay(adb: Adb, progress: Progress | None = None) -> list[str]:
    log = retire_legacy(adb, progress=progress)
    if progress:
        progress(f"включаю пакет {PACKAGE}", 89)
    enabled = adb.shell(f"pm enable --user 0 {PACKAGE}", timeout=8)
    log.append(
        f"pm enable --user 0 {PACKAGE} code={enabled.code} "
        f"out={enabled.stdout.strip()!r} err={enabled.stderr.strip()!r}"
    )
    log += grant_overlay(adb, progress=progress)
    log += enable_accessibility(adb, progress=progress)
    # BootActivity is Theme.NoDisplay and finishes immediately — clears FLAG_STOPPED
    # so ACC/BOOT broadcasts will be delivered later. Do not start MainActivity.
    for cmd in (
        f"am start -n {PACKAGE}/{JAVA_BOOT} --activity-no-animation",
        f"am startservice -n {SERVICE}",
        f"am start-foreground-service -n {SERVICE}",
        f"am startservice -n {SERVICE} -a com.changanhub.quickbar.SHOW",
    ):
        if progress:
            progress(f"запуск: {cmd}", 95)
        result = adb.shell(cmd, timeout=10)
        log.append(f"{cmd} code={result.code} out={result.stdout.strip()!r} err={result.stderr.strip()!r}")
    return log


def stop_overlay(adb: Adb) -> list[str]:
    lines = []
    for pkg in (PACKAGE, *LEGACY_PACKAGES):
        result = adb.shell(f"am force-stop {pkg}", timeout=10)
        lines.append(f"force-stop {pkg} code={result.code} {result.text or result.stderr}")
    return lines


def remove_overlay(adb: Adb, progress: Progress | None = None) -> list[str]:
    lines: list[str] = []

    def step(message: str, percent: int) -> None:
        lines.append(message)
        if progress:
            progress(message, percent)

    step("Feiyu не удаляет auth-приложение (提示 not allow delete). Отключаю панели.", 40)
    lines += retire_legacy(adb, progress=progress)
    lines += _retire_package(adb, PACKAGE, progress=progress)
    return lines


def install_overlay(adb: Adb, progress: Progress | None = None) -> list[str]:
    apk = overlay_apk()
    if not apk.exists():
        return [f"QuickBar.apk не найден: {apk}"]
    lines = [f"Файл панели: {apk} ({apk.stat().st_size} байт)"]
    if progress:
        progress(lines[0], 5)
    report = install_apk(adb, apk, already_signed=False, progress=progress, package=PACKAGE)
    lines.extend(report.log)
    if not report.ok:
        if any("not auth" in line.lower() or "-118" in line for line in report.log):
            lines.append(
                "Пакет НЕ установлен. Белое окно 提示 «is not auth, install failed!» — "
                "отказ белого списка Feiyu (pm -118), не краш. "
                f"Имя после успеха: QuickBar / {PACKAGE}."
            )
        else:
            lines.append(
                f"Пакет НЕ установлен. В «Приложения ГУ» не будет {PACKAGE}. "
                f"Имя после успеха: QuickBar / {PACKAGE}."
            )
        if progress:
            progress("Установка не удалась — пакета в списке не будет.", 100)
        return lines
    lines.append(f"Пакет установлен. В списке ГУ: QuickBar · {PACKAGE}")
    lines += start_overlay(adb, progress=progress)
    if progress:
        progress("Готово. Ищите зелёную колонку СПРАВА, не иконку в меню.", 100)
    lines.append("Панель — зелёная колонка СПРАВА поверх экрана, не пункт в меню приложений.")
    lines.append(
        "Старые com.changanhub.quickbar / quickdock / quicklane Feiyu не даёт удалить "
        "(auth, not allow delete) — Hub их отключает и ставит новую com.changanhub.quickkeep."
    )
    return lines
