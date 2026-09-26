"""Isolated UI Automation import and root control probe."""

import importlib.metadata
import sys

import pytest

pytestmark = [pytest.mark.probe("uiautomation"), pytest.mark.windows]


def test_P_UIA_001_root_control_and_pin() -> None:
    if sys.platform != "win32":
        pytest.skip("uiautomation desktop probe requires Windows")
    import win32gui

    if not win32gui.GetDesktopWindow():
        pytest.skip("interactive desktop is unavailable")
    import uiautomation

    assert importlib.metadata.version("uiautomation") == "2.0.29"
    root = uiautomation.GetRootControl()
    if root is None:
        pytest.skip("UI Automation root unavailable without interactive desktop")
    assert isinstance(root.ControlTypeName, str)
