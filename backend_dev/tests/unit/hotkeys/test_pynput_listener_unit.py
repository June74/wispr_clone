"""Pure pynput key conversion and listener lifecycle with an injected module."""

import importlib
import sys
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest


def _fake_keyboard() -> Any:
    keyboard = ModuleType("fake_pynput_keyboard")
    names = (
        "ctrl",
        "ctrl_l",
        "ctrl_r",
        "alt",
        "alt_l",
        "alt_r",
        "alt_gr",
        "shift",
        "shift_l",
        "shift_r",
        "cmd",
        "cmd_l",
        "cmd_r",
        "space",
        "esc",
        "tab",
        "enter",
        "backspace",
        "delete",
        "insert",
        "home",
        "end",
        "page_up",
        "page_down",
        "up",
        "down",
        "left",
        "right",
        "pause",
        "scroll_lock",
        "media_play_pause",
    )
    keys = {name: object() for name in names}
    keys.update({f"f{i}": object() for i in range(1, 25)})

    class FakeKeyCode:
        def __init__(self, char: str | None) -> None:
            self.char = char

    class FakeListener:
        instances: list[Any] = []

        def __init__(self, *, on_press: Any, on_release: Any) -> None:
            self.on_press = on_press
            self.on_release = on_release
            self.started = 0
            self.stopped = 0
            self.instances.append(self)

        def start(self) -> None:
            self.started += 1

        def stop(self) -> None:
            self.stopped += 1

    keyboard.Key = SimpleNamespace(**keys)
    keyboard.KeyCode = FakeKeyCode
    keyboard.Listener = FakeListener
    return keyboard


@pytest.mark.unit
def test_T_KEY_008_key_name_maps_supported_keys_and_discards_all_other_input() -> None:
    from wispr_clone.hotkeys.pynput_listener import key_name

    keyboard = _fake_keyboard()
    for name in (
        "ctrl",
        "ctrl_l",
        "ctrl_r",
        "alt",
        "alt_l",
        "alt_r",
        "alt_gr",
        "shift",
        "shift_l",
        "shift_r",
        "cmd",
        "cmd_l",
        "cmd_r",
    ):
        if name.startswith("cmd"):
            expected = "win"
        elif name == "alt_gr":
            expected = "alt"
        else:
            expected = name.split("_")[0]
        assert key_name(getattr(keyboard.Key, name), keyboard) == expected
    for name, expected in (
        ("space", "space"),
        ("esc", "escape"),
        ("f1", "f1"),
        ("f24", "f24"),
        ("page_up", "page_up"),
        ("tab", "tab"),
    ):
        assert key_name(getattr(keyboard.Key, name), keyboard) == expected
    for char, expected in (("D", "d"), ("5", "5"), ("z", "z")):
        assert key_name(keyboard.KeyCode(char), keyboard) == expected
    for key in (
        keyboard.Key.media_play_pause,
        keyboard.KeyCode("!"),
        keyboard.KeyCode("é"),
        keyboard.KeyCode("ab"),
        keyboard.KeyCode(None),
        object(),
    ):
        assert key_name(key, keyboard) == ""


@pytest.mark.unit
def test_T_KEY_008_listener_import_is_lazy_and_stop_is_idempotent() -> None:
    module_name = "wispr_clone.hotkeys.pynput_listener"
    sys.modules.pop(module_name, None)
    with patch.dict(sys.modules, {"pynput": None, "pynput.keyboard": None}):
        listener_module = importlib.import_module(module_name)

    keyboard = _fake_keyboard()
    listener = listener_module.PynputListener(object(), module=keyboard)
    listener.start()
    listener.stop()
    listener.stop()
    instance = keyboard.Listener.instances[-1]
    assert instance.started == 1
    assert instance.stopped == 1
