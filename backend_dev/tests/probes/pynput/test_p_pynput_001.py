"""Windows-only direct pynput import and listener lifecycle probe."""

import importlib.metadata
import sys

import pytest


@pytest.mark.probe("pynput")
@pytest.mark.windows
def test_P_PYNPUT_001_listener_symbols_and_lifecycle() -> None:
    if sys.platform != "win32":
        pytest.skip("pynput listener probe requires Windows")
    keyboard = pytest.importorskip("pynput.keyboard", reason="pynput is not importable")
    assert importlib.metadata.version("pynput") == "1.8.2"
    for name in ("ctrl_l", "ctrl_r", "alt_gr", "cmd", "space", "esc", "f24"):
        assert hasattr(keyboard.Key, name), name
    assert keyboard.KeyCode.from_char("a").char == "a"
    listener = keyboard.Listener(
        on_press=lambda _key: None, on_release=lambda _key: None
    )
    try:
        listener.start()
    finally:
        listener.stop()
