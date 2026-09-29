"""T-UI-014: native HUD availability and event delivery contracts."""

from __future__ import annotations

import sys

import pytest

from wispr_clone.ui.events import WebviewEventSink
from wispr_clone.ui.native_hud import NativeHud


class _Settings:
    def __init__(self) -> None:
        self.scripts: list[str] = []

    def run_js(self, script: str) -> None:
        self.scripts.append(script)


class _NativeReceiver:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def publish_event(self, event: dict[str, object]) -> None:
        self.events.append(event)

    def run_js(self, _script: str) -> None:
        raise AssertionError("native HUD must receive event data, not JavaScript")


@pytest.mark.unit
def test_T_UI_014_non_windows_construction_is_clean() -> None:
    if sys.platform == "win32":
        pytest.skip("non-Windows availability contract")
    hud = NativeHud()
    try:
        assert getattr(hud, "available", False) is False
        hud.show()
        hud.hide()
        hud.publish_event(
            {"name": "run:state", "run_id": "r", "version": 1, "status": "recording"}
        )
    finally:
        hud.destroy()


@pytest.mark.unit
def test_T_UI_014_event_sink_prefers_native_data_and_throttles() -> None:
    settings = _Settings()
    hud = _NativeReceiver()
    now = [10.0]
    sink = WebviewEventSink(settings, hud, clock=lambda: now[0])
    state = {"name": "run:state", "run_id": "r", "version": 1, "status": "recording"}
    audio = {"name": "audio:level", "run_id": "r", "bands": [0.3] * 12}
    sink.publish(state)
    for _ in range(10):
        sink.publish(audio)
    sink.publish({"name": "history:changed", "run_ids": ["r"], "reason": "added"})
    assert hud.events == [state, audio]
    assert len(settings.scripts) == 3
    now[0] += 1 / 30
    sink.publish(audio)
    assert hud.events == [state, audio, audio]
    assert len(settings.scripts) == 4
