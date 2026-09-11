from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_quickbar_landing_page_and_photos() -> None:
    html = (ROOT / "quickbar.html").read_text(encoding="utf-8")
    assert "<title>QuickBar" in html
    assert "разработано в ИТ-Мастерской" in html
    assert "Changan Lamore" in html
    assert "quickbar/photos/01-panel.jpg" in html
    assert "quickbar/photos/02-reorder.jpg" in html
    assert "quickbar/photos/03-usb.jpg" in html
    assert "quickbar/photos/04-collapsed.jpg" in html
    assert "lamore-hero.jpg" in (ROOT / "quickbar" / "page.css").read_text(encoding="utf-8")
    assert "5 000" in html
    assert "один раз" in html
    assert "сами" in html
    assert 'id="price"' in html
    assert 'id="order"' in html
    assert "Оставить заявку" in html
    assert "data-order-form" in html
    assert "380 dp" not in html
    assert "×3" not in html
    assert "Скрытые" in html
    photos = ROOT / "quickbar" / "photos"
    for name in (
        "01-panel.jpg",
        "02-reorder.jpg",
        "03-usb.jpg",
        "04-collapsed.jpg",
        "lamore-hero.jpg",
    ):
        path = photos / name
        assert path.is_file(), name
        assert path.stat().st_size > 20_000, name


def test_orders_page_posts_to_shared_sheet() -> None:
    html = (ROOT / "orders.html").read_text(encoding="utf-8")
    css = (ROOT / "quickbar" / "page.css").read_text(encoding="utf-8")
    js = (ROOT / "quickbar" / "orders.js").read_text(encoding="utf-8")
    gs = (ROOT / "quickbar" / "sheet-app.gs").read_text(encoding="utf-8")
    assert "Заказать QuickBar" in html
    assert "data-order-form" in html
    assert 'name="phone"' in html
    assert "5 000" in html
    assert "lamore-hero.jpg" in css
    assert "1lt7hUCI1Pu2OknbtCjNrUTfpO4iyu1RCjyoRXtSHjpw" in gs
    assert "2020729866" in gs
    assert "AKfycbxOqN9tHBz587AD47Q7L05aIIz3HlKlncoGg-v40GfLIrr6WyDn3CWZbzTQ9QDRTIe0" in js
    assert "GOOGLE_SHEET_URL" in js
    assert 'method: "GET"' in js
    assert "Заказ QuickBar" in js
    assert (ROOT / "quickbar" / "orders.js").is_file()
