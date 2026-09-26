"""Isolated Windows desktop dependency checks; no input is sent."""

import ctypes
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
    _desktop()
    pytest.skip("work order forbids touching the real clipboard")


def test_P_WIN32_003_sendinput_and_idle_symbols_exist() -> None:
    _desktop()
    assert callable(ctypes.windll.user32.SendInput)
    assert callable(ctypes.windll.user32.GetLastInputInfo)
