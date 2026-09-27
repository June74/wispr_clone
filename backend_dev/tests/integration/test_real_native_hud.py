"""T-UI-015: opt-in real Win32 HUD style, size, focus and shutdown check."""

from __future__ import annotations

import ctypes
import os
import sys
import time

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.windows, pytest.mark.manual]


class _Rect(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def test_T_UI_015_real_native_hud() -> None:
    if sys.platform != "win32" or os.environ.get("WISPR_REAL_GUI") != "1":
        pytest.skip("requires Windows and WISPR_REAL_GUI=1")

    from wispr_clone.ui.hud_model import layout
    from wispr_clone.ui.native_hud import NativeHud

    # Private WinDLL instances keep pywebview's shared function prototypes intact.
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.FindWindowW.argtypes = (ctypes.c_wchar_p, ctypes.c_wchar_p)
    user32.FindWindowW.restype = ctypes.c_void_p
    user32.GetForegroundWindow.argtypes = ()
    user32.GetForegroundWindow.restype = ctypes.c_void_p
    user32.GetWindowLongPtrW.argtypes = (ctypes.c_void_p, ctypes.c_int)
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.IsWindowVisible.argtypes = (ctypes.c_void_p,)
    user32.IsWindowVisible.restype = ctypes.c_bool
    user32.GetWindowRect.argtypes = (ctypes.c_void_p, ctypes.POINTER(_Rect))
    user32.GetWindowRect.restype = ctypes.c_bool
    user32.GetDpiForWindow.argtypes = (ctypes.c_void_p,)
    user32.GetDpiForWindow.restype = ctypes.c_uint

    hud = NativeHud()
    try:
        before = user32.GetForegroundWindow()
        hud.show()
        deadline = time.monotonic() + 5
        hwnd = None
        while time.monotonic() < deadline:
            hwnd = user32.FindWindowW("WisprCloneNativeHud", "Wispr Clone HUD")
            if hwnd and user32.IsWindowVisible(hwnd):
                break
            time.sleep(0.02)
        assert hwnd and user32.IsWindowVisible(hwnd)
        assert user32.GetForegroundWindow() == before
        style = user32.GetWindowLongPtrW(hwnd, -20)
        for flag in (0x80000, 0x80, 0x20, 0x08000000, 0x8):
            assert style & flag == flag
        rect = _Rect()
        assert user32.GetWindowRect(hwnd, ctypes.byref(rect))
        scale = user32.GetDpiForWindow(hwnd) / 96
        expected = layout(scale)
        assert (rect.right - rect.left, rect.bottom - rect.top) == (
            expected.window_width,
            expected.window_height,
        )
        hud.publish_event(
            {"name": "run:state", "run_id": "r", "version": 1, "status": "recording"}
        )
        hud.publish_event({"name": "audio:level", "run_id": "r", "bands": [0.5] * 12})
        hud.hide()
        time.sleep(0.05)
        assert not user32.IsWindowVisible(hwnd)
        assert user32.GetForegroundWindow() == before
        hud.show()
        time.sleep(0.05)
        assert user32.IsWindowVisible(hwnd)
        assert user32.GetForegroundWindow() == before
    finally:
        start = time.monotonic()
        hud.destroy()
        assert time.monotonic() - start < 2
        assert not hud._thread.is_alive()
