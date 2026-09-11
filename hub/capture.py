"""Screenshot and screen-record the Feiyu head unit over ADB.

No extra APK on the HU: ``screencap`` and ``screenrecord`` already live in
``/system/bin``. Files land in ``captures/`` next to Hub (the flash drive).

Lamore Feiyu has no ``/sdcard/Download`` — write under ``/data/local/tmp``,
the same folder Hub already uses to push APKs.
"""

from __future__ import annotations

import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from hub.adb import SHELL_PASSWORD, Adb, AdbError
from hub.paths import captures_dir

REMOTE_DIRS = (
    "/data/local/tmp",
    "/sdcard",
    "/sdcard/Download",
    "/storage/emulated/0",
)
SHOT_NAME = "changan_hub_shot.png"
REC_NAME = "changan_hub_rec.mp4"
REMOTE_REC = f"{REMOTE_DIRS[0]}/{REC_NAME}"
MAX_SECONDS = 180
DEFAULT_SECONDS = 60
BITRATE = 8_000_000

PopenFn = Callable[..., subprocess.Popen]


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def new_png() -> Path:
    return captures_dir() / f"hu-{stamp()}.png"


def new_mp4() -> Path:
    return captures_dir() / f"hu-{stamp()}.mp4"


def _clean_adb_text(text: str) -> str:
    lines = []
    for line in text.splitlines():
        low = line.lower()
        if "verify password" in low or "please input" in low:
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _write_failed(result) -> bool:
    blob = f"{result.stdout}\n{result.stderr}".lower()
    return (not result.ok) or any(
        mark in blob
        for mark in ("no such file", "read-only", "permission denied", "can't create", "cannot create")
    )


def pick_remote_dir(adb: Adb) -> str:
    """First directory on the HU that shell can actually create a file in."""
    last = ""
    for folder in REMOTE_DIRS:
        adb.shell(f"mkdir -p {folder}", timeout=8)
        probe = f"{folder}/.changan_hub_w"
        wrote = adb.shell(f"touch {probe}", timeout=8)
        if _write_failed(wrote):
            last = _clean_adb_text(wrote.text or wrote.stderr)
            continue
        adb.shell(f"rm -f {probe}", timeout=8)
        return folder
    raise AdbError(
        "На ГУ нет папки для снимка. /sdcard/Download отсутствует, "
        f"/data/local/tmp тоже не записался. {last}".strip()
    )


def take_screenshot(adb: Adb, dest: Path | None = None) -> Path:
    dest = dest or new_png()
    folder = pick_remote_dir(adb)
    remote = f"{folder}/{SHOT_NAME}"
    result = adb.screenshot(dest, remote=remote)
    if not result.ok:
        raise AdbError(
            _clean_adb_text(result.text or result.stderr) or "Не удалось снять экран ГУ"
        )
    if not dest.is_file() or dest.stat().st_size < 64:
        raise AdbError("Файл скриншота пустой. Проверьте ADB — снимок пишется в /data/local/tmp на ГУ.")
    return dest


def screenrecord_available(adb: Adb) -> bool:
    result = adb.shell("ls /system/bin/screenrecord", timeout=8)
    blob = f"{result.stdout}\n{result.stderr}".lower()
    if "no such file" in blob or "not found" in blob:
        return False
    return bool(result.ok or "screenrecord" in blob)


def interrupt_screenrecord(adb: Adb) -> None:
    """SIGINT so screenrecord finalizes the MP4 instead of leaving a broken file."""
    pid = adb.shell("pidof screenrecord", timeout=8)
    pids = [part for part in pid.stdout.split() if part.isdigit()]
    if pids:
        adb.shell("kill -INT " + " ".join(pids), timeout=8)
        return
    adb.shell("killall -INT screenrecord", timeout=8)


class Recorder:
    def __init__(self, adb: Adb) -> None:
        self.adb = adb
        self.proc: subprocess.Popen | None = None
        self.remote = REMOTE_REC
        self.local: Path | None = None
        self.limit = DEFAULT_SECONDS
        self.started_at = 0.0

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def elapsed(self) -> int:
        if not self.started_at:
            return 0
        return int(time.monotonic() - self.started_at)

    def start(
        self,
        seconds: int = DEFAULT_SECONDS,
        dest: Path | None = None,
        popen: PopenFn = subprocess.Popen,
        settle: float = 0.8,
    ) -> Path:
        if self.running:
            raise AdbError("Запись уже идёт. Сначала нажмите «Стоп».")
        seconds = max(5, min(MAX_SECONDS, int(seconds)))
        if not screenrecord_available(self.adb):
            raise AdbError(
                "На ГУ нет /system/bin/screenrecord. Видео эта прошивка не пишет — "
                "снимите скриншот."
            )
        folder = pick_remote_dir(self.adb)
        self.remote = f"{folder}/{REC_NAME}"
        self.adb.shell(f"rm -f {self.remote}", timeout=8)
        dest = dest or new_mp4()
        dest.parent.mkdir(parents=True, exist_ok=True)
        argv = self.adb.prefix() + [
            "shell",
            f"screenrecord --bit-rate {BITRATE} --time-limit {seconds} {self.remote}",
        ]
        proc = popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        if proc.stdin:
            try:
                proc.stdin.write(f"{SHELL_PASSWORD}\n".encode("utf-8"))
                proc.stdin.flush()
                proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass
        if settle > 0:
            time.sleep(settle)
        code = proc.poll()
        if code is not None:
            err = b""
            if proc.stderr:
                try:
                    err = proc.stderr.read() or b""
                except OSError:
                    err = b""
            text = err.decode("utf-8", "replace") if isinstance(err, (bytes, bytearray)) else str(err)
            raise AdbError(
                _clean_adb_text(text) or f"screenrecord сразу вышел (code {code})"
            )
        self.proc = proc
        self.local = dest
        self.limit = seconds
        self.started_at = time.monotonic()
        return dest

    def stop(self, flush_wait: float = 1.2) -> Path:
        dest = self.local or new_mp4()
        try:
            interrupt_screenrecord(self.adb)
        except AdbError:
            pass
        proc = self.proc
        self.proc = None
        if proc is not None:
            try:
                proc.wait(timeout=12)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
        if flush_wait > 0:
            time.sleep(flush_wait)
        dest.parent.mkdir(parents=True, exist_ok=True)
        pulled = self.adb.raw(["pull", self.remote, str(dest)], timeout=60)
        try:
            self.adb.shell(f"rm -f {self.remote}", timeout=8)
        except AdbError:
            pass
        self.started_at = 0.0
        if not pulled.ok:
            raise AdbError(_clean_adb_text(pulled.text or pulled.stderr) or "Не удалось скачать видео с ГУ")
        if not dest.is_file() or dest.stat().st_size < 256:
            raise AdbError(
                "Видеофайл пустой. Запись короче секунды часто не успевает закрыться — "
                "повторите и подождите 2–3 с перед «Стоп»."
            )
        return dest
