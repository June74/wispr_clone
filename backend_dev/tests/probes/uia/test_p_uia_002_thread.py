"""P-UIA-002: UIA COM initialization belongs to the calling thread."""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

pytestmark = [pytest.mark.probe("uiautomation"), pytest.mark.windows]


def test_P_UIA_002_fresh_thread_requires_com_initialization() -> None:
    if sys.platform != "win32":
        pytest.skip("UI Automation probe requires Windows")

    import uiautomation  # type: ignore[import-not-found]

    uiautomation.Logger.SetLogFile("")

    with ThreadPoolExecutor(max_workers=1) as executor:
        uninitialized = executor.submit(uiautomation.GetFocusedControl)
        with pytest.raises(Exception, match="CoInitialize|UIAutomationCore|COM"):
            uninitialized.result()

    def initialized_call() -> object:
        uiautomation.InitializeUIAutomationInCurrentThread()
        try:
            return uiautomation.GetFocusedControl()
        finally:
            uiautomation.UninitializeUIAutomationInCurrentThread()

    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(initialized_call).result()
