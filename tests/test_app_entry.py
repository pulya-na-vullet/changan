from pathlib import Path


def test_app_py_exists() -> None:
    root = Path(__file__).resolve().parents[1]
    assert (root / "app.py").is_file()
    text = (root / "app.py").read_text(encoding="utf-8")
    assert "hub.gui" in text


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
