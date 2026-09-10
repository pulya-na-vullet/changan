from pathlib import Path


def test_app_py_exists() -> None:
    root = Path(__file__).resolve().parents[1]
    assert (root / "app.py").is_file()
    text = (root / "app.py").read_text(encoding="utf-8")
    assert "hub.gui" in text


def test_run_bat_starts_once() -> None:
    root = Path(__file__).resolve().parents[1]
    text = (root / "run.bat").read_text(encoding="utf-8")
    assert text.lower().count("@echo off") == 1
    assert "ensure_env.py" in text
    assert "goto :launch" in text
    assert "skipping pip" in text
    assert "chcp 65001" in text
    assert "logs\\start.log" in text or "logs\\start.log" in text.replace("/", "\\")
    assert "pythonw.exe" in text
    assert text.lower().count("setlocal") == 1
    assert (root / "ensure_env.py").is_file()
    env = (root / "ensure_env.py").read_text(encoding="utf-8")
    assert "cryptography" in env
    assert "ensurepip" in env
    assert "start.log" in env
    assert "pip не запускаю" in env
    assert "timeout=120" in env
