"""Install and launch AI Chat on the head unit."""

from __future__ import annotations

from pathlib import Path

from hub.adb import Adb
from hub.installer import Progress, install_apk
from hub.paths import bundled_apps

PACKAGE = "com.changanhub.aichat"
JAVA_MAIN = "com.changanhub.chat.ChatActivity"

GRANT_SHELL = (
    f"pm grant {PACKAGE} android.permission.RECORD_AUDIO",
    f"appops set {PACKAGE} RECORD_AUDIO allow",
    f"dumpsys deviceidle whitelist +{PACKAGE}",
    f"am set-inactive {PACKAGE} false",
)


def aichat_apk() -> Path:
    return bundled_apps() / "AiChat.apk"


def grant_aichat(adb: Adb, progress: Progress | None = None) -> list[str]:
    log: list[str] = []
    for cmd in GRANT_SHELL:
        if progress:
            progress(f"разрешение: {cmd}", 90)
        result = adb.shell(cmd, timeout=10)
        log.append(f"{cmd} code={result.code} out={result.stdout.strip()!r} err={result.stderr.strip()!r}")
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
    lines.append(
        "Ключи DeepSeek / Yandex — вкладка Настройки. Автоозвучка — переключатель в шапке. "
        "Интернет на ГУ обязателен. Тот же каталог Hub, иначе другой ключ подписи."
    )
    return lines
