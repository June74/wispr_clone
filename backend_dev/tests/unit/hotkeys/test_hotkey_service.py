"""Listener-thread events produce deferred, privacy-preserving hotkey callbacks."""

import logging
from collections.abc import Callable
from threading import Thread
from typing import Any

import pytest


def _service(shortcuts: Any, hotkeys: Any, mode: str):  # type: ignore[no-untyped-def]
    delivered: list[str] = []
    posted: list[Callable[[], None]] = []
    service = hotkeys.HotkeyService(
        dictation=shortcuts.parse_binding("ctrl+shift+space"),
        cancel=shortcuts.parse_binding("escape"),
        mode=mode,
        on_start=lambda: delivered.append("start"),
        on_stop=lambda: delivered.append("stop"),
        on_cancel=lambda: delivered.append("cancel"),
        post=posted.append,
    )
    return service, delivered, posted


def _emit(service: Any, action: Any, *keys: str) -> None:
    for key in keys:
        service.handle(action, key)


def _drain(posted: list[Callable[[], None]]) -> None:
    while posted:
        posted.pop(0)()


@pytest.mark.unit
def test_T_KEY_002_hold_starts_and_stops_on_key_or_modifier_release() -> None:
    from wispr_clone.contracts import shortcuts
    from wispr_clone.hotkeys import hotkey_service as hotkeys

    service, delivered, posted = _service(shortcuts, hotkeys, "hold")
    _emit(service, hotkeys.KeyAction.DOWN, "ctrl", "shift", "space")
    assert len(posted) == 1
    _drain(posted)
    assert delivered == ["start"]
    service.handle(hotkeys.KeyAction.UP, "space")
    _drain(posted)
    assert delivered == ["start", "stop"]
    _emit(service, hotkeys.KeyAction.UP, "shift", "ctrl")
    _drain(posted)
    assert delivered == ["start", "stop"]

    _emit(service, hotkeys.KeyAction.DOWN, "ctrl", "shift", "space")
    _drain(posted)
    service.handle(hotkeys.KeyAction.UP, "ctrl")
    _drain(posted)
    service.handle(hotkeys.KeyAction.UP, "space")
    _drain(posted)
    assert delivered == ["start", "stop", "start", "stop"]


@pytest.mark.unit
def test_T_KEY_002_extra_modifier_prevents_match() -> None:
    from wispr_clone.contracts import shortcuts
    from wispr_clone.hotkeys import hotkey_service as hotkeys

    service, delivered, posted = _service(shortcuts, hotkeys, "hold")
    _emit(service, hotkeys.KeyAction.DOWN, "ctrl", "alt", "shift", "space")
    _emit(service, hotkeys.KeyAction.UP, "space", "shift", "alt", "ctrl")
    assert posted == []
    assert delivered == []


@pytest.mark.unit
def test_T_KEY_003_toggle_alternates_on_distinct_presses() -> None:
    from wispr_clone.contracts import shortcuts
    from wispr_clone.hotkeys import hotkey_service as hotkeys

    service, delivered, posted = _service(shortcuts, hotkeys, "toggle")
    _emit(service, hotkeys.KeyAction.DOWN, "ctrl", "shift")
    for expected in (["start"], ["start", "stop"], ["start", "stop", "start"]):
        service.handle(hotkeys.KeyAction.DOWN, "space")
        service.handle(hotkeys.KeyAction.UP, "space")
        _drain(posted)
        assert delivered == expected
    _emit(service, hotkeys.KeyAction.UP, "shift", "ctrl")
    assert posted == []


@pytest.mark.unit
def test_T_KEY_004_cancel_ends_hold_without_stop() -> None:
    from wispr_clone.contracts import shortcuts
    from wispr_clone.hotkeys import hotkey_service as hotkeys

    service, delivered, posted = _service(shortcuts, hotkeys, "hold")
    _emit(service, hotkeys.KeyAction.DOWN, "ctrl", "shift", "space")
    _drain(posted)
    service.handle(hotkeys.KeyAction.DOWN, "escape")
    _drain(posted)
    _emit(service, hotkeys.KeyAction.UP, "space", "shift", "ctrl", "escape")
    _drain(posted)
    assert delivered == ["start", "cancel"]


