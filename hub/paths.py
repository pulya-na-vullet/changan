"""Filesystem helpers. Everything portable lives next to app.py (flash drive)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def app_data() -> Path:
    path = ROOT / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def bundled_apps() -> Path:
    path = ROOT / "apps"
    path.mkdir(parents=True, exist_ok=True)
    return path


def logs_dir() -> Path:
    path = ROOT / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path
