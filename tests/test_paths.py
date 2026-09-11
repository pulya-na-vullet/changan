from hub.paths import ROOT, captures_dir, logs_dir


def test_logs_live_next_to_app() -> None:
    folder = logs_dir()
    assert folder == ROOT / "logs"
    assert folder.is_dir()


def test_captures_live_next_to_app() -> None:
    folder = captures_dir()
    assert folder == ROOT / "captures"
    assert folder.is_dir()
    assert (folder / "README.txt").is_file()
