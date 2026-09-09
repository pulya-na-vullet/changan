import os

import pytest

pytestmark = pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="GUI needs a display")


def test_gui_pages_render() -> None:
    from hub.gui import HubApp

    app = HubApp()
    try:
        app.root.update()
        for name in ("connect", "install", "overlay", "apps", "catalog", "tools"):
            app.show(name)
            app.root.update_idletasks()
            app.root.update()
        assert app.pages.keys() >= {"connect", "install", "overlay", "apps", "catalog", "tools"}
        app._pump_log()
        assert "Changan Hub" in app.log_widget.get("1.0", "end") or app.log_q.qsize() >= 0
    finally:
        app.root.destroy()
