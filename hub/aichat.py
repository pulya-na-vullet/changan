"""Install and launch AI Chat on the head unit."""

from __future__ import annotations

from pathlib import Path

from hub.adb import Adb
from hub.installer import Progress, install_apk
from hub.paths import bundled_apps

# New applicationId: a fresh GitHub ZIP mints a new RSA key, so pm install -r
# of com.changanhub.aichat fails UPDATE_INCOMPATIBLE and Feiyu blocks uninstall.
PACKAGE = "com.changanhub.chatrise"
LEGACY_PACKAGES = ("com.changanhub.aichat",)
JAVA_MAIN = "com.changanhub.chat.ChatActivity"

GRANT_SHELL = (
    f"pm grant {PACKAGE} android.permission.RECORD_AUDIO",
    f"appops set {PACKAGE} RECORD_AUDIO allow",
    f"dumpsys deviceidle whitelist +{PACKAGE}",
    f"am set-inactive {PACKAGE} false",
)


def aichat_apk() -> Path:
    return bundled_apps() / "AiChat.apk"


def is_aichat_package(package: str) -> bool:
    return package == PACKAGE or package in LEGACY_PACKAGES


def launch_aichat_target(package: str) -> str | None:
    """Leftover chat icons start the working package, not the old APK."""
    if is_aichat_package(package):
        return PACKAGE
    return None


def grant_aichat(adb: Adb, progress: Progress | None = None) -> list[str]:
    log: list[str] = []
    for cmd in GRANT_SHELL:
        if progress:
            progress(f"разрешение: {cmd}", 90)
        result = adb.shell(cmd, timeout=10)
        log.append(f"{cmd} code={result.code} out={result.stdout.strip()!r} err={result.stderr.strip()!r}")
    return log


def retire_legacy(adb: Adb, progress: Progress | None = None) -> list[str]:
    """Hide the undeletable old chat after the new package is installed."""
    log: list[str] = []
    for pkg in LEGACY_PACKAGES:
        for cmd in (
            f"am force-stop {pkg}",
            f"pm disable-user --user 0 {pkg}",
        ):
            if progress:
                progress(f"старый чат: {cmd}", 88)
            result = adb.shell(cmd, timeout=8)
            log.append(
                f"{cmd} code={result.code} out={result.stdout.strip()!r} err={result.stderr.strip()!r}"
            )
    return log


def start_aichat(adb: Adb, progress: Progress | None = None) -> list[str]:
    log: list[str] = []
    if progress:
        progress(f"включаю {PACKAGE}", 92)
    enabled = adb.shell(f"pm enable --user 0 {PACKAGE}", timeout=8)
    log.append(
        f"pm enable --user 0 {PACKAGE} code={enabled.code} "
        f"out={enabled.stdout.strip()!r} err={enabled.stderr.strip()!r}"
    )
    log += grant_aichat(adb, progress=progress)
    cmd = f"am start -n {PACKAGE}/{JAVA_MAIN}"
    if progress:
        progress(f"запуск: {cmd}", 96)
    result = adb.shell(cmd, timeout=10)
    log.append(f"{cmd} code={result.code} out={result.stdout.strip()!r} err={result.stderr.strip()!r}")
    return log


def install_aichat(adb: Adb, progress: Progress | None = None) -> list[str]:
    apk = aichat_apk()
    if not apk.exists():
        return [f"AiChat.apk не найден: {apk}"]
    lines = [f"Файл чата: {apk} ({apk.stat().st_size} байт)"]
    if progress:
        progress(lines[0], 5)
    report = install_apk(adb, apk, already_signed=False, progress=progress, package=PACKAGE)
    lines.extend(report.log)
    if not report.ok:
        lines.append(f"AI Chat НЕ установлен. В списке ГУ не будет {PACKAGE}.")
        return lines
    lines.append(f"Пакет установлен. В списке ГУ: AI Chat · {PACKAGE}")
    lines += start_aichat(adb, progress=progress)
    lines += retire_legacy(adb, progress=progress)
    lines.append(
        "Ключи DeepSeek / Yandex — вкладка Настройки. Автоозвучка — переключатель в шапке. "
        "Интернет на ГУ обязателен. На Feiyu нет Google STT: пишите текстом (Яндекс-клавиатура). "
        "Русский интерфейс — из приложения, язык системы ГУ может остаться китайским."
    )
    return lines
