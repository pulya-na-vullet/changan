from pathlib import Path


def test_app_py_exists() -> None:
    root = Path(__file__).resolve().parents[1]
    assert (root / "app.py").is_file()
    text = (root / "app.py").read_text(encoding="utf-8")
    assert "hub.gui" in text
