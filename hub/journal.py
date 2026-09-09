"""Persistent debug journal: every user action and ADB call."""

from __future__ import annotations

import json
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Callable

from hub.paths import logs_dir

Listener = Callable[[str], None]


class Journal:
    def __init__(self) -> None:
        self.path = logs_dir() / "hub.log"
        self.dated = logs_dir() / f"hub-{datetime.now().strftime('%Y-%m-%d')}.log"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._listeners: list[Listener] = []
        self.write("INFO", "journal", f"журнал на флешке: {self.path}")

    def subscribe(self, fn: Listener) -> None:
        self._listeners.append(fn)

    def write(self, level: str, event: str, message: str, **extra: object) -> str:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        line = f"{ts} [{level:<5}] {event}: {message}"
        if extra:
            try:
                dumped = json.dumps(extra, ensure_ascii=False, default=str)
            except TypeError:
                dumped = str(extra)
            line += " " + dumped
        with self._lock:
            for target in (self.path, self.dated):
                with target.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
                    handle.flush()
        for fn in list(self._listeners):
            try:
                fn(line)
            except Exception:
                pass
        return line

    def action(self, name: str, detail: str = "") -> None:
        self.write("ACTION", "ui", name if not detail else f"{name} — {detail}")

    def adb(self, argv: list[str], stdout: str, stderr: str, code: int, elapsed_ms: int) -> None:
        out = (stdout or "").strip()
        err = (stderr or "").strip()
        if len(out) > 4000:
            out = out[:4000] + "…(обрезано)"
        if len(err) > 2000:
            err = err[:2000] + "…(обрезано)"
        self.write(
            "ADB",
            "cmd",
            " ".join(argv),
            code=code,
            ms=elapsed_ms,
            stdout=out,
            stderr=err,
        )

    def error(self, event: str, exc: BaseException) -> None:
        self.write("ERROR", event, f"{type(exc).__name__}: {exc}")
        self.write("ERROR", event, traceback.format_exc())
