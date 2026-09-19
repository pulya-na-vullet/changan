"""Install Changan News (changan_news APK, unmodified)."""

from __future__ import annotations

from pathlib import Path

from hub.adb import Adb
from hub.installer import Progress, install_apk
from hub.paths import bundled_apps
from hub.windowed import enable_freeform

# APK from https://github.com/pulya-na-vullet/changan_news — source is not copied here.
# The public repo currently ships the README/build scripts; the release APK is
# ChanganNews-1.5-release.apk (package ru.changan.news) when the author adds it.
PACKAGE = "ru.changan.news"
JAVA_MAIN = "ru.changan.news.MainActivity"
SOURCE_URL = "https://github.com/pulya-na-vullet/changan_news"

GRANT_SHELL = (
    f"dumpsys deviceidle whitelist +{PACKAGE}",
    f"am set-inactive {PACKAGE} false",
)


def news_apk() -> Path:
    bundled = bundled_apps()
    for name in (
        "ChanganNews.apk",
        "ChanganNews-1.5-release.apk",
        "News.apk",
    ):
        path = bundled / name
        if path.exists():
            return path
    return bundled / "ChanganNews.apk"


def is_news_package(package: str) -> bool:
    return package == PACKAGE


def grant_news(adb: Adb, progress: Progress | None = None) -> list[str]:
    log: list[str] = []
    for cmd in GRANT_SHELL:
        if progress:
            progress(f"разрешение: {cmd}", 90)
        result = adb.shell(cmd, timeout=10)
        log.append(f"{cmd} code={result.code} out={result.stdout.strip()!r} err={result.stderr.strip()!r}")
    return log


def start_news(adb: Adb, progress: Progress | None = None) -> list[str]:
    log: list[str] = []
    if progress:
        progress(f"включаю {PACKAGE}", 92)
    enabled = adb.shell(f"pm enable --user 0 {PACKAGE}", timeout=8)
    log.append(
        f"pm enable --user 0 {PACKAGE} code={enabled.code} "
        f"out={enabled.stdout.strip()!r} err={enabled.stderr.strip()!r}"
    )
    log += grant_news(adb, progress=progress)
    log += enable_freeform(adb, progress=progress)
    cmd = f"am start -n {PACKAGE}/{JAVA_MAIN}"
    if progress:
        progress(f"запуск: {cmd}", 96)
    result = adb.shell(cmd, timeout=10)
    log.append(f"{cmd} code={result.code} out={result.stdout.strip()!r} err={result.stderr.strip()!r}")
    log.append(
        "Новости сами рисуют поля 10% внутри Activity — отдельный freeform им не нужен."
    )
    return log


def install_news(adb: Adb, progress: Progress | None = None) -> list[str]:
    apk = news_apk()
    if not apk.exists():
        return [
            f"ChanganNews.apk не найден: {apk}. "
            f"В {SOURCE_URL} сейчас нет APK (только README). "
            "Положите ChanganNews-1.5-release.apk в папку apps/ рядом с Hub — исходники репозитория не копирую."
        ]
    lines = [f"Файл новостей: {apk} ({apk.stat().st_size} байт)"]
    if progress:
        progress(lines[0], 5)
    report = install_apk(adb, apk, already_signed=False, progress=progress, package=PACKAGE)
    lines.extend(report.log)
    if not report.ok:
        lines.append(f"Новости НЕ установлены. В списке ГУ не будет {PACKAGE}.")
        return lines
    lines.append(f"Пакет установлен. В списке ГУ: Новости · {PACKAGE}")
    lines += start_news(adb, progress=progress)
    lines.append(
        "Окно с полями 10% — внутри самого приложения (как вы обкатали). "
        "Исходники changan_news Hub не трогает."
    )
    return lines
