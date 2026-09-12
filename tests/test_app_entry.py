from pathlib import Path

from app import project_root


def test_app_py_exists() -> None:
    root = Path(__file__).resolve().parents[1]
    assert (root / "app.py").is_file()
    text = (root / "app.py").read_text(encoding="utf-8")
    assert "hub.gui" in text
    assert "project_root" in text
    assert (root / "hub" / "gui.py").is_file()


def test_project_root_uses_nested_github_extract(tmp_path: Path) -> None:
    inner = tmp_path / "changan-cursor-fix-rus-whitelist-serial-0bfc"
    (inner / "hub").mkdir(parents=True)
    (inner / "hub" / "gui.py").write_text("# gui\n", encoding="utf-8")
    (inner / "app.py").write_text("#\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("# outer leftover\n", encoding="utf-8")
    assert project_root(tmp_path) == inner.resolve()


def test_project_root_prefers_current_folder(tmp_path: Path) -> None:
    (tmp_path / "hub").mkdir()
    (tmp_path / "hub" / "gui.py").write_text("# gui\n", encoding="utf-8")
    nested = tmp_path / "nested"
    (nested / "hub").mkdir(parents=True)
    (nested / "hub" / "gui.py").write_text("# other\n", encoding="utf-8")
    assert project_root(tmp_path) == tmp_path.resolve()


def test_run_bat_starts_once() -> None:
    root = Path(__file__).resolve().parents[1]
    text = (root / "run.bat").read_text(encoding="utf-8")
    raw = (root / "run.bat").read_bytes()
    assert text.lower().count("@echo off") == 1
    assert not any(line.lstrip().lower().startswith("chcp") for line in text.splitlines())
    assert "goto :launch" in text
    assert "pythonw.exe" in text
    assert "python app.py" in text.lower() or 'python "%~dp0app.py"' in text.lower()
    assert "logs\\start.log" in text or "logs\\start.log" in text.replace("/", "\\")
    assert text.lower().count("setlocal") == 1
    assert "hub.lock" in text
    assert b"\r\n" in raw
    assert "ensure_env.py" not in text
    # UTF-8 code page makes cmd.exe skip the first character of later lines.
    assert not text.lstrip().startswith("\ufeff")
    assert (root / "ensure_env.py").is_file()
    env = (root / "ensure_env.py").read_text(encoding="utf-8")
    assert "cryptography" in env
    assert "ensurepip" in env
    assert "start.log" in env
    assert "pip не запускаю" in env
    assert "timeout=120" in env
    assert "hub_running" in env
    assert "setup_running" in env
    assert "trusted-host" in env


def test_hub_lock_detects_live_pid(tmp_path, monkeypatch) -> None:
    import os

    import ensure_env

    monkeypatch.setattr(ensure_env, "LOCK", tmp_path / "hub.lock")
    assert ensure_env.hub_running() is False
    (tmp_path / "hub.lock").write_text(str(os.getpid()), encoding="utf-8")
    assert ensure_env.hub_running() is True
    (tmp_path / "hub.lock").write_text("99999999", encoding="utf-8")
    assert ensure_env.hub_running() is False
