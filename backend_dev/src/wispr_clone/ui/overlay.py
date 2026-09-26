"""Non-activating, bridge-free HUD window."""

from __future__ import annotations

from typing import Protocol, cast


class HudWindow(Protocol):
    def show(self) -> None: ...

    def hide(self) -> None: ...


def open_hud(webview: object, *, hud_url: str) -> HudWindow:
    """Create a hidden HUD with no JS API and place it near screen bottom."""
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
    )
    screens = getattr(webview, "screens", ())
    if screens:
        primary = next((screen for screen in screens if screen.is_primary), screens[0])
        x = int(primary.x + (primary.width - 240) / 2)
        y = int(primary.y + primary.height - 56 - 48)
        window.move(x, y)
    return cast(HudWindow, window)