def _stored_values(service: Any) -> list[Any]:
    values = list(vars(service).values()) if hasattr(service, "__dict__") else []
    for cls in type(service).__mro__:
        for slot in getattr(cls, "__slots__", ()):
            if slot not in {"__dict__", "__weakref__"} and hasattr(service, slot):
                values.append(getattr(service, slot))
    return values


def _contains_forbidden_key(value: Any, forbidden: set[str]) -> bool:
    if isinstance(value, str):
        return value in forbidden
    if isinstance(value, dict):
        return any(
            _contains_forbidden_key(item, forbidden)
            for pair in value.items()
            for item in pair
        )
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_contains_forbidden_key(item, forbidden) for item in value)
    return False


@pytest.mark.unit
@pytest.mark.invariant("Non-binding keys are discarded without logging or retention")
def test_T_KEY_005_typed_keys_are_never_retained_forwarded_or_logged(
    caplog: Any,
) -> None:
    from wispr_clone.contracts import shortcuts
    from wispr_clone.hotkeys import hotkey_service as hotkeys

    service, delivered, posted = _service(shortcuts, hotkeys, "hold")
    caplog.set_level(logging.NOTSET)
    typed = "quick7zebras!?"
    for key in typed:
        canonical = key if key.isascii() and key.isalnum() else ""
        _emit(service, hotkeys.KeyAction.DOWN, canonical)
        _emit(service, hotkeys.KeyAction.UP, canonical)
        assert service.tracked_keys <= {
            "ctrl",
            "alt",
            "shift",
            "win",
            "space",
            "escape",
        }
    _emit(service, hotkeys.KeyAction.DOWN, "ctrl", "shift", "space")
    for key in typed:
        canonical = key if key.isascii() and key.isalnum() else ""
        _emit(service, hotkeys.KeyAction.DOWN, canonical)
        _emit(service, hotkeys.KeyAction.UP, canonical)
        assert service.tracked_keys <= {
            "ctrl",
            "alt",
            "shift",
            "win",
            "space",
            "escape",
        }
    _emit(service, hotkeys.KeyAction.UP, "space", "shift", "ctrl")
    _drain(posted)
    assert delivered == ["start", "stop"]
    assert service.tracked_keys <= {"ctrl", "alt", "shift", "win", "space", "escape"}
    forbidden = set(typed) - {"!", "?"}
    assert not any(
        _contains_forbidden_key(v, forbidden) for v in _stored_values(service)
    )
    assert caplog.records == []


@pytest.mark.unit
@pytest.mark.parametrize("mode", ["hold", "toggle"])
def test_T_KEY_006_auto_repeat_never_refires_until_key_up(mode: str) -> None:
    from wispr_clone.contracts import shortcuts
    from wispr_clone.hotkeys import hotkey_service as hotkeys

    service, delivered, posted = _service(shortcuts, hotkeys, mode)
    _emit(service, hotkeys.KeyAction.DOWN, "ctrl", "shift", "space", "space")
    _drain(posted)
    assert delivered == ["start"]
    service.handle(hotkeys.KeyAction.UP, "space")
    _drain(posted)
    assert delivered == (["start", "stop"] if mode == "hold" else ["start"])
    service.handle(hotkeys.KeyAction.DOWN, "space")
    _drain(posted)
    assert delivered == ["start", "stop"]


@pytest.mark.unit
def test_T_KEY_007_callbacks_only_via_post_and_reset_forgets_state() -> None:
    from wispr_clone.contracts import shortcuts
    from wispr_clone.hotkeys import hotkey_service as hotkeys

    service, delivered, posted = _service(shortcuts, hotkeys, "hold")
    _emit(service, hotkeys.KeyAction.DOWN, "ctrl", "shift", "space")
    assert delivered == []
    assert len(posted) == 1
    assert service.tracked_keys == frozenset({"ctrl", "shift", "space"})
    service.reset()
    assert service.tracked_keys == frozenset()
    service.handle(hotkeys.KeyAction.UP, "space")
    assert len(posted) == 1
    _drain(posted)
    assert delivered == ["start"]

    service, delivered, posted = _service(shortcuts, hotkeys, "hold")
    _emit(service, hotkeys.KeyAction.DOWN, "ctrl", "shift", "space")
    _drain(posted)
    assert delivered == ["start"]
    service.handle(hotkeys.KeyAction.UP, "space")
    assert delivered == ["start"]
    assert len(posted) == 1
    _drain(posted)
    assert delivered == ["start", "stop"]
    service.handle(hotkeys.KeyAction.DOWN, "escape")
    assert delivered == ["start", "stop"]
    assert len(posted) == 1
    _drain(posted)
    assert delivered == ["start", "stop", "cancel"]


