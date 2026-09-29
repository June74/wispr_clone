"""Regression tests for the pywebview HUD window, the fallback for the native HUD."""

from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace

import pytest
from fakes.webview import FakeWebview, Screen

from wispr_clone.ui.overlay import open_hud


@pytest.mark.unit
def test_T_UI_008_hud_window_geometry_and_creation_options() -> None:
    webview = FakeWebview()
    webview.screens = [Screen(-1600, 0, 1600, 900), Screen(0, 0, 3440, 1440)]

    open_hud(webview, hud_url="file:///bundled/hud.html")

    assert len(webview.windows) == 1
    assert webview.calls[0][0] == "create_window"
    options = webview.calls[0][1]
    assert options["title"] == "Wispr Clone HUD"
    assert options["url"] == "file:///bundled/hud.html"
    assert {
        key: options[key]
        for key in (
            "js_api",
            "frameless",
            "on_top",
            "focus",
            "shadow",
            "hidden",
            "transparent",
            "background_color",
            "min_size",
            "width",
            "height",
            "x",
            "y",
        )
    } == {
        "js_api": None,
        "frameless": True,
        "on_top": True,
        "focus": False,
        "shadow": False,
        "hidden": True,
        "transparent": False,
        "background_color": "#1b161d",
        "min_size": (1, 1),
        "width": 272,
        "height": 44,
        "x": (3440 - 272) // 2,
        "y": 1440 - 44 - 48,
    }


@pytest.mark.unit
def test_T_UI_009_shown_resizes_before_native_prepare(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    win_hud = importlib.import_module("wispr_clone.ui.win_hud")
    monkeypatch.setattr(sys, "platform", "win32")
    calls: list[tuple[str, object]] = []

    def prepare(title: str, make_visible: object) -> int:
        calls.append(("prepare", title))
        assert callable(make_visible)
        return 1234

    monkeypatch.setattr(win_hud, "prepare", prepare)
    webview = FakeWebview()
    hud = open_hud(webview, hud_url="file:///bundled/hud.html")
    window = webview.windows[0]
    assert window.events.shown.handlers
    monkeypatch.setattr(
        window,
        "resize",
        lambda width, height: calls.append(("resize", (width, height))),
    )

    window.events.shown.emit()

    assert hud is not window
    assert hud.prepared.is_set()
    assert hud.native_ready is True
    assert calls == [
        ("resize", (272, 44)),
        ("prepare", "Wispr Clone HUD"),
    ]


@pytest.mark.unit
@pytest.mark.parametrize("failure", ["resize", "prepare", "missing_window"])
def test_T_UI_009_shown_handler_swallows_native_failures(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    win_hud = importlib.import_module("wispr_clone.ui.win_hud")
    monkeypatch.setattr(sys, "platform", "win32")
    webview = FakeWebview()
    hud = open_hud(webview, hud_url="file:///bundled/hud.html")
    window = webview.windows[0]

    def fail_resize(_width: int, _height: int) -> None:
        raise RuntimeError("native resize failed")

    def fail_prepare(_title: str, _make_visible: object) -> None:
        raise RuntimeError("native prepare failed")

    if failure == "resize":
        monkeypatch.setattr(window, "resize", fail_resize)
        monkeypatch.setattr(win_hud, "prepare", lambda _title, _visible: 1234)
    elif failure == "missing_window":
        monkeypatch.setattr(win_hud, "prepare", lambda _title, _visible: None)
    else:
        monkeypatch.setattr(win_hud, "prepare", fail_prepare)

    window.events.shown.emit()
    assert hud.prepared.is_set()
    assert hud.native_ready is (failure == "resize")


@pytest.mark.unit
@pytest.mark.parametrize("native_ready", [False, True])
def test_T_UI_010_handle_routes_visibility_and_delegates(
    monkeypatch: pytest.MonkeyPatch, native_ready: bool
) -> None:
    win_hud = importlib.import_module("wispr_clone.ui.win_hud")
    monkeypatch.setattr(sys, "platform", "win32")
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(win_hud, "prepare", lambda _title, _visible: 1234)
    monkeypatch.setattr(win_hud, "show", lambda hwnd: calls.append(("show", hwnd)))
    monkeypatch.setattr(win_hud, "hide", lambda hwnd: calls.append(("hide", hwnd)))
    webview = FakeWebview()
    webview.started = True
    hud = open_hud(webview, hud_url="file:///bundled/hud.html")
    window = webview.windows[0]
    if native_ready:
        window.events.shown.emit()
    else:
        # The fallback path represents a call before the shown event is delivered.
        monkeypatch.setattr(window.events.shown, "emit", lambda: None)

    hud.show()
    hud.hide()
    hud.run_js("window.test()")
    assert hud.events is window.events
    hud.destroy()

    assert calls == ([("show", 1234), ("hide", 1234)] if native_ready else [])
    assert window.calls[-2:] == [
        ("run_js", ("window.test()",)),
        ("destroy", ()),
    ]
    assert [name for name, _args in window.calls if name in {"show", "hide"}] == (
        [] if native_ready else ["show", "hide"]
    )


@pytest.mark.unit
def test_T_UI_010_prepare_returns_none_off_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    win_hud = importlib.import_module("wispr_clone.ui.win_hud")
    monkeypatch.setattr(win_hud.sys, "platform", "linux")

    assert win_hud.prepare("Wispr Clone HUD", lambda: None) is None


@pytest.mark.unit
def test_T_UI_010_prepare_returns_none_when_window_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    win_hud = importlib.import_module("wispr_clone.ui.win_hud")
    monkeypatch.setattr(win_hud.sys, "platform", "win32")
    calls: list[tuple[object, object]] = []

    def find_window(class_name: object, title: object) -> int:
        calls.append((class_name, title))
        return 0

    user32 = SimpleNamespace(FindWindowW=find_window)
    monkeypatch.setattr(
        win_hud.ctypes, "WinDLL", lambda _name, **_kwargs: user32, raising=False
    )

    assert win_hud.prepare("Wispr Clone HUD", lambda: None) is None
    assert calls == [(None, "Wispr Clone HUD")]
