"""Screenshot and screen-record the Feiyu head unit over ADB.

No extra APK on the HU: ``screencap`` and ``screenrecord`` already live in
``/system/bin``. Files land in ``captures/`` next to Hub (the flash drive).

Screenshots go to ``/data/local/tmp`` (Feiyu has no ``/sdcard/Download``).
Video prefers ``/storage/emulated/0/Download`` so the media encoder can write.
Native Lamore pixels are 1440×1920 — that size returns Encoder failed (-38),
so we ask screenrecord for 720×960 (same 3:4, multiples of 16).
"""

from __future__ import annotations

import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from hub.adb import SHELL_PASSWORD, Adb, AdbError
from hub.gifutil import write_gif
from hub.paths import captures_dir

REMOTE_DIRS = (
    "/data/local/tmp",
    "/sdcard",
    "/sdcard/Download",
    "/storage/emulated/0",
)
VIDEO_DIRS = (
    "/storage/emulated/0/Download",
    "/storage/emulated/0",
    "/data/local/tmp",
)
SHOT_NAME = "changan_hub_shot.png"
REC_NAME = "changan_hub_rec.mp4"
REMOTE_REC = f"{VIDEO_DIRS[0]}/{REC_NAME}"
MAX_SECONDS = 180
DEFAULT_SECONDS = 60
BITRATE = 4_000_000
CAPTURE_VERSION = 4

PopenFn = Callable[..., subprocess.Popen]


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def new_png() -> Path:
    return captures_dir() / f"hu-{stamp()}.png"


def new_gif() -> Path:
    return captures_dir() / f"hu-{stamp()}.gif"


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


def pick_remote_dir(adb: Adb, folders: tuple[str, ...] = REMOTE_DIRS) -> str:
    """First directory on the HU that shell can actually create a file in."""
    last = ""
    for folder in folders:
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


def parse_wm_size(text: str) -> tuple[int, int] | None:
    override: tuple[int, int] | None = None
    physical: tuple[int, int] | None = None
    for line in text.splitlines():
        low = line.lower()
        if "x" not in low:
            continue
        part = line.split(":")[-1].strip().lower().replace(" ", "")
        if "x" not in part:
            continue
        left, right = part.split("x", 1)
        if not (left.isdigit() and right.isdigit()):
            continue
        pair = (int(left), int(right))
        if "override" in low:
            override = pair
        else:
            physical = physical or pair
    return override or physical


def _align16(value: int) -> int:
    return max(16, value - (value % 16))


def record_size_candidates(width: int | None, height: int | None) -> list[str]:
    """Sizes the Feiyu H.264 encoder is likely to accept.

    Lamore is 1440×1920. Native screenrecord returns Encoder failed (err=-38),
    INVALID_OPERATION. Landscape 1280×720 is the usual MTK profile; 720×960
    keeps the 3:4 picture.
    """
    pairs: list[tuple[int, int]] = [
        (1280, 720),
        (800, 480),
        (720, 960),
        (640, 480),
    ]
    if width and height and width > 0 and height > 0:
        for max_side in (1280, 960, 720):
            scale = min(1.0, max_side / max(width, height))
            pairs.append((_align16(int(width * scale)), _align16(int(height * scale))))
    out: list[str] = []
    seen: set[str] = set()
    for wide, high in pairs:
        key = f"{wide}x{high}"
        if key in seen or wide < 16 or high < 16:
            continue
        seen.add(key)
        out.append(key)
    return out


def display_size(adb: Adb) -> tuple[int, int] | None:
    result = adb.shell("wm size", timeout=8)
    return parse_wm_size(f"{result.stdout}\n{result.stderr}")


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


def _encoder_failed(text: str) -> bool:
    low = text.lower()
    return (
        "encoder failed" in low
        or "err=-38" in low
        or "unable to configure" in low
        or "error starting encoder" in low
        or "unable to start encoder" in low
    )


