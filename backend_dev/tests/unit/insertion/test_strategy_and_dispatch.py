"""T-INS strategy, input encoding, clipboard and confirmation contracts."""

from dataclasses import replace

from .fake_apis import FakeUiaApi, FakeWin32Api


def _snapshot() -> object:
    from wispr_clone.insertion.destination import capture

    return capture(FakeWin32Api(), FakeUiaApi())


def test_T_INS_004_every_transcript_clipboard_write_requests_exclusions() -> None:
    from wispr_clone.insertion.inserter import dispatch

    win, uia = FakeWin32Api(), FakeUiaApi()
    win.clipboard = "old"
    snapshot = replace(_snapshot(), langid=0x0412)
    dispatch("synthetic transcript", snapshot, win, uia)
    writes = [call for call in win.calls if call[0] == "set_clipboard"]
    assert writes == [
        ("set_clipboard", ("synthetic transcript",), {"exclusion_formats": True}),
        ("set_clipboard", ("old",), {"exclusion_formats": False}),
    ]
    assert win.clipboard == "old"


def test_T_INS_005_rejected_paste_does_not_fall_back_to_unicode() -> None:
    from wispr_clone.insertion.inserter import dispatch

    win, uia = FakeWin32Api(), FakeUiaApi()
    win.accepted = 0
    snapshot = replace(_snapshot(), langid=0x0412)
    result = dispatch("sample", snapshot, win, uia)
    sends = [call for call in win.calls if call[0] == "send_inputs"]
    assert result.strategy == "paste"
    assert result.events_accepted == 0
    assert len(sends) == 1
    assert all(event.flags & 0x0004 == 0 for event in sends[0][1][0])
    assert [name for name, *_ in win.calls].index("set_clipboard") < [
        name for name, *_ in win.calls
    ].index("send_inputs")
    assert win.clipboard is None


def test_T_INS_006_unicode_inputs_use_utf16_units_with_down_up() -> None:
    from wispr_clone.insertion.inserter import build_unicode_inputs

    for text, units in (("A", [0x0041]), ("한", [0xD55C]), ("😀", [0xD83D, 0xDE00])):
        events = build_unicode_inputs(text)
        assert [(event.vk, event.scan, event.flags) for event in events] == [
            (0, unit, flag) for unit in units for flag in (0x0004, 0x0006)
        ]
        assert all(event.vk != 0x0D for event in events)


def test_T_INS_009_confirmation_requires_exactly_one_new_occurrence() -> None:
    from wispr_clone.insertion.inserter import DispatchResult, confirm

    uia = FakeUiaApi()
    snapshot = _snapshot()
    rid = snapshot.field
    for before, after, expected in (
        (None, "sample", "uncertain"),
        ("before", None, "uncertain"),
        ("before", "before", "uncertain"),
        ("before", "before sample sample", "uncertain"),
        ("before", "changed sample", "uncertain"),
        ("before", "before sample", "inserted"),
        ("before sample", "before sample sample", "inserted"),
        ("before sample", "before sample sample sample", "uncertain"),
    ):
        uia.texts[rid] = after
        result = DispatchResult("paste", 4, before)
        assert confirm("sample", result, snapshot, uia) == expected


def test_T_INS_009_confirmation_rejects_unrelated_whitespace_change() -> None:
    from wispr_clone.insertion.inserter import DispatchResult, confirm

    uia = FakeUiaApi()
    snapshot = _snapshot()
    uia.texts[snapshot.field] = " before sample"
    result = DispatchResult("paste", 4, "before")
    assert confirm("sample", result, snapshot, uia) == "uncertain"


def test_T_INS_010_korean_layout_and_known_apps_choose_paste() -> None:
    from wispr_clone.insertion.app_strategies import PASTE_APPS, choose_strategy

    snapshot = _snapshot()
    assert (
        choose_strategy(replace(snapshot, exe="unknown.exe", langid=0x0412)) == "paste"
    )
    assert (
        choose_strategy(replace(snapshot, exe="unknown.exe", langid=0x0409))
        == "unicode"
    )
    assert "notepad.exe" in PASTE_APPS
    for exe in PASTE_APPS:
        assert choose_strategy(replace(snapshot, exe=exe, langid=0x0409)) == "paste"
