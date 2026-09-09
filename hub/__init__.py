"""Changan Hub package."""

__all__ = ["main"]


def main() -> None:
    from hub.gui import main as gui_main

    gui_main()
