"""T-INS-004 isolated pywin32 clipboard format contract."""

import sys
from types import ModuleType


def test_T_INS_004_real_win32_sets_three_zero_dword_formats(monkeypatch) -> None:
    from wispr_clone.insertion.win32 import EXCLUSION_FORMATS, RealWin32

    clipboard = ModuleType("win32clipboard")
    calls: list[tuple[str, object, object]] = []
    formats = {name: index + 100 for index, name in enumerate(EXCLUSION_FORMATS)}
    clipboard.OpenClipboard = lambda: calls.append(("open", None, None))
    clipboard.EmptyClipboard = lambda: calls.append(("empty", None, None))
    clipboard.CloseClipboard = lambda: calls.append(("close", None, None))
    clipboard.RegisterClipboardFormat = lambda name: formats[name]
    clipboard.SetClipboardData = lambda fmt, value: calls.append(("set", fmt, value))
    monkeypatch.setitem(sys.modules, "win32clipboard", clipboard)
    win32con = ModuleType("win32con")
    win32con.CF_UNICODETEXT = 13
    monkeypatch.setitem(sys.modules, "win32con", win32con)
    RealWin32().set_clipboard("synthetic", exclusion_formats=True)
    for fmt in formats.values():
        assert ("set", fmt, b"\x00\x00\x00\x00") in calls
