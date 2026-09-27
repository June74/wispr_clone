"""T-UI-011: opt-in native HUD style, geometry, and focus check."""

from __future__ import annotations

import ctypes
import multiprocessing
import os
import sys
import time
from pathlib import Path
from queue import Empty
from typing import Any

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.windows, pytest.mark.manual]


class _Rect(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def _inspect_real_hud(result: Any) -> None:
    import webview

    from wispr_clone.ui.overlay import open_hud

    title = "Wispr Clone HUD"
    url = (Path(__file__).resolve().parents[2] / "web" / "hud.html").as_uri()
    handle = open_hud(webview, hud_url=url)
    # Separate WinDLL objects avoid changing pywebview's shared prototypes.
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
    user32.FindWindowW.argtypes = (ctypes.c_wchar_p, ctypes.c_wchar_p)
    user32.FindWindowW.restype = ctypes.c_void_p
    user32.GetForegroundWindow.argtypes = ()
    user32.GetForegroundWindow.restype = ctypes.c_void_p
    user32.GetWindowLongPtrW.argtypes = (ctypes.c_void_p, ctypes.c_int)
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.IsWindowVisible.argtypes = (ctypes.c_void_p,)
    user32.IsWindowVisible.restype = ctypes.c_bool
    user32.GetLayeredWindowAttributes.argtypes = (
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.c_ubyte),
        ctypes.POINTER(ctypes.c_ulong),
    )
    user32.GetLayeredWindowAttributes.restype = ctypes.c_bool
    user32.GetDpiForWindow.argtypes = (ctypes.c_void_p,)
    user32.GetDpiForWindow.restype = ctypes.c_uint
    user32.GetWindowRect.argtypes = (ctypes.c_void_p, ctypes.POINTER(_Rect))
    user32.GetWindowRect.restype = ctypes.c_bool
    dwmapi.DwmGetWindowAttribute.argtypes = (
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.c_void_p,
        ctypes.c_uint,
    )
    dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long

    def after_start() -> None:
        try:
            if not handle.events.shown.wait(5):
                raise AssertionError("HUD shown event did not fire")
            if not handle.prepared.wait(5):
                raise AssertionError("HUD native preparation did not finish")
            if not handle.native_ready:
                raise AssertionError("HUD native preparation did not succeed")
            hwnd = user32.FindWindowW(None, title)
            if not hwnd:
                raise AssertionError("HUD window was not found")
            foreground_before = user32.GetForegroundWindow()
            handle.show()
            time.sleep(0.5)  # Give any deferred activation a chance to occur.
            foreground_after = user32.GetForegroundWindow()
            rect = _Rect()
            if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                raise AssertionError("GetWindowRect failed")
            scale = user32.GetDpiForWindow(hwnd) / 96
            color_key = ctypes.c_ulong()
            alpha = ctypes.c_ubyte()
            alpha_flags = ctypes.c_ulong()
            if not user32.GetLayeredWindowAttributes(
                hwnd,
                ctypes.byref(color_key),
                ctypes.byref(alpha),
                ctypes.byref(alpha_flags),
            ):
                raise AssertionError("GetLayeredWindowAttributes failed")
            corner = ctypes.c_int()
            dwm_status = dwmapi.DwmGetWindowAttribute(
                hwnd, 33, ctypes.byref(corner), ctypes.sizeof(corner)
            )
            handle.hide()
            foreground_before_reshow = user32.GetForegroundWindow()
            handle.show()
            time.sleep(0.5)
            foreground_after_reshow = user32.GetForegroundWindow()
            result.put(
                (
                    "ok",
                    user32.IsWindowVisible(hwnd),
                    alpha.value,
                    alpha_flags.value,
                    user32.GetWindowLongPtrW(hwnd, -20),
                    hwnd,
                    foreground_before,
                    foreground_after,
                    foreground_before_reshow,
                    foreground_after_reshow,
                    (rect.right - rect.left, rect.bottom - rect.top),
                    scale,
                    corner.value if dwm_status == 0 else None,
                )
            )
        except BaseException as error:
            result.put(("error", type(error).__name__, str(error)))
        finally:
            handle.destroy()

    webview.start(func=after_start, gui="edgechromium", http_server=False)


def test_T_UI_011_real_hud_style_and_focus() -> None:
    if sys.platform != "win32" or os.environ.get("WISPR_REAL_GUI") != "1":
        pytest.skip("requires Windows and WISPR_REAL_GUI=1")

    context = multiprocessing.get_context("spawn")
    result = context.Queue()
    process = context.Process(target=_inspect_real_hud, args=(result,))
    process.start()
    try:
        process.join(20)
        if process.is_alive():
            pytest.fail("HUD GUI did not exit within 20 seconds")
        assert process.exitcode == 0
        try:
            measured = result.get_nowait()
        except Empty:
            pytest.fail("HUD GUI exited without reporting native state")
        assert measured[0] == "ok", measured
        (
            _,
            visible,
            alpha,
            alpha_flags,
            style,
            hwnd,
            foreground_before,
            foreground_after,
            foreground_before_reshow,
            foreground_after_reshow,
            size,
            scale,
            corner,
        ) = measured
        assert visible
        assert alpha == 255
        assert alpha_flags & 2  # LWA_ALPHA
        assert style & 0x80000  # WS_EX_LAYERED
        assert style & 0x80  # WS_EX_TOOLWINDOW
        assert style & 0x20  # WS_EX_TRANSPARENT
        assert style & 0x08000000  # WS_EX_NOACTIVATE
        assert not style & 0x40000  # WS_EX_APPWINDOW
        assert foreground_after == foreground_before
        assert foreground_after != hwnd
        assert foreground_after_reshow == foreground_before_reshow
        assert foreground_after_reshow != hwnd
        assert size == (round(272 * scale), round(44 * scale))
        assert corner == 2
    finally:
        if process.is_alive():
            process.terminate()
            process.join(2)
        result.close()
