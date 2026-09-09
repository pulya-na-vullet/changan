from hub.paths import ROOT, logs_dir


def test_logs_live_next_to_app() -> None:
    folder = logs_dir()
    assert folder == ROOT / "logs"
    assert folder.is_dir()
