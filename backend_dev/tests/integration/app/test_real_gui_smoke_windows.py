"""T-APP-043: opt-in real Windows GUI startup and orderly window close."""

from __future__ import annotations

import ctypes
import os
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from wispr_clone.app import App, real_factories

# pywebview 6.2.1 (platforms/winforms.py:757) creates its WebView2 cache with
# tempfile.TemporaryDirectory().name and never cleans it up. Ignore exactly that
# upstream warning.
pytestmark = [
    pytest.mark.integration,
    pytest.mark.windows,
    pytest.mark.manual,
    pytest.mark.filterwarnings(
        "ignore:Implicitly cleaning up <TemporaryDirectory:ResourceWarning"
    ),
    pytest.mark.filterwarnings(
        "ignore:Exception ignored in. <finalize object"
        ":pytest.PytestUnraisableExceptionWarning"
    ),
]


def test_T_APP_043_real_gui_starts_and_closes(tmp_path: Path) -> None:
    if sys.platform != "win32" or os.environ.get("WISPR_REAL_GUI") != "1":
        pytest.skip("requires Windows and WISPR_REAL_GUI=1")

    import webview

    # Keep Win32 prototypes private from pywebview's own user32 bindings.
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.FindWindowW.argtypes = (ctypes.c_wchar_p, ctypes.c_wchar_p)
    user32.FindWindowW.restype = ctypes.c_void_p
    user32.IsWindow.argtypes = (ctypes.c_void_p,)
    user32.IsWindow.restype = ctypes.c_bool

    observed: list[set[str]] = []
    native_hud_found: list[bool] = []
    errors: list[BaseException] = []

    class HookedWebview:
        def __getattr__(self, name: str) -> Any:
            return getattr(webview, name)

        def start(self, **kwargs: Any) -> None:
            def inspect_and_close() -> None:
                time.sleep(2)
                try:
                    observed.append({window.title for window in webview.windows})
                    hwnd = user32.FindWindowW("WisprCloneNativeHud", "Wispr Clone HUD")
                    native_hud_found.append(bool(hwnd and user32.IsWindow(hwnd)))
                except BaseException as error:
                    errors.append(error)
                finally:
                    for window in reversed(tuple(webview.windows)):
                        try:
                            window.destroy()
                        except BaseException as error:
                            errors.append(error)

            webview.start(func=inspect_and_close, **kwargs)

    factories = replace(real_factories(), webview=HookedWebview)
    app = App(factories, data_dir=tmp_path)

    assert app.run() == 0
    assert errors == []
    assert observed == [{"Wispr Clone"}]
    assert native_hud_found == [True]
    assert not (Path.cwd() / "@AutomationLog.txt").exists()
