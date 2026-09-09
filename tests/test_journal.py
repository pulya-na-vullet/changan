from hub.adb import SHELL_PASSWORD, Adb
from hub.journal import Journal


def test_shell_always_sends_password() -> None:
    adb = object.__new__(Adb)
    sent = {}

    def fake_raw(args, timeout=45, input_text=None):
        sent["args"] = args
        sent["input"] = input_text
        from hub.adb import CommandResult

        return CommandResult(True, "please input verify password:\nspm8666p1_64_car\n", "", 0, args)

    adb.raw = fake_raw  # type: ignore[method-assign]
    adb.last_password_used = False
    result = Adb.shell(adb, "getprop ro.product.device")
    assert sent["args"] == ["shell", "getprop ro.product.device"]
    assert sent["input"] is not None and sent["input"].startswith(SHELL_PASSWORD)
    assert "please input" not in result.stdout.lower()
    assert "spm8666p1_64_car" in result.stdout


def test_shell_timeout_does_not_retry() -> None:
    adb = object.__new__(Adb)
    calls: list[tuple] = []

    def fake_raw(args, timeout=45, input_text=None):
        calls.append((tuple(args), input_text, timeout))
        from hub.adb import CommandResult

        return CommandResult(False, "", "timeout after 25s", 124, args)

    adb.raw = fake_raw  # type: ignore[method-assign]
    adb.last_password_used = False
    result = Adb.shell(adb, "pm install -r /sdcard/x.apk", timeout=25)
    assert result.code == 124
    assert len(calls) == 1


def test_journal_writes_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("hub.journal.logs_dir", lambda: tmp_path)
    journal = Journal()
    journal.action("установить панель", "QuickBar")
    text = journal.path.read_text(encoding="utf-8")
    assert "[ACTION]" in text
    assert "установить панель" in text
