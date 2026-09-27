"""T-APP-043: opt-in real Windows GUI startup and orderly window close."""

from __future__ import annotations

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

    observed: list[set[str]] = []
    errors: list[BaseException] = []

    class HookedWebview:
        def __getattr__(self, name: str) -> Any:
            return getattr(webview, name)

        def start(self, **kwargs: Any) -> None:
            def inspect_and_close() -> None:
                time.sleep(2)
                try:
                    observed.append({window.title for window in webview.windows})
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
    assert observed == [{"Wispr Clone", "Wispr Clone HUD"}]
    assert not (Path.cwd() / "@AutomationLog.txt").exists()
