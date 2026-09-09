"""Filesystem helpers for Changan Hub."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def app_data() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    path = base / "ChanganHub"
    path.mkdir(parents=True, exist_ok=True)
    return path


def bundled_apps() -> Path:
    path = ROOT / "apps"
    path.mkdir(parents=True, exist_ok=True)
    return path


def logs_dir() -> Path:
    path = app_data() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path
