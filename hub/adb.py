"""ADB client tailored to Changan Feiyu head units."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

SHELL_PASSWORD = "adb36987"
ENGINEERING_CODE = "*#*#888"
ENGINEERING_PIN = "369875"

LAUNCHER_PACKAGES = (
    "com.iflytek.autofly.launcher",
    "com.android.launcher3",
    "com.changan.launcher",
    "com.tinnove.launcher",
)

LogFn = Callable[[list[str], str, str, int, int], None]


@dataclass
class CommandResult:
    ok: bool
    stdout: str
    stderr: str
    code: int
    argv: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return (self.stdout or self.stderr or "").strip()


class AdbError(RuntimeError):
    pass


def _adb_candidates() -> list[Path]:
    found: list[Path] = []
    which = shutil.which("adb")
    if which:
        found.append(Path(which))
    extra = [
        Path("/tmp/android-sdk/platform-tools/adb"),
        Path.home() / "AppData" / "Local" / "Android" / "Sdk" / "platform-tools" / "adb.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Android" / "Sdk" / "platform-tools" / "adb.exe",
        Path(os.environ.get("ANDROID_HOME", "")) / "platform-tools" / "adb.exe",
        Path(os.environ.get("ANDROID_HOME", "")) / "platform-tools" / "adb",
        Path(sys.executable).resolve().parent / "adb.exe",
        Path.cwd() / "platform-tools" / "adb.exe",
        Path.cwd() / "adb.exe",
    ]
    for item in extra:
        if item and item.exists():
            found.append(item)
    uniq: list[Path] = []
    seen: set[str] = set()
    for item in found:
        key = str(item)
        if key not in seen:
            uniq.append(item)
            seen.add(key)
    return uniq


def _no_adb_target(text: str) -> bool:
    """True when adb has no HU — extra password/exec-out retries only waste time."""
    low = (text or "").lower()
    return (
        "no devices/emulators found" in low
        or "no devices found" in low
        or "device not found" in low
        or ("device" in low and "not found" in low)
        or "device offline" in low
    )


def _run_kwargs() -> dict:
    return {
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }


class Adb:
    def __init__(
        self,
        binary: str | Path | None = None,
        serial: str | None = None,
        on_log: LogFn | None = None,
    ) -> None:
        self.serial = serial
        self.on_log = on_log
        if binary:
            self.binary = Path(binary)
        else:
            cands = _adb_candidates()
            if not cands:
                raise AdbError(
                    "adb не найден. Положите platform-tools в PATH или рядом с программой."
                )
            self.binary = cands[0]
        self.last_password_used = False

    def prefix(self) -> list[str]:
        cmd = [str(self.binary)]
        if self.serial:
            cmd += ["-s", self.serial]
        return cmd

    def raw(self, args: list[str], timeout: int = 45, input_text: str | None = None) -> CommandResult:
        argv = self.prefix() + args
        started = time.monotonic()
        if self.on_log:
            self.on_log(argv, "", f"запущен, жду ответ (лимит {timeout}с)…", -1, 0)
        try:
            proc = subprocess.run(
                argv,
                input=input_text,
                timeout=timeout,
                **_run_kwargs(),
            )
        except FileNotFoundError as exc:
            raise AdbError(f"Не удалось запустить adb: {exc}") from exc
        except OSError as exc:
            elapsed = int((time.monotonic() - started) * 1000)
            winerr = getattr(exc, "winerror", None)
            code = 206 if winerr == 206 else (exc.errno or 1)
            stderr = f"{type(exc).__name__}: {exc}"
            result = CommandResult(False, "", stderr, code, argv)
            if self.on_log:
                self.on_log(argv, result.stdout, result.stderr, result.code, elapsed)
            return result
        except subprocess.TimeoutExpired as exc:
            elapsed = int((time.monotonic() - started) * 1000)
            stdout = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = f"timeout after {timeout}s"
            result = CommandResult(False, stdout, stderr, 124, argv)
            if self.on_log:
                self.on_log(argv, result.stdout, result.stderr, result.code, elapsed)
            return result
        elapsed = int((time.monotonic() - started) * 1000)
        result = CommandResult(
            proc.returncode == 0,
            proc.stdout or "",
            proc.stderr or "",
            proc.returncode,
            argv,
        )
        if self.on_log:
            self.on_log(argv, result.stdout, result.stderr, result.code, elapsed)
        return result

    def start_server(self) -> CommandResult:
        return self.raw(["start-server"], timeout=20)

    def kill_server(self) -> CommandResult:
        return self.raw(["kill-server"], timeout=20)

    def devices(self) -> list[dict[str, str]]:
        result = self.raw(["devices", "-l"], timeout=15)
        rows: list[dict[str, str]] = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("List of devices"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            rows.append({"serial": parts[0], "state": parts[1], "raw": line})
        return rows

    def connected(self) -> bool:
        return any(d["state"] == "device" for d in self.devices())

    def pick_serial(self) -> str | None:
        ready = [d for d in self.devices() if d["state"] == "device"]
        if not ready:
            unauthorized = [d for d in self.devices() if d["state"] == "unauthorized"]
            if unauthorized:
                raise AdbError(
                    "Устройство unauthorized. На ГУ подтвердите отладку по USB, если появится запрос."
                )
            return None
        if self.serial and any(d["serial"] == self.serial for d in ready):
            return self.serial
        self.serial = ready[0]["serial"]
        return self.serial

    def wait_for_device(self, seconds: int = 20) -> bool:
        deadline = time.time() + seconds
        while time.time() < deadline:
            if self.connected():
                self.pick_serial()
                return True
            time.sleep(1)
        return False

    def needs_password(self, text: str) -> bool:
        lower = text.lower()
        return "verify password" in lower or "please input" in lower

    def _strip_password_banner(self, text: str) -> str:
        lines = []
        for line in text.splitlines():
            low = line.lower()
            if "verify password" in low or "please input" in low:
                continue
            lines.append(line)
        return "\n".join(lines)

    def shell(self, command: str, timeout: int = 12) -> CommandResult:
        """Run a remote command the way Feiyu actually accepts it.

        Interactive ``adb shell`` (no command) hangs on this HU until timeout.
        Working form from the community: pipe the password into
        ``adb shell <command>``.
        """
        self.last_password_used = True
        attempts: list[tuple[list[str], str | None]] = [
            (["shell", command], f"{SHELL_PASSWORD}\n"),
            (["shell", command], f"{SHELL_PASSWORD}\r\n"),
            (["shell", command], None),
            (["exec-out", command], f"{SHELL_PASSWORD}\n"),
            (["exec-out", command], None),
        ]
        last = CommandResult(False, "", "shell not attempted", 1, [])
        for args, stdin in attempts:
            last = self.raw(args, timeout=timeout, input_text=stdin)
            blob = (last.stdout + "\n" + last.stderr).lower()
            stdout = self._strip_password_banner(last.stdout)
            stderr = self._strip_password_banner(last.stderr)
            body = (stdout + "\n" + stderr).lower()
            if last.code == 124:
                # One hang is enough. Retrying 4 stdin variants used to freeze
                # the UI for timeout×5 (pm install 25s → 125s of a dead queue).
                return CommandResult(False, stdout, stderr or last.stderr, 124, last.argv)
            if _no_adb_target(blob):
                return CommandResult(False, stdout, stderr, last.code, last.argv)
            if "security exception" in body or "securityexception" in body:
                return CommandResult(False, stdout, stderr, last.code, last.argv)
            if "illegalargumentexception" in body or "unknown package" in body or "exception occurred" in body:
                return CommandResult(False, stdout, stderr, last.code, last.argv)
            # Feiyu prints "please input verify password: verify success!" on
            # stderr even when the command succeeded with empty stdout (appops).
            # That used to look like "need password" and we retried until hang.
            verified = "verify success" in blob
            asked = self.needs_password(last.stdout + "\n" + last.stderr)
            if last.code == 0 and (verified or not asked):
                return CommandResult(True, stdout, stderr, 0, last.argv)
            body = (stdout + "\n" + stderr).lower()
            if "not auth" in body or "install failed" in body or "failure [" in body:
                return CommandResult(False, stdout, stderr, last.code, last.argv)
            if asked and not verified and not stdout.strip():
                continue
            ok = last.code == 0 or "success" in body or bool(stdout.strip())
            if ok or stdout.strip() or "error" in body:
                return CommandResult(ok, stdout, stderr, last.code, last.argv)
        stdout = self._strip_password_banner(last.stdout)
        stderr = self._strip_password_banner(last.stderr)
        return CommandResult(False, stdout, stderr, last.code, last.argv)

    def getprop(self, name: str) -> str:
        result = self.shell(f"getprop {name}", timeout=8)
        lines = [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
        return lines[-1] if lines else ""

    def props(self) -> dict[str, str]:
        keys = {
            "brand": "ro.product.brand",
            "model": "ro.product.model",
            "device": "ro.product.device",
            "android": "ro.build.version.release",
            "sdk": "ro.build.version.sdk",
            "cpu": "ro.product.cpu.abi",
        }
        parsed = {label: self.getprop(prop) for label, prop in keys.items()}
        return parsed

    def push(self, local: Path, remote: str, timeout: int = 40) -> CommandResult:
        # Do not send stdin: adb may wait for file data and hang.
        return self.raw(["push", str(local), remote], timeout=timeout)

    def install_stream(self, apk: Path, timeout: int = 8) -> CommandResult:
        return self.raw(
            ["install", "-r", "-t", "-g", "--no-streaming", str(apk)],
            timeout=timeout,
        )

    def screenshot(self, dest: Path, remote: str | None = None) -> CommandResult:
        # Feiyu has no /sdcard/Download (user log: "No such file or directory").
        # /data/local/tmp already works for APK push on this HU.
        remote = remote or "/data/local/tmp/changan_hub_shot.png"
        folder = remote.rsplit("/", 1)[0]
        self.shell(f"mkdir -p {folder}", timeout=8)
        shot = self.shell(f"screencap -p {remote}", timeout=20)
        if not shot.ok:
            return shot
        dest.parent.mkdir(parents=True, exist_ok=True)
        pulled = self.raw(["pull", remote, str(dest)], timeout=30)
        self.shell(f"rm -f {remote}", timeout=8)
        return pulled

    def packages(self) -> list[str]:
        result = self.shell("pm list packages", timeout=25)
        names = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("package:"):
                names.append(line.split(":", 1)[1])
        return sorted(names)

    def package_path(self, package: str) -> str:
        result = self.shell(f"pm path {package}", timeout=15)
        for line in result.stdout.splitlines():
            if line.startswith("package:"):
                return line.split(":", 1)[1].strip()
        return ""

    def launch(self, package: str) -> CommandResult:
        return self.shell(f"monkey -p {package} -c android.intent.category.LAUNCHER 1")

    def clear_launcher_cache(self) -> list[CommandResult]:
        results = []
        installed = set(self.packages())
        for pkg in LAUNCHER_PACKAGES:
            if pkg in installed:
                results.append(self.shell(f"pm clear {pkg}"))
        if not results:
            results.append(CommandResult(True, "лаунчер из списка не найден", "", 0, []))
        return results

    def try_root(self) -> CommandResult:
        return self.raw(["root"], timeout=20)

    def try_remount(self) -> CommandResult:
        return self.raw(["remount"], timeout=20)

    def reboot(self) -> CommandResult:
        return self.raw(["reboot"], timeout=20)
