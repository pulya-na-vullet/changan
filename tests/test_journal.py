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


def test_shell_success_empty_stdout_does_not_retry() -> None:
    adb = object.__new__(Adb)
    calls: list[tuple] = []

    def fake_raw(args, timeout=45, input_text=None):
        calls.append((tuple(args), input_text, timeout))
        from hub.adb import CommandResult

        return CommandResult(
            True,
            "",
            "please input verify password: verify success!",
            0,
            args,
        )

    adb.raw = fake_raw  # type: ignore[method-assign]
    adb.last_password_used = False
    result = Adb.shell(adb, "appops set com.changanhub.quickbar SYSTEM_ALERT_WINDOW allow")
    assert result.ok
    assert result.code == 0
    assert len(calls) == 1


def test_shell_no_devices_does_not_retry() -> None:
    adb = object.__new__(Adb)
    calls: list[tuple] = []

    def fake_raw(args, timeout=45, input_text=None):
        calls.append((tuple(args), input_text, timeout))
        from hub.adb import CommandResult

        return CommandResult(False, "", "adb.exe: no devices/emulators found", 1, args)

    adb.raw = fake_raw  # type: ignore[method-assign]
    adb.last_password_used = False
    result = Adb.shell(adb, "am startservice -n x/y")
    assert not result.ok
    assert len(calls) == 1


def test_shell_device_not_found_does_not_retry() -> None:
    adb = object.__new__(Adb)
    calls: list[tuple] = []

    def fake_raw(args, timeout=45, input_text=None):
        calls.append((tuple(args), input_text, timeout))
        from hub.adb import CommandResult

        return CommandResult(False, "", "adb.exe: device 'AHFPF6643H444A0076' not found", 1, args)

    adb.raw = fake_raw  # type: ignore[method-assign]
    adb.last_password_used = False
    result = Adb.shell(adb, "pm path org.schabi.newpipe")
    assert not result.ok
    assert len(calls) == 1


def test_shell_security_exception_does_not_retry() -> None:
    adb = object.__new__(Adb)
    calls: list[tuple] = []

    def fake_raw(args, timeout=45, input_text=None):
        calls.append((tuple(args), input_text, timeout))
        from hub.adb import CommandResult

        return CommandResult(
            False,
            "",
            "please input verify password: verify success!\n"
            "Security exception: Package com.changanhub.quickdock has not requested permission "
            "android.permission.WRITE_EXTERNAL_STORAGE",
            255,
            args,
        )

    adb.raw = fake_raw  # type: ignore[method-assign]
    adb.last_password_used = False
    result = Adb.shell(
        adb, "pm grant com.changanhub.quickdock android.permission.WRITE_EXTERNAL_STORAGE", timeout=10
    )
    assert not result.ok
    assert result.code == 255
    assert len(calls) == 1


def test_shell_verify_success_nonzero_does_not_retry() -> None:
    """Rus HU 2026-09-12: pm path returned code=1 + verify success, retry hung 10s."""
    adb = object.__new__(Adb)
    calls: list[tuple] = []

    def fake_raw(args, timeout=45, input_text=None):
        calls.append((tuple(args), input_text, timeout))
        from hub.adb import CommandResult

        return CommandResult(
            False,
            "",
            "please input verify password: verify success!",
            1,
            args,
        )

    adb.raw = fake_raw  # type: ignore[method-assign]
    adb.last_password_used = False
    result = Adb.shell(adb, "pm path org.schabi.newpipe", timeout=10)
    assert len(calls) == 1
    assert not result.ok
    assert result.code == 1


def test_shell_keeps_package_path_on_stderr() -> None:
    adb = object.__new__(Adb)
    calls: list[tuple] = []

    def fake_raw(args, timeout=45, input_text=None):
        calls.append((tuple(args), input_text, timeout))
        from hub.adb import CommandResult

        return CommandResult(
            False,
            "",
            "please input verify password: verify success!\npackage:/data/app/hack/base.apk\n",
            1,
            args,
        )

    adb.raw = fake_raw  # type: ignore[method-assign]
    adb.last_password_used = False
    result = Adb.shell(adb, "pm path ru.hackchan.launcher", timeout=10)
    assert len(calls) == 1
    assert "package:/data/app/hack/base.apk" in result.stderr
    assert result.ok


def test_journal_writes_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("hub.journal.logs_dir", lambda: tmp_path)
    journal = Journal()
    journal.action("установить панель", "QuickBar")
    text = journal.path.read_text(encoding="utf-8")
    assert "[ACTION]" in text
    assert "установить панель" in text
