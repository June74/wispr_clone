"""P-WEBVIEW-001: compare the fake's native API surface without opening a window."""

from __future__ import annotations

import inspect
import sys

import pytest
from fakes.webview import FakeWebview, WindowEvents

pytestmark = [pytest.mark.probe("pywebview"), pytest.mark.windows]


def test_P_WEBVIEW_001_real_module_supports_fake_surface() -> None:
    if sys.platform != "win32":
        pytest.skip("pywebview API probe requires Windows")

    import webview
    from webview.window import Window

    fake = FakeWebview()
    for name in ("create_window", "start"):
        real_parameters = inspect.signature(getattr(webview, name)).parameters
        fake_parameters = inspect.signature(getattr(fake, name)).parameters
        assert set(fake_parameters) - {"kwargs"} <= set(real_parameters)
    assert set(fake.settings) <= set(webview.settings)
    for name in (
        "run_js",
        "evaluate_js",
        "get_current_url",
        "load_url",
        "show",
        "hide",
        "destroy",
        "move",
        "resize",
        "on_top",
    ):
        assert hasattr(Window, name), name

    # Window.__init__ assigns the events to its container. Inspect its source
    # rather than constructing a native window.
    constructor_source = inspect.getsource(Window.__init__)
    for name in vars(WindowEvents()):
        assert f"self.events.{name} =" in constructor_source, name
