"""Pinned shortcut syntax and safe validation errors for WO-feat-hotkeys."""

import pytest


@pytest.mark.unit
def test_T_KEY_001_defaults_aliases_and_canonical_format() -> None:
    from wispr_clone.contracts import shortcuts

    cases = {
        "Ctrl+Shift+Space": "ctrl+shift+space",
        "shift + CTRL + Space": "ctrl+shift+space",
        "ctrl + alt + KeyD": "ctrl+alt+d",
        "F9": "f9",
        "esc": "escape",
        "CONTROL+Option+Digit5": "ctrl+alt+5",
        "cmd+pgup": "win+page_up",
        "meta+pgdn": "win+page_down",
        "super+return": "win+enter",
    }
    for text, expected in cases.items():
        binding = shortcuts.parse_binding(text)
        assert shortcuts.format_binding(binding) == expected
        assert shortcuts.parse_binding(expected) == binding

    assert shortcuts.parse_binding("ctrl+shift+space")
    assert shortcuts.parse_binding("escape")
    assert shortcuts.MODIFIERS == ("ctrl", "alt", "shift", "win")
    assert {f"f{number}" for number in range(1, 25)} <= shortcuts.FUNCTION_KEYS
    assert {"a", "z", "0", "9", "space", "escape"} <= shortcuts.KEYS


@pytest.mark.unit
@pytest.mark.parametrize(
    "text,why",
    [
        ("", "empty"),
        (" " * 65, "too long"),
        ("ctrl+SYNTHETIC_PRIVATE_KEY", "unknown key"),
        ("ctrl+shift", "one key"),
        ("ctrl+a+b", "one key"),
        ("ctrl+control+space", "duplicate modifier"),
        ("a", "needs modifier"),
        ("7", "needs modifier"),
        ("space", "needs modifier"),
        ("enter", "needs modifier"),
        ("tab", "needs modifier"),
        ("backspace", "needs modifier"),
        ("shift+a", "needs modifier"),
    ],
)
def test_T_KEY_001_rejects_invalid_binding_without_echoing_input(
    text: str, why: str
) -> None:
    from wispr_clone.contracts import shortcuts
    from wispr_clone.contracts.common import ErrorCode, WisprError

    with pytest.raises(WisprError) as caught:
        shortcuts.parse_binding(text)
    error = caught.value
    assert (error.error_code, error.where, error.why) == (
        ErrorCode.VALIDATION,
        "shortcuts",
        why,
    )
    if text.strip():
        assert text not in str(error)
        assert text not in error.why


@pytest.mark.unit
def test_T_KEY_001_rejects_conflicting_bindings() -> None:
    from wispr_clone.contracts import shortcuts
    from wispr_clone.contracts.common import ErrorCode, WisprError

    binding = shortcuts.parse_binding("ctrl+shift+space")
    with pytest.raises(WisprError) as caught:
        shortcuts.validate_bindings(binding, binding)
    assert (
        caught.value.error_code,
        caught.value.where,
        caught.value.why,
    ) == (ErrorCode.VALIDATION, "shortcuts", "conflict")
    shortcuts.validate_bindings(binding, shortcuts.parse_binding("escape"))


@pytest.mark.unit
@pytest.mark.parametrize("text", ["сtrl+space", "ctrl＋space", "ctrl++space"])
def test_T_KEY_001_rejects_lookalikes_and_empty_chord_part(text: str) -> None:
    from wispr_clone.contracts import shortcuts
    from wispr_clone.contracts.common import ErrorCode, WisprError

    with pytest.raises(WisprError) as caught:
        shortcuts.parse_binding(text)
    assert caught.value.error_code == ErrorCode.VALIDATION
    assert caught.value.where == "shortcuts"
    assert caught.value.why == "unknown key"
