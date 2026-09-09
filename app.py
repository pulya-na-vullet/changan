#!/usr/bin/env python3
"""Запуск Changan Hub: python app.py"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _prepare() -> None:
    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))


def main() -> None:
    _prepare()
    try:
        from hub.gui import main as gui_main
    except ModuleNotFoundError as exc:
        missing = exc.name or ""
        if missing in {"cryptography", "hub"}:
            print("Сначала установите зависимости:")
            print(f"  {sys.executable} -m pip install -r \"{ROOT / 'requirements.txt'}\"")
            raise SystemExit(1) from exc
        raise
    gui_main()


if __name__ == "__main__":
    main()
