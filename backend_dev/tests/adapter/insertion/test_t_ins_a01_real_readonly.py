"""Read-only checks of the real Windows insertion adapters."""

import sys

import pytest

from wispr_clone.insertion.uia import RealUia
from wispr_clone.insertion.win32 import RealWin32


def _foreground() -> int:
    if sys.platform != "win32":
        pytest.skip("Windows insertion adapter requires Windows")
    import win32gui

    if not win32gui.GetDesktopWindow():
        pytest.skip("interactive desktop is unavailable")
    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        pytest.skip("interactive foreground window is unavailable")
    return hwnd


def _focused(uia: RealUia) -> tuple[int, ...]:
    rid = uia.focused_element()
    if rid is None:
        pytest.skip("focused UI Automation element is unavailable")
    assert isinstance(rid, tuple)
    assert all(isinstance(part, int) for part in rid)
    return rid


@pytest.mark.adapter("pywin32")
@pytest.mark.windows
def test_T_INS_A01_real_window_process_shape() -> None:
    hwnd = _foreground()
    pid, exe = RealWin32().window_process(hwnd)
    assert isinstance(pid, int) and pid > 0
    assert isinstance(exe, str)


@pytest.mark.adapter("pywin32")
@pytest.mark.windows
def test_T_INS_A02_real_keyboard_layout_shape() -> None:
    hwnd = _foreground()
    langid = RealWin32().keyboard_layout(hwnd)
    assert isinstance(langid, int)
    assert 0 <= langid <= 0xFFFF


@pytest.mark.adapter("uiautomation")
@pytest.mark.windows
def test_T_INS_A03_real_selected_tab_shape() -> None:
    hwnd = _foreground()
    tab = RealUia().selected_tab(hwnd)
    assert tab is None or (
        isinstance(tab, tuple) and all(isinstance(part, int) for part in tab)
    )


@pytest.mark.adapter("uiautomation")
@pytest.mark.windows
def test_T_INS_A04_real_focused_element_properties() -> None:
    _foreground()
    uia = RealUia()
    rid = _focused(uia)
    control_type = uia.element_control_type(rid)
    assert isinstance(control_type, str) and control_type
    assert isinstance(uia.is_on_screen(rid), bool)


@pytest.mark.adapter("uiautomation")
@pytest.mark.windows
def test_T_INS_A05_real_focused_element_text_shape() -> None:
    _foreground()
    uia = RealUia()
    text = uia.element_text(_focused(uia))
    assert text is None or isinstance(text, str)
