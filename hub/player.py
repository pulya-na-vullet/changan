"""Install and launch Lamore Player on the head unit."""

from __future__ import annotations

from pathlib import Path

from hub.adb import Adb
from hub.installer import Progress, install_apk
from hub.paths import bundled_apps

# New applicationId: Feiyu refuses pm install -r when the Hub folder minted a
# new RSA key (UPDATE_INCOMPATIBLE) and refuses pm uninstall (auth dialog).
PACKAGE = "com.changanhub.playrise"
LEGACY_PACKAGES = ("com.changanhub.lamoreplayer",)
JAVA_MAIN = "com.changanhub.player.BrowserActivity"

GRANT_SHELL = (
    f"pm grant {PACKAGE} android.permission.READ_EXTERNAL_STORAGE",
    f"pm grant {PACKAGE} android.permission.WRITE_EXTERNAL_STORAGE",
    f"pm grant {PACKAGE} android.permission.RECORD_AUDIO",
    f"appops set {PACKAGE} RECORD_AUDIO allow",
    f"appops set {PACKAGE} READ_EXTERNAL_STORAGE allow",
    f"dumpsys deviceidle whitelist +{PACKAGE}",
    f"am set-inactive {PACKAGE} false",
)


def player_apk() -> Path:
    return bundled_apps() / "Player.apk"


def is_player_package(package: str) -> bool:
    return package == PACKAGE or package in LEGACY_PACKAGES


def launch_player_target(package: str) -> str | None:
    """Leftover player icons start the working package, not the old APK."""
    if is_player_package(package):
        return PACKAGE
    return None


def grant_player(adb: Adb, progress: Progress | None = None) -> list[str]:
    log: list[str] = []
    for cmd in GRANT_SHELL:
        if progress:
            progress(f"разрешение: {cmd}", 90)
        result = adb.shell(cmd, timeout=10)
        log.append(f"{cmd} code={result.code} out={result.stdout.strip()!r} err={result.stderr.strip()!r}")
    return log


def retire_legacy(adb: Adb, progress: Progress | None = None) -> list[str]:
    """Hide the undeletable old player after the new package is installed."""
    log: list[str] = []
    for pkg in LEGACY_PACKAGES:
        for cmd in (
            f"am force-stop {pkg}",
            f"pm disable-user --user 0 {pkg}",
        ):
            if progress:
                progress(f"старый плеер: {cmd}", 88)
            result = adb.shell(cmd, timeout=8)
            log.append(
                f"{cmd} code={result.code} out={result.stdout.strip()!r} err={result.stderr.strip()!r}"
            )
    return log


def start_player(adb: Adb, progress: Progress | None = None) -> list[str]:
    log: list[str] = []
    if progress:
        progress(f"включаю {PACKAGE}", 92)
    enabled = adb.shell(f"pm enable --user 0 {PACKAGE}", timeout=8)
    log.append(
        f"pm enable --user 0 {PACKAGE} code={enabled.code} "
        f"out={enabled.stdout.strip()!r} err={enabled.stderr.strip()!r}"
    )
    log += grant_player(adb, progress=progress)
    cmd = f"am start -n {PACKAGE}/{JAVA_MAIN}"
    if progress:
        progress(f"запуск: {cmd}", 96)
    result = adb.shell(cmd, timeout=10)
    log.append(f"{cmd} code={result.code} out={result.stdout.strip()!r} err={result.stderr.strip()!r}")
    return log


def install_player(adb: Adb, progress: Progress | None = None) -> list[str]:
    apk = player_apk()
    if not apk.exists():
        return [f"Player.apk не найден: {apk}"]
    lines = [f"Файл плеера: {apk} ({apk.stat().st_size} байт)"]
    if progress:
        progress(lines[0], 5)
    report = install_apk(adb, apk, already_signed=False, progress=progress, package=PACKAGE)
    lines.extend(report.log)
    if not report.ok:
        lines.append(f"Плеер НЕ установлен. В списке ГУ не будет {PACKAGE}.")
        return lines
    lines.append(f"Пакет установлен. В списке ГУ: Lamore Player · {PACKAGE}")
    lines += start_player(adb, progress=progress)
    lines += retire_legacy(adb, progress=progress)
    lines.append(
        "Откройте флешку в плеере. Вкладки: музыка, видео, эквалайзер, визуализация. "
        "Видео — SRT рядом с файлом и выбор дорожки. "
        "Старый com.changanhub.lamoreplayer Feiyu не удаляет — его отключаю, не снимаю."
    )
    return lines
