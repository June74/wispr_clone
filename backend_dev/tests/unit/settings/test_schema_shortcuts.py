"""T-SET-002: settings apply the shared shortcut contract."""

import pytest

from wispr_clone.contracts.common import ErrorCode, WisprError
from wispr_clone.models.registry import default_registry
from wispr_clone.settings.schema import parse_settings, settings_to_data


@pytest.mark.unit
@pytest.mark.parametrize(
    "dictation,cancel,expected_dictation,expected_cancel",
    [
        ("ctrl+shift+space", "escape", "ctrl+shift+space", "escape"),
        ("Ctrl + Shift + Space", "Esc", "ctrl+shift+space", "escape"),
    ],
)
def test_T_SET_002_valid_shortcuts_are_canonical_and_round_trip(
    dictation: str,
    cancel: str,
    expected_dictation: str,
    expected_cancel: str,
) -> None:
    settings = parse_settings(
        {
            "schema_version": 1,
            "dictation_shortcut": dictation,
            "cancel_shortcut": cancel,
        },
        default_registry(),
    )
    assert settings.dictation_shortcut == expected_dictation
    assert settings.cancel_shortcut == expected_cancel

    data = settings_to_data(settings)
    assert data["dictation_shortcut"] == expected_dictation
    assert data["cancel_shortcut"] == expected_cancel
    assert parse_settings(data, default_registry()) == settings


@pytest.mark.unit
@pytest.mark.parametrize("field", ["dictation_shortcut", "cancel_shortcut"])
@pytest.mark.parametrize(
    "shortcut",
    ["not_a_key", "ctrl+a+b", "d", "shift+a"],
    ids=["unknown-key", "two-keys", "bare-letter", "shift-only-letter"],
)
def test_T_SET_002_invalid_shortcut_names_only_its_field(
    field: str, shortcut: str
) -> None:
    with pytest.raises(WisprError) as caught:
        parse_settings({"schema_version": 1, field: shortcut}, default_registry())
    error = caught.value
    assert error.error_code == ErrorCode.VALIDATION
    assert error.where == "settings.schema"
    assert error.why == field


@pytest.mark.unit
@pytest.mark.parametrize("field", ["dictation_shortcut", "cancel_shortcut"])
def test_T_SET_002_bad_shortcut_does_not_expose_typed_text(field: str) -> None:
    sentinel = "PRIVATE_SENTINEL_7e4f"
    with pytest.raises(WisprError) as caught:
        parse_settings({"schema_version": 1, field: sentinel}, default_registry())
    error = caught.value
    assert error.error_code == ErrorCode.VALIDATION
    assert error.where == "settings.schema"
    assert error.why == field
    assert sentinel not in str(error)
    assert sentinel not in error.why


@pytest.mark.unit
def test_T_SET_002_equivalent_dictation_and_cancel_shortcuts_conflict() -> None:
    with pytest.raises(WisprError) as caught:
        parse_settings(
            {
                "schema_version": 1,
                "dictation_shortcut": "ctrl+shift+space",
                "cancel_shortcut": "Ctrl + Shift + Space",
            },
            default_registry(),
        )
    error = caught.value
    assert error.error_code == ErrorCode.VALIDATION
    assert error.where == "settings.schema"
    assert error.why == "dictation_shortcut, cancel_shortcut"
