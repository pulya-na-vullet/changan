#!/usr/bin/env python3
"""Запуск Changan Hub: python app.py"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

MIN_PY = (3, 10)


def python_dir_version(exe: Path) -> tuple[int, int] | None:
    """Parse …/Python313/python.exe → (3, 13), …/Python39/python.exe → (3, 9)."""
    name = exe.parent.name.lower().replace("python", "")
    if not name.isdigit():
        return None
    if len(name) == 1:
        return (int(name), 0)
    return (int(name[0]), int(name[1:]))


def newer_python_exe(current: Path | None = None) -> Path | None:
    current = (current or Path(sys.executable)).resolve()
    found: list[tuple[tuple[int, int], Path]] = []
    bases = []
    localapp = os.environ.get("LOCALAPPDATA")
    if localapp:
        bases.append(Path(localapp) / "Programs" / "Python")
    bases.append(Path.home() / "AppData" / "Local" / "Programs" / "Python")
    seen: set[Path] = set()
    for base in bases:
        if not base.is_dir():
            continue
        try:
            children = list(base.iterdir())
        except OSError:
            continue
        for child in children:
            exe = child / "python.exe"
            try:
                resolved = exe.resolve()
            except OSError:
                continue
            if not exe.is_file() or resolved in seen or resolved == current:
                continue
            version = python_dir_version(exe)
            if version and version >= MIN_PY:
                seen.add(resolved)
                found.append((version, exe))
    if not found:
        return None
    found.sort(key=lambda item: item[0], reverse=True)
    return found[0][1]


def _reexec_or_die() -> None:
    if sys.version_info >= MIN_PY:
        return
    newer = newer_python_exe()
    if newer is not None:
        print(
            f"Git Bash дал Python {sys.version.split()[0]}. "
            f"Перезапускаю: {newer}"
        )
        raise SystemExit(subprocess.call([str(newer), *sys.argv]))
    print(
        f"Этот Python слишком старый: {sys.executable} ({sys.version.split()[0]}). "
        "Нужен 3.10+."
    )
    hint = Path.home() / "AppData" / "Local" / "Programs" / "Python" / "Python313" / "python.exe"
    if hint.is_file():
        print(f'Запустите:\n  "{hint}" app.py')
    else:
        print(
            'Запустите Python 3.13, не python из Git Bash:\n'
            r'  "/c/Users/79872/AppData/Local/Programs/Python/Python313/python.exe" app.py'
        )
    raise SystemExit(1)


def project_root(start: Path | None = None) -> Path:
    """GitHub ZIP often unpacks one extra folder; find the tree that has hub/gui.py."""
    start = (start or Path(__file__).resolve().parent).resolve()
    found: list[Path] = []

    def add(path: Path) -> None:
        path = path.resolve()
        if path not in found and (path / "hub" / "gui.py").is_file():
            found.append(path)

    add(start)
    try:
        children = list(start.iterdir())
    except OSError:
        children = []
    for child in children:
        if child.is_dir() and not child.name.startswith("."):
            add(child)
    return found[0] if found else start


def _prepare(start: Path | None = None) -> Path:
    root = project_root(start)
    os.chdir(root)
    root_s = str(root)
    sys.path[:] = [item for item in sys.path if item != root_s]
    sys.path.insert(0, root_s)
    return root


def _die_missing_hub(root: Path) -> None:
    print("Не найден hub\\gui.py — архив распакован не полностью.")
    print(f"Сейчас папка: {root}")
    print("Нужны: app.py, папка hub (gui.py, installer.py), папка apps.")
    try:
        names = sorted(item.name for item in root.iterdir())
    except OSError:
        names = []
    print("В этой папке сейчас:", ", ".join(names[:40]) or "(пусто)")
    nested = []
    try:
        nested = [item.parent.parent.name for item in root.glob("*/hub/gui.py")]
    except OSError:
        nested = []
    if nested:
        print("Полный Hub лежит во вложенной папке:", ", ".join(nested))
        print(f"  cd {nested[0]}")
        print("  python app.py")
    else:
        print("Распакуйте ZIP целиком в новую папку. Не копируйте один app.py.")
    print(f"Этот Python: {sys.executable}")
    raise SystemExit(1)


def main() -> None:
    _reexec_or_die()
    root = _prepare()
    gui_py = root / "hub" / "gui.py"
    if not gui_py.is_file():
        _die_missing_hub(root)

    from ensure_env import clear_hub_lock, hub_running, write_hub_lock

    if hub_running():
        print("Changan Hub уже запущен. Закройте то окно или подождите.")
        raise SystemExit(0)
    write_hub_lock()
    import atexit

    atexit.register(clear_hub_lock)
    try:
        import hub
    except ModuleNotFoundError as exc:
        missing = exc.name or ""
        if missing in {"cryptography"}:
            print("Сначала установите зависимости:")
            print(f"  {sys.executable} -m pip install -r \"{root / 'requirements.txt'}\"")
            raise SystemExit(1) from exc
        _die_missing_hub(root)
    hub_file_raw = getattr(hub, "__file__", None)
    expected = (root / "hub" / "__init__.py").resolve()
    if hub_file_raw:
        hub_file = Path(hub_file_raw).resolve()
        if expected.is_file() and hub_file != expected:
            print("Python взял чужой пакет hub, не эту флешку.")
            print(f"  взял: {hub_file}")
            print(f"  нужен: {expected}")
            print(f"Запустите так: {sys.executable} \"{root / 'app.py'}\"")
            raise SystemExit(1)
    try:
        from hub.gui import main as gui_main
    except ModuleNotFoundError as exc:
        missing = exc.name or ""
        if missing in {"cryptography"}:
            print("Сначала установите зависимости:")
            print(f"  {sys.executable} -m pip install -r \"{root / 'requirements.txt'}\"")
            raise SystemExit(1) from exc
        print(f"Не импортировался {missing or 'hub.gui'}.")
        print(f"Python: {sys.executable}")
        print(f"Ожидаю файл: {gui_py} (есть: {gui_py.is_file()})")
        _die_missing_hub(root)
    except SyntaxError as exc:
        print(
            f"Этот Python не читает Hub: {sys.executable} ({sys.version.split()[0]}). "
            f"{exc.filename}:{exc.lineno}"
        )
        raise SystemExit(1) from exc
    gui_main()


if __name__ == "__main__":
    main()
