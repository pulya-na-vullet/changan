"""ADB client tailored to Changan Feiyu head units."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

SHELL_PASSWORD = "adb36987"
ENGINEERING_CODE = "*#*#888"
ENGINEERING_PIN = "369875"

LAUNCHER_PACKAGES = (
    "com.iflytek.autofly.launcher",
    "com.android.launcher3",
    "com.changan.launcher",
    "com.tinnove.launcher",
)


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
    # unique preserve order
    uniq: list[Path] = []
    seen: set[str] = set()
    for item in found:
        key = str(item)
        if key not in seen:
            uniq.append(item)
            seen.add(key)
    return uniq


class Adb:
    def __init__(self, binary: str | Path | None = None, serial: str | None = None) -> None:
        self.serial = serial
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
        try:
            proc = subprocess.run(
                argv,
                input=input_text,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace",
            )
        except FileNotFoundError as exc:
            raise AdbError(f"Не удалось запустить adb: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            return CommandResult(False, "", f"timeout: {exc}", 124, argv)
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        return CommandResult(proc.returncode == 0, stdout, stderr, proc.returncode, argv)

    def start_server(self) -> CommandResult:
        return self.raw(["start-server"], timeout=20)

    def kill_server(self) -> CommandResult:
        return self.raw(["kill-server"], timeout=20)

    def devices(self) -> list[dict[str, str]]:
        result = self.raw(["devices", "-l"])
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
        if self.serial:
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

    def shell(self, command: str, timeout: int = 60) -> CommandResult:
        """Run a shell command, answering the Changan adbd password prompt."""
        first = self.raw(["shell", command], timeout=timeout)
        blob = first.stdout + first.stderr
        if first.ok and not self.needs_password(blob):
            return first
        # Interactive password: feed password then the command.
        argv = self.prefix() + ["shell"]
        try:
            proc = subprocess.run(
                argv,
                input=f"{SHELL_PASSWORD}\n{command}\nexit\n",
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace",
            )
        except subprocess.TimeoutExpired as exc:
            return CommandResult(False, "", f"timeout: {exc}", 124, argv)
        self.last_password_used = True
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        ok = proc.returncode == 0 and "error" not in (stdout + stderr).lower()
        # pm install prints Success with return code 0
        if "Success" in stdout:
            ok = True
        return CommandResult(ok, stdout, stderr, proc.returncode, argv)

    def getprop(self, name: str) -> str:
        return self.shell(f"getprop {name}").stdout.strip()

    def props(self) -> dict[str, str]:
        keys = {
            "brand": "ro.product.brand",
            "model": "ro.product.model",
            "device": "ro.product.device",
            "android": "ro.build.version.release",
            "sdk": "ro.build.version.sdk",
            "fingerprint": "ro.build.fingerprint",
            "cpu": "ro.product.cpu.abi",
            "language": "persist.sys.language",
            "locale": "ro.product.locale",
        }
        return {label: self.getprop(prop) for label, prop in keys.items()}

    def push(self, local: Path, remote: str, timeout: int = 180) -> CommandResult:
        result = self.raw(["push", str(local), remote], timeout=timeout)
        if result.ok and not self.needs_password(result.stdout + result.stderr):
            return result
        # Some builds prompt before push
        argv = self.prefix() + ["push", str(local), remote]
        proc = subprocess.run(
            argv,
            input=f"{SHELL_PASSWORD}\n",
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        return CommandResult(
            proc.returncode == 0, proc.stdout or "", proc.stderr or "", proc.returncode, argv
        )

    def install_stream(self, apk: Path, timeout: int = 180) -> CommandResult:
        return self.raw(["install", "-r", "-t", "-g", "--no-streaming", str(apk)], timeout=timeout)

    def screenshot(self, dest: Path) -> CommandResult:
        remote = "/sdcard/Download/changan_hub_shot.png"
        shot = self.shell(f"screencap -p {remote}")
        if not shot.ok:
            return shot
        dest.parent.mkdir(parents=True, exist_ok=True)
        pulled = self.raw(["pull", remote, str(dest)], timeout=30)
        self.shell(f"rm {remote}")
        return pulled

    def packages(self) -> list[str]:
        result = self.shell("pm list packages")
        names = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("package:"):
                names.append(line.split(":", 1)[1])
        return sorted(names)

    def launch(self, package: str) -> CommandResult:
        return self.shell(
            f"monkey -p {package} -c android.intent.category.LAUNCHER 1"
        )

    def clear_launcher_cache(self) -> list[CommandResult]:
        results = []
        installed = set(self.packages())
        for pkg in LAUNCHER_PACKAGES:
            if pkg in installed:
                results.append(self.shell(f"pm clear {pkg}"))
        return results

    def try_root(self) -> CommandResult:
        return self.raw(["root"], timeout=20)

    def try_remount(self) -> CommandResult:
        return self.raw(["remount"], timeout=20)

    def reboot(self) -> CommandResult:
        return self.raw(["reboot"], timeout=20)
