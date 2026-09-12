from hub.adb import Adb
from hub.catalog import CATALOG


def test_password_detection() -> None:
    adb = object.__new__(Adb)
    assert adb.needs_password("please input verify password:")
    assert not adb.needs_password("Success")


def test_catalog_has_quickbar() -> None:
    from hub.catalog import package_from_row, package_label

    assert any(app.id == "quickbar" for app in CATALOG)
    assert all(app.package for app in CATALOG)
    row = package_label("com.changanhub.quickrise")
    assert "QuickBar" in row
    assert package_from_row(row) == "com.changanhub.quickrise"
    assert "Лайт" in package_label("com.yandex.browser.lite")
    leftover = package_label("com.changanhub.quickkeep")
    assert "старая" in leftover.lower()
    assert package_from_row(leftover) == "com.changanhub.quickkeep"
    legacy = package_label("com.changanhub.quickbar")
    assert "quickbar" in legacy.lower()
    assert package_from_row(legacy) == "com.changanhub.quickbar"
    previous = package_label("com.changanhub.quickdock")
    assert package_from_row(previous) == "com.changanhub.quickdock"
    lane = package_label("com.changanhub.quicklane")
    assert package_from_row(lane) == "com.changanhub.quicklane"


def test_need_adb_dialog_does_not_close_over_exc() -> None:
    from pathlib import Path

    src = Path("hub/gui.py").read_text(encoding="utf-8")
    assert 'lambda: messagebox.showerror("ADB", str(exc))' not in src
    assert "lambda m=msg: messagebox.showerror(\"ADB\", m)" in src


def test_demo_capture_in_hub() -> None:
    from pathlib import Path

    src = Path("hub/gui.py").read_text(encoding="utf-8")
    assert '("demo", "Демо")' in src
    assert "Сделать скриншот" in src
    assert "Запись 60 с" in src
    assert "from hub.capture import" in src
    adb_src = Path("hub/adb.py").read_text(encoding="utf-8")
    assert "/data/local/tmp/changan_hub_shot.png" in adb_src
    assert "/sdcard/Download/changan_hub_shot.png" not in adb_src
    cli = Path("hub/cli.py").read_text(encoding="utf-8")
    assert 'sub.add_parser("screenshot"' in cli
    assert 'sub.add_parser("record"' in cli


def test_nav_credit_matches_hub_title_style() -> None:
    from pathlib import Path

    src = Path("hub/gui.py").read_text(encoding="utf-8")
    assert 'text="CHANGAN HUB"' in src
    assert 'text="разработано в ИТ-Мастерской"' in src
    assert 'fg=ACCENT' in src
    assert 'font=("Segoe UI", 16, "bold")' in src
    assert 'font=("Segoe UI", 9, "bold")' in src
