from pathlib import Path

from hub.paths import ROOT
from hub.usb import list_usb_apks, removable_roots


def test_hub_stick_lists_bundled_apk() -> None:
    roots = removable_roots()
    assert ROOT in roots or any(ROOT.is_relative_to(r) for r in roots) or ROOT in roots
    apks = list_usb_apks()
    names = {p.name for p in apks}
    assert "QuickBar.apk" in names


def test_usb_skip_does_not_enter_git() -> None:
    from hub.usb import SKIP_DIRS

    assert ".git" in SKIP_DIRS
    assert "android" in SKIP_DIRS
