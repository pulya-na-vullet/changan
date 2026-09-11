from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_quickbar_landing_page_and_photos() -> None:
    html = (ROOT / "quickbar.html").read_text(encoding="utf-8")
    assert "<title>QuickBar" in html
    assert "разработано в ИТ-Мастерской" in html
    assert "Changan Lamore" in html
    assert "quickbar/photos/01-panel-navigator.png" in html
    assert "quickbar/photos/02-reorder.png" in html
    assert "quickbar/photos/03-hidden-folded.png" in html
    assert "quickbar/photos/04-collapsed.png" in html
    assert "5 000" in html
    assert "один раз" in html
    assert "сами" in html
    assert 'id="price"' in html
    assert "Скрытые" in html
    photos = ROOT / "quickbar" / "photos"
    for name in (
        "01-panel-navigator.png",
        "02-reorder.png",
        "03-hidden-folded.png",
        "04-collapsed.png",
    ):
        path = photos / name
        assert path.is_file(), name
        assert path.stat().st_size > 20_000, name
