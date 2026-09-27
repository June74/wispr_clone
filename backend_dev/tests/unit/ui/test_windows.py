"""T-UI-003/004/005: native window creation, navigation, and release settings."""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

import pytest
from fakes.webview import FakeWebview, Screen, WebViewException, Window

from wispr_clone.ui.overlay import open_hud
from wispr_clone.ui.windows import open_settings, start


def _loads(window: Window) -> list[str]:
    return [str(args[0]) for name, args in window.calls if name == "load_url"]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("method", "args"),
    [
        ("move", (1, 2)),
        ("resize", (3, 4)),
        ("show", ()),
        ("hide", ()),
        ("load_url", ("file:///other.html",)),
        ("run_js", ("window.test()",)),
        ("evaluate_js", ("window.test()",)),
        ("get_current_url", ()),
        ("destroy", ()),
    ],
)
def test_fake_window_methods_require_webview_start(
    method: str, args: tuple[object, ...]
) -> None:
    webview = FakeWebview()
    window = webview.create_window("settings")
    window.events.loaded += lambda: None

    with pytest.raises(WebViewException, match="^Main window failed to start$"):
        getattr(window, method)(*args)
    assert window.calls == []

    webview.start()
    getattr(window, method)(*args)
    assert window.calls == [(method, args)]


@pytest.mark.unit
def test_fake_start_emits_before_load_before_window_is_shown() -> None:
    webview = FakeWebview()
    window = webview.create_window("settings")
    events: list[str] = []

    def before_load() -> None:
        events.append("before_load")
        with pytest.raises(WebViewException, match="^Main window failed to start$"):
            window.get_current_url()

    def loaded() -> None:
        events.append("loaded")
        assert window.get_current_url() is None

    window.events.before_load += before_load
    window.events.shown += lambda: events.append("shown")
    window.events.loaded += loaded

    webview.start()

    assert events == ["before_load", "shown", "loaded"]


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
    assert window.options["transparent"] is False
    assert window.options["background_color"] == "#1b161d"
    assert window.options["min_size"] == (1, 1)
    assert window.options["hidden"] is True
    assert window.options["width"] == 280
    assert window.options["height"] == 44


@pytest.mark.unit
def test_T_UI_007_hud_uses_origin_screen_and_skips_placement_without_screens() -> None:
    webview = FakeWebview()
    webview.screens = [Screen(-1920, 0, 1920, 1080), Screen(0, 0, 3440, 1440)]

    open_hud(webview, hud_url="file:///bundled/hud.html")

    assert webview.windows[0].options["x"] == (3440 - 280) // 2
    assert webview.windows[0].options["y"] == 1440 - 44 - 48
    assert all(name != "move" for name, _ in webview.windows[0].calls)

    webview.screens = []
    open_hud(webview, hud_url="file:///bundled/hud.html")
    assert webview.windows[1].options["x"] is None
    assert webview.windows[1].options["y"] is None
    assert all(name != "move" for name, _ in webview.windows[1].calls)


@pytest.mark.unit
@pytest.mark.parametrize(
    "destination", ["https://example.invalid/", "file:///other/hud.html", "about:blank"]
)
def test_T_UI_004_hud_navigation_is_restricted_to_its_bundled_file(
    destination: str,
) -> None:
    webview = FakeWebview()
    allowed = "file:///bundled/hud.html"
    open_hud(webview, hud_url=allowed)
    webview.start()
    hud = webview.windows[0]
    hud.url = destination

    hud.events.before_load.emit()
    assert _loads(hud) == []
    hud.events.loaded.emit()

    assert _loads(hud) == [allowed]


@pytest.mark.unit
def test_T_UI_004_navigation_is_restricted_to_bundled_file() -> None:
    webview = FakeWebview()
    bridge = object()
    open_settings(webview, bridge, debug=False)
    webview.start()
    settings = webview.windows[0]
    allowed = settings.url
    assert allowed is not None
    assert allowed.startswith("file:")
    assert allowed.endswith("/backend_dev/web/index.html")
    assert settings.options["js_api"] is bridge
    assert settings.options["min_size"] == (1100, 700)

    event = settings.events.loaded
    settings.url = "https://example.invalid/escape"
    settings.events.before_load.emit()
    assert _loads(settings) == []
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
    settings.url = urlunsplit(urlsplit(allowed)._replace(netloc="remote-host"))
    event.emit()
    assert _loads(settings) == [allowed, allowed, allowed, allowed]
    settings.url = "about:blank"
    event.emit()
    assert _loads(settings) == [allowed] * 5


@pytest.mark.unit
def test_T_UI_004_navigation_handler_exception_does_not_escape_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    webview = FakeWebview()
    settings = open_settings(webview, object(), debug=False)
    webview.start()
    calls = 0

    def fail_to_read_url() -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("failed to read URL")

    monkeypatch.setattr(settings, "get_current_url", fail_to_read_url)

    settings.events.loaded.emit()

    assert calls == 1


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
