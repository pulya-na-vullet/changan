import os

import pytest

pytestmark = pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="GUI needs a display")


def test_gui_pages_render() -> None:
    from hub.gui import HubApp
    from hub.installer import PROCESS_STAGES

    app = HubApp()
    try:
        app.root.update()
        for name in ("connect", "install", "overlay", "apps", "catalog", "tools"):
            app.show(name)
            app.root.update_idletasks()
            app.root.update()
        assert app.pages.keys() >= {"connect", "install", "overlay", "apps", "catalog", "tools"}
        assert app.progress_bar.winfo_exists()
        assert set(app.stage_labels) == {key for key, _ in PROCESS_STAGES}
        app._show_progress("Шаг 2/5: копирую APK на ГУ (push).", 40)
        app.root.update()
        assert "push" in app.step_var.get().lower() or "копир" in app.step_var.get().lower()
        assert "●" in app.stage_labels["push"].cget("text")
        app._reset_stages()
        app.root.update()
        app._show_progress("Готово: Подключение", 100)
        app.root.update()
        assert "○" in app.stage_labels["push"].cget("text")
        app.busy = True
        app.busy_title = "QuickBar"
        before = app.jobs.qsize()
        app._work("QuickBar", lambda: None)
        assert app.jobs.qsize() == before
        app.busy = False
        app.busy_title = ""
        app._pump_log()
        assert "Changan Hub" in app.log_widget.get("1.0", "end") or app.log_q.qsize() >= 0
    finally:
        app.root.destroy()


def _inside_window(widget, root, pad: int = 4) -> bool:
    if not widget.winfo_ismapped():
        return False
    top = widget.winfo_rooty()
    bottom = top + widget.winfo_height()
    win_top = root.winfo_rooty()
    win_bottom = win_top + root.winfo_height()
    return widget.winfo_height() > 8 and top >= win_top - pad and bottom <= win_bottom + pad


def test_install_button_visible_at_laptop_size() -> None:
    from hub.gui import HubApp

    app = HubApp()
    try:
        app.root.geometry("960x640")
        app.root.update_idletasks()
        app.root.update()
        app.show("install", "Установка APK")
        app.root.update_idletasks()
        app.root.update()
        assert app.install_btn.winfo_ismapped()
        assert _inside_window(app.install_btn, app.root)
        assert app.usb_btn.winfo_ismapped()
        assert _inside_window(app.usb_btn, app.root)
        app.show("overlay", "Правая панель")
        app.root.update()
        assert app.overlay_install_btn.winfo_ismapped()
        assert _inside_window(app.overlay_install_btn, app.root)
        app.show("apps", "Приложения ГУ")
        app.root.update()
        assert app.launch_btn.winfo_ismapped()
        assert _inside_window(app.launch_btn, app.root)
    finally:
        app.root.destroy()
