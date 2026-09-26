"""Isolated Windows desktop dependency checks; no input is sent."""

import ctypes
import os
import sys

import pytest

pytestmark = [pytest.mark.probe("pywin32"), pytest.mark.windows]


def _desktop() -> None:
    if sys.platform != "win32":
        pytest.skip("Windows pywin32 desktop probe; this runner is not Windows")
    import win32gui

    if not win32gui.GetDesktopWindow():
        pytest.skip("interactive desktop is unavailable")


def test_P_WIN32_001_exclusion_formats_register() -> None:
    _desktop()
    import win32clipboard

    for name in (
        "ExcludeClipboardContentFromMonitorProcessing",
        "CanIncludeInClipboardHistory",
        "CanUploadToCloudClipboard",
    ):
        assert win32clipboard.RegisterClipboardFormat(name) > 0


def test_P_WIN32_002_synthetic_clipboard_round_trip() -> None:
    if os.environ.get("CI") != "true":
        pytest.skip("clipboard round trip runs on hosted CI only")
    _desktop()
    import win32clipboard
    import win32con

    try:
        win32clipboard.OpenClipboard()
    except Exception as error:
        pytest.skip(f"clipboard unavailable: {type(error).__name__}")
    try:
        previous = (
            win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
            if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT)
            else None
        )
    finally:
        win32clipboard.CloseClipboard()

    try:
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(
                win32con.CF_UNICODETEXT, "synthetic P-WIN32-002"
            )
        finally:
            win32clipboard.CloseClipboard()
        win32clipboard.OpenClipboard()
        try:
            assert win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT) == (
                "synthetic P-WIN32-002"
            )
        finally:
            win32clipboard.CloseClipboard()
    finally:
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            if previous is not None:
                win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, previous)
        finally:
            win32clipboard.CloseClipboard()


def test_P_WIN32_003_sendinput_and_idle_symbols_exist() -> None:
    _desktop()
    assert callable(ctypes.windll.user32.SendInput)
    assert callable(ctypes.windll.user32.GetLastInputInfo)
