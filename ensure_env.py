#!/usr/bin/env python3
"""Create or repair the USB .venv. Stdlib only — pip in .venv may be broken."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import traceback
import venv
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
REQ = ROOT / "requirements.txt"
LOG = ROOT / "logs" / "start.log"
LOCK = ROOT / "logs" / "hub.lock"
SETUP_LOCK = ROOT / "logs" / "setup.lock"


def log(message: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {message}"
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    try:
        print(line)
    except UnicodeEncodeError:
        print(line.encode("ascii", "replace").decode("ascii"))


def venv_python() -> Path:
    if os.name == "nt":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def run(args: list[str], timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(ROOT),
        timeout=timeout,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def ok(args: list[str], timeout: int = 90) -> bool:
    try:
        proc = run(args, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
        except Exception:
            return False
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _read_pid(path: Path) -> int | None:
    try:
        raw = path.read_text(encoding="utf-8").strip()
        return int(raw)
    except (OSError, ValueError):
        return None


def hub_running() -> bool:
    pid = _read_pid(LOCK)
    return pid is not None and pid_alive(pid)


def setup_running() -> bool:
    pid = _read_pid(SETUP_LOCK)
    return pid is not None and pid_alive(pid)


def write_hub_lock() -> None:
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    LOCK.write_text(str(os.getpid()), encoding="utf-8")


def clear_hub_lock() -> None:
    try:
        LOCK.unlink()
    except OSError:
        pass


def _write_setup_lock() -> None:
    SETUP_LOCK.parent.mkdir(parents=True, exist_ok=True)
    SETUP_LOCK.write_text(str(os.getpid()), encoding="utf-8")


def _clear_setup_lock() -> None:
    try:
        SETUP_LOCK.unlink()
    except OSError:
        pass


def cryptography_ok(py: Path) -> bool:
    # USB flash drives are slow; 40s was not enough and Hub rebuilt .venv every launch.
    return py.is_file() and ok([str(py), "-c", "import cryptography"], timeout=120)


def pip_ok(py: Path) -> bool:
    if not py.is_file():
        return False
    if not ok([str(py), "-c", "import pip"], timeout=60):
        return False
    return ok([str(py), "-m", "pip", "--version"], timeout=60)


def remove_venv() -> None:
    if not VENV.exists():
        return
    log(f"удаляю сломанное окружение {VENV}")

    def onerror(func, path, _exc):  # noqa: ANN001
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except OSError:
            pass

    import shutil

    shutil.rmtree(VENV, onerror=onerror)
    if VENV.exists():
        raise RuntimeError(
            f"не удалось удалить {VENV}. Закройте Hub и проводник с этой папкой, затем снова run.bat"
        )


def create_venv(system_python: str) -> None:
    log(f"создаю .venv через {system_python}")
    builder = venv.EnvBuilder(with_pip=True, clear=True, upgrade_deps=False)
    builder.create(VENV)
    py = venv_python()
    if not py.is_file():
        raise RuntimeError("venv создался без python.exe")
    ensure = run([str(py), "-m", "ensurepip", "--upgrade"])
    if ensure.returncode != 0:
        log((ensure.stderr or ensure.stdout or "ensurepip failed").strip())
    if not pip_ok(py):
        raise RuntimeError("pip в новом .venv не работает. Переустановите Python с python.org")


def install_requirements(py: Path) -> None:
    log("ставлю cryptography (первый запуск или после поломки .venv)")
    args = [str(py), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(REQ)]
    proc = run(args, timeout=600)
    if proc.returncode != 0:
        log("pip через HTTPS не прошёл, пробую trusted-host (часто ломает SSL в машине)")
        proc = run(
            args
            + [
                "--trusted-host",
                "pypi.org",
                "--trusted-host",
                "pypi.python.org",
                "--trusted-host",
                "files.pythonhosted.org",
            ],
            timeout=600,
        )
    if proc.stdout:
        log(proc.stdout.strip()[-1500:])
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "pip install failed").strip()
        log(err[-2000:])
        raise RuntimeError(
            "pip install не смог поставить зависимости. "
            "Нужен интернет (лучше дома, не через Wi‑Fi машины). "
            "Не удаляйте .venv и не запускайте run.bat повторно, пока идёт установка."
        )


def main() -> int:
    try:
        log(f"ensure_env: python={sys.executable} cwd={ROOT}")
        if hub_running():
            log("Hub уже запущен — .venv не трогаю и pip не запускаю")
            return 0
        if setup_running():
            log("уже идёт установка .venv в другом окне run.bat — дождитесь его")
            return 1
        _write_setup_lock()
        try:
            py = venv_python()
            if cryptography_ok(py):
                log("окружение в порядке, cryptography уже есть — pip не запускаю")
                return 0
            if not py.is_file():
                create_venv(sys.executable)
                py = venv_python()
            elif not pip_ok(py):
                log("pip не отвечает, пробую ensurepip без удаления .venv")
                run([str(py), "-m", "ensurepip", "--upgrade"])
                if not pip_ok(py):
                    log("pip в .venv сломан. Пересоздаю только если Hub не запущен.")
                    remove_venv()
                    create_venv(sys.executable)
                    py = venv_python()
            if not pip_ok(py):
                log("pip всё ещё нет, пробую ensurepip")
                run([str(py), "-m", "ensurepip", "--upgrade"])
            if not cryptography_ok(py):
                install_requirements(py)
            if not cryptography_ok(py):
                raise RuntimeError("cryptography так и не импортируется после pip install")
            log("окружение готово")
            return 0
        finally:
            _clear_setup_lock()
    except Exception as exc:  # noqa: BLE001
        log(f"ОШИБКА: {exc}")
        log(traceback.format_exc())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
