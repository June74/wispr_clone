"""T-UI-003/004/005: native window creation, navigation, and release settings."""

from __future__ import annotations

import pytest
from fakes.webview import FakeWebview, Window

from wispr_clone.ui.overlay import open_hud
from wispr_clone.ui.windows import open_settings, start


def _loads(window: Window) -> list[str]:
    return [str(args[0]) for name, args in window.calls if name == "load_url"]


@pytest.mark.unit
def test_T_UI_003_hud_has_no_bridge_and_cannot_activate() -> None:
    webview = FakeWebview()
    allowed = "file:///bundled/hud.html"
    open_hud(webview, hud_url=allowed)
    window = webview.windows[0]
    assert window.options["url"] == allowed
    assert window.options["js_api"] is None
    assert window.options["focus"] is False
    assert window.options["on_top"] is True
    assert window.options["frameless"] is True
    assert window.options["resizable"] is False
    assert window.options["shadow"] is False
    assert window.options["transparent"] is True
    assert window.options["hidden"] is True
    assert window.options["width"] == 240
    assert window.options["height"] == 56


@pytest.mark.unit
@pytest.mark.parametrize("event_name", ["before_load", "loaded"])
@pytest.mark.parametrize(
    "destination", ["https://example.invalid/", "file:///other/hud.html", "about:blank"]
)
def test_T_UI_004_hud_navigation_is_restricted_to_its_bundled_file(
    event_name: str, destination: str
) -> None:
    webview = FakeWebview()
    allowed = "file:///bundled/hud.html"
    open_hud(webview, hud_url=allowed)
    hud = webview.windows[0]
    hud.url = destination

    getattr(hud.events, event_name).emit()

    assert _loads(hud) == [allowed]


@pytest.mark.unit
@pytest.mark.parametrize("event_name", ["before_load", "loaded"])
def test_T_UI_004_navigation_is_restricted_to_bundled_file(event_name: str) -> None:
    webview = FakeWebview()
    bridge = object()
    open_settings(webview, bridge, debug=False)
    settings = webview.windows[0]
    allowed = settings.url
    assert allowed is not None
    assert allowed.startswith("file:")
    assert allowed.endswith("/backend_dev/web/index.html")
    assert settings.options["js_api"] is bridge
    assert settings.options["min_size"] == (1100, 700)

    event = getattr(settings.events, event_name)
    settings.url = "https://example.invalid/escape"
    event.emit()
    assert _loads(settings) == [allowed]
    settings.url = "file:///other/local.html"
    event.emit()
    assert _loads(settings) == [allowed, allowed]
    settings.url = allowed + "?state=1#view"
    event.emit()
    assert _loads(settings) == [allowed, allowed]

    settings.url = allowed.upper()
    event.emit()
    assert _loads(settings) == [allowed, allowed]

    settings.url = allowed.replace("/index.html", "/%69ndex.html")
    event.emit()
    assert _loads(settings) == [allowed, allowed, allowed]
    settings.url = allowed.replace("file:///", "file://remote-host/")
    event.emit()
    assert _loads(settings) == [allowed, allowed, allowed, allowed]
    settings.url = "about:blank"
    event.emit()
    assert _loads(settings) == [allowed] * 5


@pytest.mark.unit
def test_T_UI_005_release_start_disables_http_server_downloads_and_devtools() -> None:
    webview = FakeWebview()
    start(webview, debug=False)
    assert webview.settings == {
        "ALLOW_DOWNLOADS": False,
        "ALLOW_FILE_URLS": True,
        "OPEN_EXTERNAL_LINKS_IN_BROWSER": False,
        "OPEN_DEVTOOLS_IN_DEBUG": False,
    }
    calls = [options for name, options in webview.calls if name == "start"]
    assert len(calls) == 1
    assert calls[0]["debug"] is False
    assert calls[0]["http_server"] is False
    assert calls[0]["private_mode"] is True