class Recorder:
    def __init__(self, adb: Adb) -> None:
        self.adb = adb
        self.proc: subprocess.Popen | None = None
        self.remote = REMOTE_REC
        self.local: Path | None = None
        self.limit = DEFAULT_SECONDS
        self.started_at = 0.0
        self.size = ""
        self.mode = "screenrecord"
        self._stop_frames = False
        self._frame_thread: threading.Thread | None = None
        self._frames: list[Path] = []
        self._shot_remote = f"{REMOTE_DIRS[0]}/{SHOT_NAME}"

    def _note(self, argv: list[str], stderr: str = "") -> None:
        if self.adb.on_log:
            self.adb.on_log(argv, f"capture v{CAPTURE_VERSION}", stderr, -1, 0)

    @property
    def running(self) -> bool:
        if self.mode == "frames":
            return (
                self._frame_thread is not None
                and self._frame_thread.is_alive()
                and not self._stop_frames
            )
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
        dest = dest or new_mp4()
        dest.parent.mkdir(parents=True, exist_ok=True)
        self._note(["capture", f"v{CAPTURE_VERSION}", "start", str(seconds)])
        if screenrecord_available(self.adb):
            started = self._start_screenrecord(seconds, dest, popen, settle)
            if started is not None:
                return started
        return self._start_frames(seconds, dest.with_suffix(".gif"))

    def _start_screenrecord(
        self,
        seconds: int,
        dest: Path,
        popen: PopenFn,
        settle: float,
    ) -> Path | None:
        folder = pick_remote_dir(self.adb, VIDEO_DIRS)
        self.remote = f"{folder}/{REC_NAME}"
        width_height = display_size(self.adb)
        sizes = record_size_candidates(*(width_height or (None, None)))
        bitrates = (BITRATE, 2_000_000)
        last_err = "screenrecord сразу вышел"
        for size in sizes:
            for rate in bitrates:
                try:
                    interrupt_screenrecord(self.adb)
                except AdbError:
                    pass
                self.adb.shell(f"rm -f {self.remote}", timeout=8)
                argv = self.adb.prefix() + [
                    "shell",
                    (
                        f"screenrecord --size {size} --bit-rate {rate} "
                        f"--time-limit {seconds} {self.remote}"
                    ),
                ]
                self._note(argv, "screenrecord start")
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
                if code is None:
                    self.mode = "screenrecord"
                    self.proc = proc
                    self.local = dest
                    self.limit = seconds
                    self.size = size
                    self.started_at = time.monotonic()
                    return dest
                err = b""
                if proc.stderr:
                    try:
                        err = proc.stderr.read() or b""
                    except OSError:
                        err = b""
                text = err.decode("utf-8", "replace") if isinstance(err, (bytes, bytearray)) else str(err)
                last_err = _clean_adb_text(text) or f"screenrecord сразу вышел (code {code})"
                self._note(argv, last_err)
                if not _encoder_failed(last_err) and "no such file" not in last_err.lower():
                    raise AdbError(last_err)
        self._note(["capture", f"v{CAPTURE_VERSION}", "fallback-gif"], last_err)
        return None

    def _start_frames(self, seconds: int, dest: Path) -> Path:
        folder = pick_remote_dir(self.adb)
        self._shot_remote = f"{folder}/{SHOT_NAME}"
        self.mode = "frames"
        self.local = dest
        self.limit = seconds
        self._stop_frames = False
        self._frames = []
        self.started_at = time.monotonic()
        self._frame_thread = threading.Thread(target=self._loop_frames, daemon=True, name="hub-frames")
        self._frame_thread.start()
        return dest

    def _loop_frames(self) -> None:
        index = 0
        while not self._stop_frames and self.elapsed() < self.limit:
            frame = captures_dir() / f".hub-frame-{index:04d}.png"
            try:
                result = self.adb.screenshot(frame, remote=self._shot_remote)
                if result.ok and frame.is_file() and frame.stat().st_size >= 64:
                    self._frames.append(frame)
                    index += 1
                    self._note(["screencap", f"frame {index}"], str(frame.name))
            except AdbError as exc:
                self._note(["screencap"], str(exc))
                break
            end = time.monotonic() + 0.4
            while time.monotonic() < end and not self._stop_frames:
                time.sleep(0.05)

    def stop(self, flush_wait: float = 1.2) -> Path:
        if self.mode == "frames":
            return self._stop_frames_gif()
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

    def _stop_frames_gif(self) -> Path:
        self._stop_frames = True
        thread = self._frame_thread
        self._frame_thread = None
        if thread is not None:
            thread.join(timeout=40)
        dest = self.local or new_gif()
        frames = list(self._frames)
        self._frames = []
        self.started_at = 0.0
        if not frames:
            raise AdbError("Не удалось снять ни одного кадра для ролика.")
        delay = max(2, int(100 * self.limit / max(len(frames), 1)))
        write_gif(frames, dest, delay_cs=min(200, delay))
        for path in frames:
            try:
                path.unlink()
            except OSError:
                pass
        if not dest.is_file() or dest.stat().st_size < 32:
            raise AdbError("GIF ролика пустой.")
        return dest
