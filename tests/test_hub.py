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
    row = package_label("com.changanhub.quickbar")
    assert "IT-m" in row
    assert package_from_row(row) == "com.changanhub.quickbar"
