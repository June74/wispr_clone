"""Match configured shortcuts and post deferred recording actions."""

from collections.abc import Callable
from enum import StrEnum
from typing import Literal

from wispr_clone.contracts.shortcuts import MODIFIERS, KeyBinding


class KeyAction(StrEnum):
    """A key transition reported by the operating-system listener."""

    DOWN = "down"
    UP = "up"


class HotkeyService:
    """Listener-thread state machine retaining configured keys only."""

    def __init__(
        self,
        *,
        dictation: KeyBinding,
        cancel: KeyBinding,
        mode: Literal["hold", "toggle"],
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
        on_cancel: Callable[[], None],
        post: Callable[[Callable[[], None]], None],
    ) -> None:
        self._dictation = dictation
        self._cancel = cancel
        self._mode = mode
        self._on_start = on_start
        self._on_stop = on_stop
        self._on_cancel = on_cancel
        self._post = post
        self._pressed: set[str] = set()
        self._holding = False
        self._start_pending = False
        self._toggled = False
        self._dictation_armed = True
        self._repeat_seen = False

    @property
    def tracked_keys(self) -> frozenset[str]:
        """Keys currently remembered as down (only modifiers/configured keys)."""
        return frozenset(self._pressed)

    def handle(self, action: KeyAction, key: str) -> None:
        """Consume one transition without retaining unrelated input."""
        allowed = frozenset(MODIFIERS) | {self._dictation.key, self._cancel.key}
        if key not in allowed:
            return
        if action is KeyAction.DOWN:
            if key in self._pressed:
                if key == self._dictation.key:
                    self._repeat_seen = True
                return
            self._pressed.add(key)
            if (
                key == self._dictation.key
                and self._dictation_armed
                and self._matches(self._dictation)
            ):
                if self._mode != "hold" or not self._repeat_seen:
                    self._fire_dictation()
                self._dictation_armed = False
                self._repeat_seen = False
            if key == self._cancel.key and (
                not self._cancel.modifiers or self._matches(self._cancel)
            ):
                self._post(self._on_cancel)
                if self._mode == "hold":
                    self._holding = False
        elif action is KeyAction.UP:
            if key not in self._pressed:
                return
            self._pressed.remove(key)
            if key == self._dictation.key:
                self._dictation_armed = True
                self._start_pending = False
            if (
                self._mode == "hold"
                and self._holding
                and (key == self._dictation.key or key in self._dictation.modifiers)
            ):
                self._holding = False
                self._start_pending = False
                self._post(self._on_stop)

    def reset(self) -> None:
        """Forget key state and stop an active hold after a lost key-up."""
        self._pressed.clear()
        self._dictation_armed = True
        if self._mode == "hold" and self._holding and not self._start_pending:
            self._holding = False
            self._post(self._on_stop)
        self._holding = False
        self._start_pending = False

    def _matches(self, binding: KeyBinding) -> bool:
        held_modifiers = self._pressed.intersection(MODIFIERS)
        return held_modifiers == binding.modifiers

    def _fire_dictation(self) -> None:
        if self._mode == "hold":
            if not self._holding:
                self._holding = True
                self._start_pending = True
                self._post(self._on_start)
        elif self._toggled:
            self._toggled = False
            self._post(self._on_stop)
        else:
            self._toggled = True
            self._post(self._on_start)
