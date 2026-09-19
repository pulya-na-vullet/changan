from pathlib import Path

from hub.catalog import CATALOG
from hub.news import PACKAGE, install_news, news_apk, start_news


class FakeAdb:
    def __init__(self) -> None:
        self.shells: list[str] = []

    def shell(self, command: str, timeout: int = 60):
        from hub.adb import CommandResult

        self.shells.append(command)
        return CommandResult(True, "", "", 0, [])


def test_news_catalog_and_hub_card() -> None:
    assert any(app.id == "news" and app.package == PACKAGE for app in CATALOG)
    src = Path("hub/gui.py").read_text(encoding="utf-8")
    assert "deploy_news" in src
    assert "news_install_btn" in src
    assert "changan_news" in Path("hub/catalog.py").read_text(encoding="utf-8")
    news_src = Path("hub/news.py").read_text(encoding="utf-8")
    assert "исходники" in news_src.lower() or "не копиру" in news_src.lower()
    assert "applyWindowMargins" not in news_src  # do not vendor their Java


def test_news_apk_missing_explains_repo() -> None:
    apk = news_apk()
    if apk.exists():
        return
    lines = install_news(FakeAdb())
    blob = "\n".join(lines).lower()
    assert "не найден" in blob
    assert "changan_news" in blob
    assert "apps/" in blob or "apps\\" in blob


def test_start_news_when_present() -> None:
    fake = FakeAdb()
    lines = start_news(fake)
    joined = "\n".join(fake.shells + lines)
    assert PACKAGE in joined
    assert "MainActivity" in joined
    assert "поля 10%" in "\n".join(lines)