@pytest.mark.unit
def test_T_KEY_007_post_receives_only_the_three_supplied_callbacks() -> None:
    from wispr_clone.contracts import shortcuts
    from wispr_clone.hotkeys.hotkey_service import HotkeyService, KeyAction

    delivered: list[str] = []
    posted: list[Callable[[], None]] = []

    def on_start() -> None:
        delivered.append("start")

    def on_stop() -> None:
        delivered.append("stop")

    def on_cancel() -> None:
        delivered.append("cancel")

    service = HotkeyService(
        dictation=shortcuts.parse_binding("ctrl+shift+space"),
        cancel=shortcuts.parse_binding("escape"),
        mode="hold",
        on_start=on_start,
        on_stop=on_stop,
        on_cancel=on_cancel,
        post=posted.append,
    )
    _emit(service, KeyAction.DOWN, "ctrl", "shift", "space")
    _emit(service, KeyAction.UP, "space")
    service.handle(KeyAction.DOWN, "escape")

    assert len(posted) == 3
    assert posted[0] is on_start
    assert posted[1] is on_stop
    assert posted[2] is on_cancel
    assert delivered == []


@pytest.mark.unit
def test_T_KEY_007_draining_on_another_thread_never_changes_listener_state() -> None:
    from wispr_clone.contracts import shortcuts
    from wispr_clone.hotkeys import hotkey_service as hotkeys

    service, delivered, posted = _service(shortcuts, hotkeys, "hold")
    _emit(service, hotkeys.KeyAction.DOWN, "ctrl", "shift", "space")
    before = (service.tracked_keys, service._holding, service._start_pending)
    assert len(posted) == 1

    worker = Thread(target=_drain, args=(posted,))
    worker.start()
    worker.join(timeout=1)

    assert not worker.is_alive()
    assert delivered == ["start"]
    assert (service.tracked_keys, service._holding, service._start_pending) == before


@pytest.mark.unit
def test_T_KEY_002_press_and_release_before_drain_posts_start_then_stop() -> None:
    from wispr_clone.contracts import shortcuts
    from wispr_clone.hotkeys import hotkey_service as hotkeys

    service, delivered, posted = _service(shortcuts, hotkeys, "hold")
    _emit(service, hotkeys.KeyAction.DOWN, "ctrl", "shift", "space")
    service.handle(hotkeys.KeyAction.UP, "space")

    assert len(posted) == 2
    assert delivered == []
    _drain(posted)
    assert delivered == ["start", "stop"]


@pytest.mark.unit
def test_T_KEY_002_reset_during_active_hold_posts_one_stop() -> None:
    from wispr_clone.contracts import shortcuts
    from wispr_clone.hotkeys import hotkey_service as hotkeys

    service, delivered, posted = _service(shortcuts, hotkeys, "hold")
    _emit(service, hotkeys.KeyAction.DOWN, "ctrl", "shift", "space")
    _drain(posted)
    service.reset()
    service.reset()

    assert service.tracked_keys == frozenset()
    assert len(posted) == 1
    _drain(posted)
    assert delivered == ["start", "stop"]


@pytest.mark.unit
def test_T_KEY_004_escape_cancels_with_dictation_modifiers_still_held() -> None:
    from wispr_clone.contracts import shortcuts
    from wispr_clone.hotkeys import hotkey_service as hotkeys

    service, delivered, posted = _service(shortcuts, hotkeys, "hold")
    _emit(service, hotkeys.KeyAction.DOWN, "ctrl", "shift", "space")
    _drain(posted)
    service.handle(hotkeys.KeyAction.DOWN, "escape")
    _drain(posted)
    _emit(service, hotkeys.KeyAction.UP, "space", "shift", "ctrl", "escape")
    _drain(posted)

    assert delivered == ["start", "cancel"]


