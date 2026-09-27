"""Non-activating, bridge-free HUD window."""

from __future__ import annotations

from typing import Protocol, cast

from wispr_clone.ui.windows import _lock_navigation


class HudWindow(Protocol):
    def show(self) -> None: ...

    def hide(self) -> None: ...


def open_hud(webview: object, *, hud_url: str) -> HudWindow:
    """Create a hidden HUD with no JS API and place it near screen bottom."""
    placement: dict[str, int] = {}
    screens = getattr(webview, "screens", ())
    if screens:
        primary = next(
            (screen for screen in screens if screen.x == 0 and screen.y == 0),
            screens[0],
        )
        placement = {
            "x": primary.x + (primary.width - 240) // 2,
            "y": primary.y + primary.height - 56 - 48,
        }
    window = webview.create_window(  # type: ignore[attr-defined]
        "Wispr Clone HUD",
        url=hud_url,
        js_api=None,
        frameless=True,
        on_top=True,
        focus=False,
        resizable=False,
        shadow=False,
        transparent=True,
        width=240,
        height=56,
        hidden=True,
        **placement,
    )
    _lock_navigation(window, hud_url)
    return cast(HudWindow, window)
