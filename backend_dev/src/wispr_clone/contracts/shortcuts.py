"""Pure shortcut syntax and validation shared by settings and hotkeys."""

from dataclasses import dataclass

from wispr_clone.contracts.common import ErrorCode, WisprError

MODIFIERS: tuple[str, ...] = ("ctrl", "alt", "shift", "win")
FUNCTION_KEYS: frozenset[str] = frozenset(f"f{number}" for number in range(1, 25))
NAMED_KEYS: frozenset[str] = frozenset(
    {
        "space",
        "escape",
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
    }
)
KEYS: frozenset[str] = frozenset(
    {
        *(chr(code) for code in range(ord("a"), ord("z") + 1)),
        *(str(number) for number in range(10)),
        *FUNCTION_KEYS,
        *NAMED_KEYS,
    }
)
_ALIASES = {
    "control": "ctrl",
    "option": "alt",
    "cmd": "win",
    "meta": "win",
    "super": "win",
    "esc": "escape",
    "return": "enter",
    "pgup": "page_up",
    "pgdn": "page_down",
}
_TYPING_KEYS = frozenset(
    {*"abcdefghijklmnopqrstuvwxyz0123456789", "space", "enter", "tab", "backspace"}
)


@dataclass(frozen=True, slots=True)
class KeyBinding:
    """One canonical key and the modifiers that must be held with it."""

    modifiers: frozenset[str]
    key: str


class _ShortcutError(WisprError):
    """Validation error whose text can never echo any part of user input."""

    def __str__(self) -> str:
        return "error"


def _invalid(why: str) -> WisprError:
    return _ShortcutError(ErrorCode.VALIDATION, "shortcuts", why)


def parse_binding(text: str) -> KeyBinding:
    """Parse a shortcut without including supplied text in validation errors."""
    if len(text) > 64:
        raise _invalid("too long")
    if not text.strip():
        raise _invalid("empty")

    modifiers: set[str] = set()
    keys: list[str] = []
    for raw_part in text.split("+"):
        part = raw_part.strip()
        if not part:
            raise _invalid("unknown key")
        lowered = part.lower()
        if lowered.startswith("key") and len(lowered) == 4 and lowered[3].isalpha():
            lowered = lowered[3]
        elif lowered.startswith("digit") and len(lowered) == 6 and lowered[5].isdigit():
            lowered = lowered[5]
        lowered = _ALIASES.get(lowered, lowered)
        if lowered in MODIFIERS:
            if lowered in modifiers:
                raise _invalid("duplicate modifier")
            modifiers.add(lowered)
        elif lowered in KEYS:
            keys.append(lowered)
        else:
            raise _invalid("unknown key")

    if len(keys) != 1:
        raise _invalid("one key")
    key = keys[0]
    if key in _TYPING_KEYS and not modifiers.intersection({"ctrl", "alt", "win"}):
        raise _invalid("needs modifier")
    return KeyBinding(frozenset(modifiers), key)


def format_binding(binding: KeyBinding) -> str:
    """Return a binding in canonical modifier order."""
    if binding.key not in KEYS or not binding.modifiers <= frozenset(MODIFIERS):
        raise _invalid("unknown key")
    ordered = [modifier for modifier in MODIFIERS if modifier in binding.modifiers]
    return "+".join((*ordered, binding.key))


def validate_bindings(dictation: KeyBinding, cancel: KeyBinding) -> None:
    """Reject a cancel shortcut that would be indistinguishable from dictation."""
    if dictation == cancel:
        raise _invalid("conflict")
