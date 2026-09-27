"""Non-activating, bridge-free HUD window."""

from __future__ import annotations

import logging
import sys
import threading
from typing import Any

from wispr_clone.ui.windows import _lock_navigation

HUD_WIDTH = 280
HUD_HEIGHT = 44
HUD_TITLE = "Wispr Clone HUD"
logger = logging.getLogger(__name__)


class HudHandle:
    """Expose the HUD's safe visibility controls and delegate its other APIs."""

    def __init__(self, window: Any) -> None:
        self._window = window
        self.native_ready = False
        self.hwnd: int | None = None
        self.prepared = threading.Event()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._window, name)

    def show(self) -> None:
        if self.native_ready:
            from wispr_clone.ui import win_hud

            win_hud.show(self.hwnd)
        else:
            self._window.show()

    def hide(self) -> None:
        if self.native_ready:
            from wispr_clone.ui import win_hud

            win_hud.hide(self.hwnd)
        else:
            self._window.hide()


def open_hud(webview: object, *, hud_url: str) -> HudHandle:
    """Create the hidden HUD and prepare its native window after it is shown."""
    placement: dict[str, int] = {}
    screens = getattr(webview, "screens", ())
    if screens:
        primary = next(
            (screen for screen in screens if screen.x == 0 and screen.y == 0),
            screens[0],
        )
        placement = {
            "x": primary.x + (primary.width - HUD_WIDTH) // 2,
            "y": primary.y + primary.height - HUD_HEIGHT - 48,
        }
    window = webview.create_window(  # type: ignore[attr-defined]
        HUD_TITLE,
        url=hud_url,
        js_api=None,
        frameless=True,
        on_top=True,
        focus=False,
        resizable=False,
        shadow=False,
        transparent=False,
        background_color="#1b161d",
        min_size=(1, 1),
        width=HUD_WIDTH,
        height=HUD_HEIGHT,
        hidden=True,
        **placement,
    )
    handle = HudHandle(window)

    def make_visible() -> None:
        from System import Action  # type: ignore[import-not-found]  # pythonnet

        window.native.Invoke(Action(lambda: setattr(window.native, "Visible", True)))

    def on_shown(*_args: object, **_kwargs: object) -> None:
        try:
            try:
                window.resize(HUD_WIDTH, HUD_HEIGHT)
            except Exception:
                logger.warning("HUD_RESIZE_FAILED")
            if sys.platform == "win32":
                try:
                    from wispr_clone.ui import win_hud

                    handle.hwnd = win_hud.prepare(HUD_TITLE, make_visible)
                    handle.native_ready = handle.hwnd is not None
                except Exception:
                    logger.warning("HUD_PREPARE_FAILED")
        finally:
            handle.prepared.set()

    window.events.shown += on_shown
    _lock_navigation(window, hud_url)
    return handle
