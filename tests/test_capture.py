from pathlib import Path

from hub.adb import SHELL_PASSWORD, AdbError, CommandResult
from hub.capture import (
    BITRATE,
    MAX_SECONDS,
    REMOTE_REC,
    Recorder,
    interrupt_screenrecord,
    screenrecord_available,
    take_screenshot,
)
from hub.paths import ROOT, captures_dir, logs_dir


class FakeAdb:
    def __init__(self, has_record: bool = True, shot_bytes: bytes | None = None) -> None:
        self.cmds: list[str] = []
        self.raws: list[list[str]] = []
        self.has_record = has_record
        self.shot_bytes = shot_bytes if shot_bytes is not None else b"\x89PNG\r\n" + b"x" * 200
        self.pidof = "4242"
        self.pull_bytes = b"ftypisom" + b"0" * 400
        self.binary = Path("/usr/bin/adb")
        self.serial = "HU123"

    def prefix(self) -> list[str]:
        return ["adb", "-s", self.serial]

    def screenshot(self, dest: Path) -> CommandResult:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.shot_bytes)
        return CommandResult(True, f"pulled {dest}", "", 0, ["pull"])

    def shell(self, command: str, timeout: int = 12) -> CommandResult:
        self.cmds.append(command)
        if command.startswith("ls /system/bin/screenrecord"):
            if self.has_record:
                return CommandResult(True, "/system/bin/screenrecord", "", 0, ["shell"])
            return CommandResult(False, "", "No such file or directory", 1, ["shell"])
        if command.startswith("pidof screenrecord"):
            return CommandResult(True, self.pidof, "", 0, ["shell"])
        return CommandResult(True, "", "", 0, ["shell"])

    def raw(self, args: list[str], timeout: int = 45, input_text: str | None = None) -> CommandResult:
        self.raws.append(list(args))
        if args and args[0] == "pull":
            dest = Path(args[2])
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(self.pull_bytes)
            return CommandResult(True, "1 file pulled", "", 0, args)
        return CommandResult(True, "", "", 0, args)


class DummyProc:
    def __init__(self, exit_immediately: bool = False) -> None:
        self.stdin = _Pipe()
        self.stderr = _Pipe()
        self._code: int | None = 1 if exit_immediately else None

    def poll(self) -> int | None:
        return self._code

    def wait(self, timeout: float | None = None) -> int:
        self._code = 0
        return 0

    def kill(self) -> None:
        self._code = 9


class _Pipe:
    def __init__(self) -> None:
        self.data = b""
        self.closed = False

    def write(self, blob: bytes) -> int:
        self.data += blob
        return len(blob)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    def read(self) -> bytes:
        return b"screenrecord: not found"


def test_logs_and_captures_live_next_to_app() -> None:
    assert logs_dir() == ROOT / "logs"
    assert captures_dir() == ROOT / "captures"
    assert captures_dir().is_dir()


def test_screenshot_writes_png(tmp_path: Path) -> None:
    adb = FakeAdb()
    dest = tmp_path / "shot.png"
    out = take_screenshot(adb, dest)  # type: ignore[arg-type]
    assert out == dest
    assert dest.stat().st_size >= 64


def test_screenshot_rejects_empty(tmp_path: Path) -> None:
    adb = FakeAdb(shot_bytes=b"tiny")
    dest = tmp_path / "empty.png"
    try:
        take_screenshot(adb, dest)  # type: ignore[arg-type]
        raise AssertionError("empty shot must fail")
    except AdbError as exc:
        assert "пустой" in str(exc)


def test_screenrecord_available() -> None:
    assert screenrecord_available(FakeAdb(has_record=True)) is True  # type: ignore[arg-type]
    assert screenrecord_available(FakeAdb(has_record=False)) is False  # type: ignore[arg-type]


def test_recorder_start_stop(tmp_path: Path) -> None:
    adb = FakeAdb()
    rec = Recorder(adb)  # type: ignore[arg-type]
    dest = tmp_path / "demo.mp4"
    procs: list[DummyProc] = []

    def popen(argv, **kwargs):
        assert argv[:3] == ["adb", "-s", "HU123"]
        assert argv[3] == "shell"
        assert f"--time-limit {MAX_SECONDS}" not in argv[4]
        assert f"--bit-rate {BITRATE}" in argv[4]
        assert REMOTE_REC in argv[4]
        assert "--time-limit 30" in argv[4]
        proc = DummyProc()
        procs.append(proc)
        return proc

    out = rec.start(30, dest=dest, popen=popen, settle=0)
    assert out == dest
    assert rec.running
    assert procs[0].stdin.data.decode().startswith(SHELL_PASSWORD)
    assert procs[0].stdin.closed
    assert any(cmd.startswith("rm -f") for cmd in adb.cmds)

    saved = rec.stop(flush_wait=0)
    assert saved == dest
    assert dest.stat().st_size >= 256
    assert not rec.running
    assert any(cmd.startswith("kill -INT") for cmd in adb.cmds)
    assert adb.raws[0][0] == "pull"


def test_recorder_missing_binary() -> None:
    rec = Recorder(FakeAdb(has_record=False))  # type: ignore[arg-type]
    try:
        rec.start(20, popen=lambda *a, **k: DummyProc(), settle=0)
        raise AssertionError("missing screenrecord must fail")
    except AdbError as exc:
        assert "screenrecord" in str(exc)


def test_recorder_exits_immediately() -> None:
    rec = Recorder(FakeAdb())  # type: ignore[arg-type]

    def popen(*_a, **_k):
        return DummyProc(exit_immediately=True)

    try:
        rec.start(20, popen=popen, settle=0)
        raise AssertionError("immediate exit must fail")
    except AdbError as exc:
        assert "screenrecord" in str(exc).lower() or "code" in str(exc)


def test_interrupt_uses_pidof() -> None:
    adb = FakeAdb()
    adb.pidof = "11 12"
    interrupt_screenrecord(adb)  # type: ignore[arg-type]
    assert "kill -INT 11 12" in adb.cmds


def test_cli_registers_capture_commands() -> None:
    from hub.cli import main

    try:
        main(["screenshot", "--help"])
    except SystemExit as exc:
        assert exc.code == 0
    try:
        main(["record", "--help"])
    except SystemExit as exc:
        assert exc.code == 0
