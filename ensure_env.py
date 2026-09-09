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


def ok(args: list[str]) -> bool:
    try:
        proc = run(args, timeout=40)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def cryptography_ok(py: Path) -> bool:
    return py.is_file() and ok([str(py), "-c", "import cryptography"])


def pip_ok(py: Path) -> bool:
    if not py.is_file():
        return False
    if not ok([str(py), "-c", "import pip"]):
        return False
    return ok([str(py), "-m", "pip", "--version"])


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
    # Prefer the running interpreter: it is the one the user actually has.
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
    log("ставлю cryptography (один раз, не каждый запуск)")
    proc = run(
        [str(py), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(REQ)],
        timeout=600,
    )
    if proc.stdout:
        log(proc.stdout.strip()[-1500:])
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "pip install failed").strip()
        log(err[-2000:])
        raise RuntimeError("pip install не смог поставить зависимости. Нужен интернет.")


def main() -> int:
    try:
        log(f"ensure_env: python={sys.executable} cwd={ROOT}")
        py = venv_python()
        if cryptography_ok(py):
            log("окружение в порядке, cryptography есть")
            return 0
        if py.is_file() and not pip_ok(py):
            log("pip в .venv сломан (часто после копирования флешки). Пересоздаю.")
            remove_venv()
        if not venv_python().is_file():
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
    except Exception as exc:  # noqa: BLE001
        log(f"ОШИБКА: {exc}")
        log(traceback.format_exc())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
