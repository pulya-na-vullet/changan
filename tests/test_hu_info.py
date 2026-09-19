from hub.hu_info import parse_version_name
from hub.version import VERSION


def test_parse_version_name() -> None:
    blob = "    versionCode=6 minSdk=28 targetSdk=28\n    versionName=1.1.3\n"
    assert parse_version_name(blob) == "1.1.3"
    assert parse_version_name("nothing") is None


def test_hub_version() -> None:
    assert VERSION == "1.5.1"
    src = open("hub/gui.py", encoding="utf-8").read()
    assert "VERSION" in src
    assert '"ours", "Наши приложения"' in src
    assert "_assert_install" in src
    assert "get-state" in src
