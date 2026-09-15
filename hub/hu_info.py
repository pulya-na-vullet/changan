"""Installed package versions on the head unit."""

from __future__ import annotations

from hub.adb import Adb


def parse_version_name(dumpsys: str) -> str | None:
    for line in (dumpsys or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("versionName="):
            return stripped.split("=", 1)[1].strip().split()[0]
        if " versionName=" in stripped:
            return stripped.split("versionName=", 1)[1].strip().split()[0]
    return None


def installed_version(adb: Adb, package: str) -> str | None:
    present = adb.shell(f"pm path {package}", timeout=8)
    blob = f"{present.stdout or ''}\n{present.stderr or ''}"
    if "package:" not in blob:
        return None
    info = adb.shell(f"dumpsys package {package}", timeout=12)
    version = parse_version_name(info.stdout or "")
    return version or "стоит"
