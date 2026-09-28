"""System-tray icon: the app keeps running while its window is hidden."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

TOOLTIP = "Wispr Clone"
# Waveform bar heights (fraction of the icon), matching the brand mark.
_BARS = (0.28, 0.52, 0.76, 0.52, 0.28)


def icon_image(size: int = 64) -> Any:
    """Draw the brand mark: white waveform bars on a purple rounded square."""
    from PIL import Image, ImageDraw  # type: ignore[import-not-found]

    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (0, 0, size - 1, size - 1), radius=size // 4, fill=(116, 86, 137, 255)
    )
    bar, gap = size // 10, size // 16
    left = (size - (len(_BARS) * bar + (len(_BARS) - 1) * gap)) // 2
    for index, height in enumerate(_BARS):
        x = left + index * (bar + gap)
        half = int(size * height) // 2
        draw.rounded_rectangle(
            (x, size // 2 - half, x + bar - 1, size // 2 + half),
            radius=bar // 2,
            fill=(255, 255, 255, 255),
        )
    return image


class Tray:
    """Own the tray icon on its own thread; menu actions call back from it."""

    def __init__(
        self,
        *,
        on_open: Callable[[], None],
        on_quit: Callable[[], None],
        pystray: Any = None,
    ) -> None:
        self._on_open = on_open
        self._on_quit = on_quit
        self._pystray = pystray
        self._icon: Any = None
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        try:
            pystray = self._pystray
            if pystray is None:
                import pystray  # type: ignore[import-not-found, no-redef]
            menu = pystray.Menu(
                pystray.MenuItem(
                    "Open Wispr Clone", lambda: self._on_open(), default=True
                ),
                pystray.MenuItem("Quit", lambda: self._on_quit()),
            )
            self._icon = pystray.Icon("wispr_clone", icon_image(), TOOLTIP, menu)
            self._thread = threading.Thread(
                target=self._icon.run, name="wispr-tray", daemon=True
            )
            self._thread.start()
            return True
        except Exception:
            logger.warning("TRAY_START_FAILED")
            self._icon = None
            return False

    @property
    def running(self) -> bool:
        return self._icon is not None

    def stop(self) -> None:
        icon, self._icon = self._icon, None
        if icon is None:
            return
        try:
            icon.stop()
        except Exception:
            logger.warning("TRAY_STOP_FAILED")
