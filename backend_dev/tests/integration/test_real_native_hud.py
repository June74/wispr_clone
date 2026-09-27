"""T-UI-015: opt-in real Win32 HUD style, size, focus and shutdown check."""

from __future__ import annotations

import ctypes
import logging
import os
import re
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


def test_T_UI_015_real_native_hud(caplog: pytest.LogCaptureFixture) -> None:
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
    user32.PostMessageW.argtypes = (
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.c_size_t,
        ctypes.c_ssize_t,
    )
    user32.PostMessageW.restype = ctypes.c_bool

    cancelled: list[None] = []
    hud = NativeHud(on_cancel=lambda: cancelled.append(None))
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
        deadline = time.monotonic() + 5
        while hud.frames_drawn < 1 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert hud.frames_drawn >= 1
        style = user32.GetWindowLongPtrW(hwnd, -20)
        for flag in (0x80000, 0x80, 0x08000000, 0x8):
            assert style & flag == flag
        assert not style & 0x20  # WS_EX_TRANSPARENT
        rect = _Rect()
        assert user32.GetWindowRect(hwnd, ctypes.byref(rect))
        scale = user32.GetDpiForWindow(hwnd) / 96
        expected = layout(scale)
        assert (rect.right - rect.left, rect.bottom - rect.top) == (
            expected.window_width,
            expected.window_height,
        )
        cancel = expected.cancel_rect
        x = round((cancel.left + cancel.right) / 2)
        y = round((cancel.top + cancel.bottom) / 2)
        lparam = (y << 16) | x
        assert user32.PostMessageW(hwnd, 0x0200, 0, lparam)  # WM_MOUSEMOVE
        time.sleep(0.05)
        assert user32.GetForegroundWindow() == before
        elsewhere = (round(expected.dot_center[1]) << 16) | round(
            expected.dot_center[0]
        )
        assert user32.PostMessageW(hwnd, 0x0201, 1, elsewhere)
        assert user32.PostMessageW(hwnd, 0x0202, 0, elsewhere)
        time.sleep(0.05)
        assert cancelled == []
        assert user32.PostMessageW(hwnd, 0x0201, 1, lparam)  # WM_LBUTTONDOWN
        assert user32.PostMessageW(hwnd, 0x0202, 0, lparam)  # WM_LBUTTONUP
        deadline = time.monotonic() + 2
        while len(cancelled) < 1 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert len(cancelled) == 1
        assert user32.GetForegroundWindow() == before
        hud.publish_event(
            {"name": "run:state", "run_id": "r", "version": 1, "status": "recording"}
        )
        time.sleep(0.1)
        recording_start_frames = hud.frames_drawn
        deadline = time.monotonic() + 2
        while (
            hud.frames_drawn <= recording_start_frames and time.monotonic() < deadline
        ):
            time.sleep(0.05)
        assert hud.frames_drawn > recording_start_frames
        assert user32.GetForegroundWindow() == before
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
    assert not [
        record.getMessage()
        for record in caplog.records
        if record.levelno >= logging.WARNING
        and re.search(r"\bNATIVE_HUD_[A-Z_]*FAILED\b", record.getMessage())
    ]


def test_T_UI_015b_multiple_real_native_huds() -> None:
    if sys.platform != "win32" or os.environ.get("WISPR_REAL_GUI") != "1":
        pytest.skip("requires Windows and WISPR_REAL_GUI=1")

    from wispr_clone.ui.native_hud import NativeHud

    def wait_for_frame(hud: NativeHud) -> None:
        hud.show()
        deadline = time.monotonic() + 5
        while hud.frames_drawn < 1 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert hud.frames_drawn >= 1

    def destroy_and_time(hud: NativeHud) -> tuple[float, bool]:
        start = time.monotonic()
        hud.destroy()
        elapsed = time.monotonic() - start
        stopped = hud._thread is not None and not hud._thread.is_alive()
        return elapsed, stopped

    # Reuse of the registered window class must work after the first HUD exits.
    for _ in range(2):
        hud = NativeHud()
        try:
            assert hud.available
            wait_for_frame(hud)
        finally:
            elapsed, stopped = destroy_and_time(hud)
        assert elapsed < 2 and stopped

    # Both windows must receive their own messages while alive together.
    huds = [NativeHud(), NativeHud()]
    try:
        assert all(hud.available for hud in huds)
        for hud in huds:
            hud.show()
        deadline = time.monotonic() + 5
        while any(hud.frames_drawn < 1 for hud in huds) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert all(hud.frames_drawn >= 1 for hud in huds)
    finally:
        shutdowns = [destroy_and_time(hud) for hud in huds]
    assert all(elapsed < 2 and stopped for elapsed, stopped in shutdowns)
