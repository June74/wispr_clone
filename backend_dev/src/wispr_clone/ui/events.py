"""Serialize application events and deliver them as page data."""

from __future__ import annotations

import json
import time
from collections.abc import Callable

from wispr_clone.contracts.events import EventPayload, EventSink


class WebviewEventSink(EventSink):
    """Publish JSON events to settings and HUD windows without evaluating code."""

    def __init__(
        self,
        settings_window: object,
        hud_window: object | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._windows = (settings_window, hud_window)
        self._clock = clock
        self._last_audio: dict[int, float] = {}
        self.delivery_errors = 0

    def publish(self, event: EventPayload) -> None:
        serialized = json.dumps(event, ensure_ascii=True)
        script = "window.wisprEvent(" + json.dumps(serialized) + ")"
        name = event["name"]
        now = self._clock() if name == "audio:level" else 0.0
        for index, window in enumerate(self._windows):
            if window is None:
                continue
            if index == 1 and name not in {"run:state", "audio:level"}:
                continue
            if name == "audio:level":
                key = id(window)
                previous = self._last_audio.get(key)
                if previous is not None and now - previous + 1e-12 < 1 / 30:
                    continue
                self._last_audio[key] = now
            try:
                window.run_js(script)  # type: ignore[attr-defined]
            except Exception:
                self.delivery_errors += 1
