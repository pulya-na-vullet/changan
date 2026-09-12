"""USB flash drives next to Hub (Windows) or mounted volumes (Linux)."""

from __future__ import annotations

import os
from pathlib import Path

from hub.paths import ROOT

SKIP_DIRS = {
    ".venv",
    ".git",
    "__pycache__",
    "windows",
    "system volume information",
    "$recycle.bin",
    "android",
    "build",
    "lost.dir",
    "system",
    "node_modules",
}


def removable_roots() -> list[Path]:
    roots: list[Path] = []
    if os.name == "nt":
        try:
            import ctypes

            bitmask = int(ctypes.windll.kernel32.GetLogicalDrives())
            get_type = ctypes.windll.kernel32.GetDriveTypeW
            for index in range(26):
                if bitmask & (1 << index):
                    letter = f"{chr(ord('A') + index)}:\\"
                    # 2 = DRIVE_REMOVABLE
                    if int(get_type(letter)) == 2:
                        path = Path(letter)
                        if path.exists():
                            roots.append(path)
        except Exception:
            pass
        drive = Path(str(ROOT)[:3]) if len(str(ROOT)) >= 3 else ROOT
        if drive.exists() and drive not in roots:
            roots.insert(0, drive)
    else:
        for base in (Path("/media"), Path("/run/media")):
            if not base.is_dir():
                continue
            try:
                children = list(base.iterdir())
            except OSError:
                continue
            nested: list[Path] = []
            for child in children:
                if not child.is_dir() or child.name.startswith("."):
                    continue
                nested.append(child)
                try:
                    nested.extend(p for p in child.iterdir() if p.is_dir())
                except OSError:
                    pass
            for child in nested:
                if child not in roots:
                    roots.append(child)
        if ROOT not in roots:
            roots.append(ROOT)
    return roots


def list_usb_apks(limit: int = 200) -> list[Path]:
    found: list[Path] = []
    for root in removable_roots():
        _walk(root, found, depth=0, limit=limit)
        if len(found) >= limit:
            break
    return found[:limit]


def _walk(folder: Path, found: list[Path], depth: int, limit: int) -> None:
    if len(found) >= limit or depth > 5:
        return
    try:
        entries = list(folder.iterdir())
    except OSError:
        return
    for item in entries:
        if len(found) >= limit:
            return
        name = item.name.lower()
        if item.is_dir():
            if name in SKIP_DIRS or name.startswith("."):
                continue
            _walk(item, found, depth + 1, limit)
        elif name.endswith((".apk", ".xapk", ".apkm", ".apks")) and item.is_file() and item.stat().st_size > 0:
            found.append(item)
