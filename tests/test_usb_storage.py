from pathlib import Path


def test_quickbar_splits_usb_and_hu_memory() -> None:
    src = Path("android/quickbar/src/main/java/com/changanhub/quickbar/UsbStorage.java").read_text(
        encoding="utf-8"
    )
    assert "usbRoots" in src
    assert "memoryRoots" in src
    assert "Память ГУ" in src
    assert 'ID_USB = "usb"' in src
    assert 'ID_MEMORY = "memory"' in src
    assert "/mnt/media_rw" in src
    assert "/storage/emulated/0" in src
    assert "/sdcard" in src
    assert "isMemoryPath" in src
    assert "dropParents" in src
    overlay = Path(
        "android/quickbar/src/main/java/com/changanhub/quickbar/OverlayService.java"
    ).read_text(encoding="utf-8")
    assert "sourcePicker" in overlay
    assert "KEY_APK_SOURCE" in overlay
    assert "USB-разъём" in overlay or "USB-разъеме" in overlay or "USB-разъёме" in overlay
    assert "Память самого ГУ" in overlay
