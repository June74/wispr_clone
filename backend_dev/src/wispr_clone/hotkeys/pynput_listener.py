"""Lazy pynput adapter that forwards only canonical binding-relevant keys."""

from __future__ import annotations

from importlib import import_module
from types import ModuleType
from typing import Any

from wispr_clone.contracts.shortcuts import FUNCTION_KEYS, KEYS
from wispr_clone.hotkeys.hotkey_service import HotkeyService, KeyAction

_KEY_NAMES: tuple[tuple[str, str], ...] = (
    ("ctrl", "ctrl"),
    ("ctrl_l", "ctrl"),
    ("ctrl_r", "ctrl"),
    ("alt", "alt"),
    ("alt_l", "alt"),
    ("alt_r", "alt"),
    ("alt_gr", "alt"),
    ("shift", "shift"),
    ("shift_l", "shift"),
    ("shift_r", "shift"),
    ("cmd", "win"),
    ("cmd_l", "win"),
    ("cmd_r", "win"),
    ("space", "space"),
    ("esc", "escape"),
    ("tab", "tab"),
    ("enter", "enter"),
    ("backspace", "backspace"),
    ("delete", "delete"),
    ("insert", "insert"),
    ("home", "home"),
    ("end", "end"),
    ("page_up", "page_up"),
    ("page_down", "page_down"),
    ("up", "up"),
    ("down", "down"),
    ("left", "left"),
    ("right", "right"),
    ("pause", "pause"),
    ("scroll_lock", "scroll_lock"),
)


def key_name(key: object, module: ModuleType) -> str:
    """Map supported pynput values to canonical names; discard all others."""
    key_type = getattr(module, "Key", None)
    if key_type is not None:
        for attr, canonical in _KEY_NAMES:
            if getattr(key_type, attr, object()) == key:
                return canonical
        for name in FUNCTION_KEYS:
            if getattr(key_type, name, object()) == key:
                return name

    key_code_type = getattr(module, "KeyCode", None)
    if key_code_type is not None and isinstance(key, key_code_type):
        char = getattr(key, "char", None)
        if (
            isinstance(char, str)
            and len(char) == 1
            and char.isascii()
            and char.isalnum()
        ):
            canonical = char.lower()
            if canonical in KEYS:
                return canonical
    return ""


class PynputListener:
    """Thin listener owner; importing this module never imports pynput."""

    def __init__(
        self, service: HotkeyService, *, module: ModuleType | None = None
    ) -> None:
        self._service = service
        self._module = module
        self._listener: Any | None = None
        self._modifier_keys: dict[str, set[str]] = {}

    def start(self) -> None:
        """Import pynput on demand and start its global down/up listener."""
        if self._listener is not None:
            return
        module = self._module
        if module is None:
            import pynput  # type: ignore[import-untyped]  # imported only on start

            _ = pynput
            module = import_module("pynput.keyboard")
            self._module = module

        self._modifier_keys.clear()

        def modifier_key(key: object) -> tuple[str, str] | None:
            key_type = getattr(module, "Key", None)
            if key_type is None:
                return None
            for attr, canonical in _KEY_NAMES:
                if (
                    canonical in {"ctrl", "alt", "shift", "win"}
                    and getattr(key_type, attr, object()) == key
                ):
                    return canonical, attr
            return None

        def on_press(key: object) -> None:
            physical = modifier_key(key)
            if physical is not None:
                modifier, physical_name = physical
                down_keys = self._modifier_keys.setdefault(modifier, set())
                if physical_name not in down_keys:
                    was_empty = not down_keys
                    down_keys.add(physical_name)
                    if was_empty:
                        self._service.handle(KeyAction.DOWN, modifier)
            else:
                self._service.handle(KeyAction.DOWN, key_name(key, module))

        def on_release(key: object) -> None:
            physical = modifier_key(key)
            if physical is not None:
                modifier, physical_name = physical
                down_keys = self._modifier_keys.get(modifier)
                if down_keys is not None and physical_name in down_keys:
                    down_keys.remove(physical_name)
                    if not down_keys:
                        self._modifier_keys.pop(modifier, None)
                        self._service.handle(KeyAction.UP, modifier)
            else:
                self._service.handle(KeyAction.UP, key_name(key, module))

        listener_type = getattr(module, "Listener")
        listener = listener_type(on_press=on_press, on_release=on_release)
        self._listener = listener
        try:
            listener.start()
        except Exception:
            self._listener = None
            self._modifier_keys.clear()
            self._service.reset()
            raise

    def stop(self) -> None:
        """Stop once and clear any key state that missed its release event."""
        listener = self._listener
        if listener is None:
            return
        self._listener = None
        try:
            listener.stop()
        finally:
            self._modifier_keys.clear()
            reset = getattr(self._service, "reset", None)
            if callable(reset):
                reset()