@pytest.mark.unit
def test_T_KEY_004_modified_cancel_requires_exact_ctrl() -> None:
    from wispr_clone.contracts import shortcuts
    from wispr_clone.hotkeys import hotkey_service as hotkeys

    delivered: list[str] = []
    posted: list[Callable[[], None]] = []
    service = hotkeys.HotkeyService(
        dictation=shortcuts.parse_binding("f9"),
        cancel=shortcuts.parse_binding("ctrl+escape"),
        mode="toggle",
        on_start=lambda: delivered.append("start"),
        on_stop=lambda: delivered.append("stop"),
        on_cancel=lambda: delivered.append("cancel"),
        post=posted.append,
    )
    _emit(service, hotkeys.KeyAction.DOWN, "shift", "escape")
    _emit(service, hotkeys.KeyAction.UP, "escape", "shift")
    _emit(service, hotkeys.KeyAction.DOWN, "ctrl", "shift", "escape")
    _emit(service, hotkeys.KeyAction.UP, "escape", "shift")
    assert posted == []
    service.handle(hotkeys.KeyAction.DOWN, "escape")
    _drain(posted)

    assert delivered == ["cancel"]


@pytest.mark.unit
def test_T_KEY_002_releasing_and_repressing_modifier_allows_next_hold() -> None:
    from wispr_clone.contracts import shortcuts
    from wispr_clone.hotkeys import hotkey_service as hotkeys

    service, delivered, posted = _service(shortcuts, hotkeys, "hold")
    _emit(service, hotkeys.KeyAction.DOWN, "ctrl", "shift", "space")
    _drain(posted)
    _emit(service, hotkeys.KeyAction.UP, "ctrl", "space")
    _drain(posted)
    _emit(service, hotkeys.KeyAction.DOWN, "ctrl", "space")
    _drain(posted)

    assert delivered == ["start", "stop", "start"]


@pytest.mark.unit
def test_T_KEY_002_repressing_key_with_modifiers_held_starts_next_hold() -> None:
    from wispr_clone.contracts import shortcuts
    from wispr_clone.hotkeys import hotkey_service as hotkeys

    service, delivered, posted = _service(shortcuts, hotkeys, "hold")
    _emit(service, hotkeys.KeyAction.DOWN, "ctrl", "shift", "space")
    _drain(posted)
    service.handle(hotkeys.KeyAction.UP, "space")
    _drain(posted)
    service.handle(hotkeys.KeyAction.DOWN, "space")
    _drain(posted)

    assert delivered == ["start", "stop", "start"]


@pytest.mark.unit
def test_T_KEY_004_shared_key_selects_binding_by_exact_modifiers() -> None:
    from wispr_clone.contracts import shortcuts
    from wispr_clone.hotkeys import hotkey_service as hotkeys

    delivered: list[str] = []
    posted: list[Callable[[], None]] = []
    service = hotkeys.HotkeyService(
        dictation=shortcuts.parse_binding("ctrl+space"),
        cancel=shortcuts.parse_binding("alt+space"),
        mode="toggle",
        on_start=lambda: delivered.append("start"),
        on_stop=lambda: delivered.append("stop"),
        on_cancel=lambda: delivered.append("cancel"),
        post=posted.append,
    )
    _emit(service, hotkeys.KeyAction.DOWN, "ctrl", "space")
    _emit(service, hotkeys.KeyAction.UP, "space", "ctrl")
    _emit(service, hotkeys.KeyAction.DOWN, "alt", "space")
    _drain(posted)

    assert delivered == ["start", "cancel"]


@pytest.mark.unit
def test_T_KEY_003_modifier_release_does_not_stop_toggle() -> None:
    from wispr_clone.contracts import shortcuts
    from wispr_clone.hotkeys import hotkey_service as hotkeys

    service, delivered, posted = _service(shortcuts, hotkeys, "toggle")
    _emit(service, hotkeys.KeyAction.DOWN, "ctrl", "shift", "space")
    _emit(service, hotkeys.KeyAction.UP, "ctrl", "shift", "space")
    _drain(posted)

    assert delivered == ["start"]
