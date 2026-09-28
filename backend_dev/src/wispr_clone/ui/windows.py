"""Settings window creation, bundled navigation lock, and GUI loop startup."""

from __future__ import annotations

import logging
import sys
import threading
from typing import Any
from urllib.parse import urldefrag, urlsplit

from wispr_clone import config
from wispr_clone.ui.bridge import attach_window_controls

logger = logging.getLogger(__name__)


def _settings_url() -> str:
    return (config.resource_root() / "web" / "index.html").as_uri()


def _normalized_url(url: str | None) -> tuple[str, str, str, str, str] | None:
    if url is None:
        return None
    parts = urlsplit(urldefrag(url)[0])
    path = parts.path.casefold() if parts.scheme.casefold() == "file" else parts.path
    return (parts.scheme.casefold(), parts.netloc.casefold(), path, "", "")


def _lock_navigation(window: object, allowed: str) -> None:
    """Keep a native window on its single bundled page."""

    blocks = 0
    failures = 0

    def check_navigation(*_args: object, **_kwargs: object) -> None:
        nonlocal blocks, failures
        try:
            current = window.get_current_url()  # type: ignore[attr-defined]
            if _normalized_url(current) != _normalized_url(allowed):
                blocks += 1
                window.load_url(allowed)  # type: ignore[attr-defined]
        except Exception:
            failures += 1

    window.events.loaded += check_navigation  # type: ignore[attr-defined]


class WindowControls:
    """Apply title-bar, tray and relaunch commands to the native settings window.

    While ``hide_on_close`` is set (the tray icon is running), closing the
    window only hides it; ``quit`` and a Windows sign-out really close it.
    """

    def __init__(self, window: object | None = None) -> None:
        self.window: Any = window
        self.hwnd: int | None = None
        self.hide_on_close = False
        self.quitting = False

    def __call__(self, name: str) -> bool:
        from wispr_clone.ui import win_frame

        window = self.window
        if name == "window_close":
            if self.hide_on_close and not self.quitting:
                window.hide()
            else:
                window.destroy()
            return True
        if self.hwnd is None:
            # No native frame: the OS caption is still there; mirror it.
            if name == "window_minimize":
                window.minimize()
                return True
            return False
        if name == "window_drag":
            return win_frame.begin_drag(self.hwnd)
        if name == "window_minimize":
            return win_frame.minimize(self.hwnd)
        if name == "window_toggle_maximize":
            return win_frame.toggle_maximize(self.hwnd)
        return False

    def show(self) -> None:
        from wispr_clone.ui import win_frame

        self.window.show()
        win_frame.bring_to_front(self.hwnd)

    def quit(self) -> None:
        self.quitting = True
        self.window.destroy()

    def on_closing(self) -> bool:
        """pywebview closing handler: False cancels the close and hides instead."""
        if self.hide_on_close and not self.quitting:
            try:
                self.window.hide()
            except Exception:
                logger.warning("SETTINGS_HIDE_FAILED")
            return False
        return True

    def end_session(self) -> None:
        self.quitting = True


def open_settings(
    webview: object,
    api_bridge: object,
    *,
    debug: bool,
    controls: WindowControls | None = None,
    start_hidden: bool = False,
) -> object:
    """Create the sole bridged window and constrain it to the bundled page.

    The window starts hidden so the native caption can be removed before the
    first paint; it is then shown unless ``start_hidden`` (launch at login).
    """
    allowed = _settings_url()
    window = webview.create_window(  # type: ignore[attr-defined]
        "Wispr Clone",
        url=allowed,
        js_api=api_bridge,
        width=1180,
        height=760,
        min_size=(1100, 700),
        hidden=True,
    )
    if controls is None:
        controls = WindowControls()
    controls.window = window
    attach_window_controls(api_bridge, controls)

    prepared: list[bool] = []

    def on_shown(*_args: object, **_kwargs: object) -> None:
        if prepared:
            return
        prepared.append(True)
        try:
            if sys.platform == "win32":
                controls.hwnd = _install_frame(window, controls)
        except Exception:
            logger.warning("SETTINGS_FRAME_FAILED")
        finally:
            if not start_hidden:
                window.show()

    window.events.shown += on_shown
    window.events.closing += controls.on_closing
    _lock_navigation(window, allowed)
    return window


def _install_frame(window: object, controls: WindowControls) -> int | None:
    """Remove the native caption on the GUI thread; return the frame's HWND."""
    from System import Action  # type: ignore[import-not-found]  # pythonnet

    from wispr_clone.ui import win_frame

    native = window.native  # type: ignore[attr-defined]
    hwnd = int(native.Handle.ToInt64())
    installed: list[bool] = []

    def on_show() -> None:
        # Runs on the GUI thread, where pywebview's show() is a no-op.
        threading.Thread(target=controls.show, name="wispr-show", daemon=True).start()

    def install() -> None:
        installed.append(
            win_frame.install(
                hwnd, on_show=on_show, on_session_end=controls.end_session
            )
        )

    native.Invoke(Action(install))
    if not installed or not installed[0]:
        logger.warning("SETTINGS_FRAME_UNAVAILABLE")
        return None
    return hwnd


def start(webview: object, *, debug: bool) -> None:
    """Configure the local-file security boundary and own the main GUI loop."""
    webview.settings["ALLOW_DOWNLOADS"] = False  # type: ignore[attr-defined]
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = False  # type: ignore[attr-defined]
    webview.settings["OPEN_DEVTOOLS_IN_DEBUG"] = False  # type: ignore[attr-defined]
    webview.settings["ALLOW_FILE_URLS"] = True  # type: ignore[attr-defined]
    webview.start(debug=debug, http_server=False, private_mode=True)  # type: ignore[attr-defined]
