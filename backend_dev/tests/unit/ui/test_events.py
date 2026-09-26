"""T-UI-002/003/006: events are data with per-window routing and throttling."""

from __future__ import annotations

import json

import pytest
from fakes.webview import FakeWebview, Window

from wispr_clone.contracts.events import AudioLevelEvent, RunStateEvent
from wispr_clone.ui.events import WebviewEventSink


def _windows() -> tuple[Window, Window]:
    webview = FakeWebview()
    settings = webview.create_window("settings")
    hud = webview.create_window("hud")
    return settings, hud


def _scripts(window: Window) -> list[str]:
    return [str(args[0]) for name, args in window.calls if name == "run_js"]


@pytest.mark.unit
def test_T_UI_002_event_is_one_json_string_literal_without_eval() -> None:
    settings, hud = _windows()
    sink = WebviewEventSink(settings, hud, clock=lambda: 0.0)
    event: RunStateEvent = {
        "name": "run:state",
        "run_id": 'quote" </script> \\ line\u2028separator',
        "version": 1,
        "status": "recording",
    }
    sink.publish(event)
    serialized = json.dumps(event, ensure_ascii=True)
    expected = "window.wisprEvent(" + json.dumps(serialized) + ")"
    for window in (settings, hud):
        assert _scripts(window) == [expected]
        literal = _scripts(window)[0][len("window.wisprEvent(") : -1]
        assert json.loads(json.loads(literal)) == event
        assert all(name != "evaluate_js" for name, _ in window.calls)


@pytest.mark.unit
def test_T_UI_003_hud_receives_only_state_and_level() -> None:
    settings, hud = _windows()
    sink = WebviewEventSink(settings, hud, clock=lambda: 0.0)
    sink.publish({"name": "run:state", "run_id": "r", "version": 1, "status": "idle"})
    level: AudioLevelEvent = {"name": "audio:level", "run_id": "r", "bands": [0.2]}
    sink.publish(level)
    sink.publish({"name": "history:changed", "run_ids": ["r"], "reason": "added"})
    assert len(_scripts(settings)) == 3
    assert len(_scripts(hud)) == 2


@pytest.mark.unit
def test_T_UI_006_audio_throttle_uses_injected_clock_per_window() -> None:
    settings, hud = _windows()
    now = [100.0]
    sink = WebviewEventSink(settings, hud, clock=lambda: now[0])
    level: AudioLevelEvent = {"name": "audio:level", "run_id": "r", "bands": [0.2]}
    for _ in range(40):
        sink.publish(level)
    assert len(_scripts(settings)) <= 1
    assert len(_scripts(hud)) <= 1
    now[0] += 1 / 30
    sink.publish(level)
    assert len(_scripts(settings)) == 2
    assert len(_scripts(hud)) == 2

    settings.raise_on_run_js = True
    now[0] += 1 / 30
    sink.publish(level)
    assert len(_scripts(hud)) == 3
    assert sink.delivery_errors == 1
