from pathlib import Path


def test_app_py_exists() -> None:
    root = Path(__file__).resolve().parents[1]
    assert (root / "app.py").is_file()
    text = (root / "app.py").read_text(encoding="utf-8")
    assert "hub.gui" in text


def test_run_bat_starts_once() -> None:
    text = (Path(__file__).resolve().parents[1] / "run.bat").read_text(encoding="utf-8")
    assert text.lower().count("@echo off") == 1
    assert "pip install" in text
    assert "import cryptography" in text
    assert "pythonw.exe" in text
    assert text.lower().count("setlocal") == 1

