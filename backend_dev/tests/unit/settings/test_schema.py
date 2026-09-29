"""Pinned settings schema behavior for WO-feat-settings-models."""

import importlib
import json
import traceback

import pytest
from pydantic import ValidationError

from wispr_clone import config
from wispr_clone.contracts.common import ErrorCode, WisprError


class TestCatalog:
    """Small catalog with model roles; schema must use this protocol."""

    __test__ = False

    def __init__(self) -> None:
        self.models = {
            "openai/whisper-large-v3-turbo": "stt",
            "local-stt": "stt",
            "meta-llama-3.1-8b-instruct": "cleanup",
            "cloud-cleanup": "cleanup",
        }

    def role_of(self, model_id: str) -> str | None:
        return self.models.get(model_id)


def schema():
    return importlib.import_module("wispr_clone.settings.schema")


def valid_data() -> dict[str, object]:
    return {"schema_version": schema().SETTINGS_SCHEMA_VERSION}


def assert_error(data: dict[str, object], code: ErrorCode) -> WisprError:
    with pytest.raises(WisprError) as caught:
        schema().parse_settings(data, TestCatalog())
    assert caught.value.error_code == code
    assert caught.value.where == "settings.schema"
    return caught.value


@pytest.mark.unit
def test_T_SET_001_defaults_and_json_round_trip() -> None:
    module = schema()
    from wispr_clone.models.registry import default_registry

    expected = {
        "schema_version": 3,
        "recording_mode": "toggle",
        "dictation_shortcut": "ctrl+shift+space",
        "cancel_shortcut": "escape",
        "microphone_id": None,
        "stt_model_id": "openai/whisper-large-v3-turbo",
        "cleanup_model_id": "meta-llama-3.1-8b-instruct",
        "cleanup_enabled": True,
        "cleanup_instructions": "",
        "theme": "light",
        "sound_cues": False,
        "idle_jump_seconds": 1.0,
        "return_settle_seconds": 0.3,
        "destination_wait_limit_seconds": 600,
    }
    settings = module.default_settings()
    assert module.SETTINGS_SCHEMA_VERSION == 3
    assert settings.model_dump() == expected
    assert settings.idle_jump_seconds == config.IDLE_JUMP_SECONDS
    assert settings.return_settle_seconds == config.RETURN_SETTLE_SECONDS
    assert (
        settings.destination_wait_limit_seconds == config.DESTINATION_WAIT_LIMIT_SECONDS
    )
    data = module.settings_to_data(settings)
    assert json.loads(json.dumps(data)) == expected
    assert module.parse_settings(data, default_registry()) == settings


@pytest.mark.unit
@pytest.mark.invariant("model selection is validated by role")
@pytest.mark.parametrize(
    "field,cloud_id",
    [
        ("stt_model_id", "openai/whisper-large-v3-turbo"),
        ("cleanup_model_id", "cloud-cleanup"),
    ],
)
def test_T_SET_025_cloud_selection_validates_by_role(field: str, cloud_id: str) -> None:
    payload = {
        **valid_data(),
        "stt_model_id": "local-stt",
        field: cloud_id,
    }
    accepted = schema().parse_settings(payload, TestCatalog())
    assert getattr(accepted, field) == cloud_id


@pytest.mark.unit
@pytest.mark.parametrize(
    "field,model_id",
    [
        ("stt_model_id", "unknown"),
        ("cleanup_model_id", "unknown"),
        ("stt_model_id", "meta-llama-3.1-8b-instruct"),
        ("cleanup_model_id", "local-stt"),
    ],
)
def test_T_SET_003_unknown_or_wrong_role_rejected(field: str, model_id: str) -> None:
    assert_error({**valid_data(), field: model_id}, ErrorCode.VALIDATION)


@pytest.mark.unit
def test_T_SET_004_upgrade_version_zero_without_mutating_input() -> None:
    payload: dict[str, object] = {"schema_version": 0, "theme": "dark"}
    calls: list[dict[str, object]] = []

    def upgrade(old: dict[str, object]) -> dict[str, object]:
        calls.append(dict(old))
        return {**old, "schema_version": 1, "recording_mode": "hold"}

    parsed = schema().parse_settings(
        payload,
        TestCatalog(),
        upgrade_steps={
            0: upgrade,
            1: schema().UPGRADE_STEPS[1],
            2: schema().UPGRADE_STEPS[2],
        },
    )
    assert calls == [{"schema_version": 0, "theme": "dark"}]
    assert parsed.schema_version == 3
    assert parsed.recording_mode == "hold"
    assert parsed.theme == "dark"
    assert payload == {"schema_version": 0, "theme": "dark"}


@pytest.mark.unit
def test_T_SET_004_upgrade_step_must_return_a_dict() -> None:
    def upgrade(_old: dict[str, object]) -> list[tuple[str, object]]:
        return [("schema_version", 1)]

    with pytest.raises(WisprError) as caught:
        schema().parse_settings(
            {"schema_version": 0}, TestCatalog(), upgrade_steps={0: upgrade}
        )
    assert caught.value.error_code == ErrorCode.VALIDATION
    assert caught.value.where == "settings.schema"


@pytest.mark.unit
def test_T_SET_004_upgrade_cannot_mutate_nested_input_data() -> None:
    payload: dict[str, object] = {
        "schema_version": 0,
        "legacy": {"private": "original"},
    }

    def upgrade(old: dict[str, object]) -> dict[str, object]:
        legacy = old["legacy"]
        assert isinstance(legacy, dict)
        legacy["private"] = "changed"
        return {"schema_version": 1}

    parsed = schema().parse_settings(
        payload,
        TestCatalog(),
        upgrade_steps={
            0: upgrade,
            1: schema().UPGRADE_STEPS[1],
            2: schema().UPGRADE_STEPS[2],
        },
    )
    assert parsed.schema_version == 3
    assert payload == {"schema_version": 0, "legacy": {"private": "original"}}


@pytest.mark.unit
@pytest.mark.parametrize(
    "payload",
    [
        {"schema_version": 0},
        {"schema_version": 4},
        {},
        {"schema_version": "1"},
        {"schema_version": True},
    ],
)
def test_T_SET_004_invalid_schema_version_rejected(payload: dict[str, object]) -> None:
    assert_error(payload, ErrorCode.VALIDATION)


@pytest.mark.unit
@pytest.mark.parametrize(
    "field,value",
    [
        ("unexpected", "value"),
        ("cleanup_enabled", "true"),
        ("destination_wait_limit_seconds", "1"),
        ("idle_jump_seconds", 0.49),
        ("idle_jump_seconds", 10.01),
        ("return_settle_seconds", 0.09),
        ("return_settle_seconds", 2.01),
        ("destination_wait_limit_seconds", 59),
        ("destination_wait_limit_seconds", 3601),
        ("cleanup_instructions", "x" * 2001),
        ("dictation_shortcut", ""),
        ("cancel_shortcut", ""),
        ("dictation_shortcut", "x" * 65),
    ],
    ids=[
        "extra-field",
        "bool-string",
        "int-string",
        "idle-below",
        "idle-above",
        "settle-below",
        "settle-above",
        "wait-below",
        "wait-above",
        "instructions-too-long",
        "empty-dictation-shortcut",
        "empty-cancel-shortcut",
        "dictation-shortcut-too-long",
    ],
)
def test_T_SET_005_rejects_invalid_fields(field: str, value: object) -> None:
    assert_error({**valid_data(), field: value}, ErrorCode.VALIDATION)


@pytest.mark.unit
def test_T_SET_005_private_input_is_absent_from_error_text() -> None:
    sentinel = "PRIVATE_SENTINEL_7e4f"
    with pytest.raises(WisprError) as caught:
        schema().parse_settings(
            {**valid_data(), "cleanup_instructions": sentinel * 200}, TestCatalog()
        )
    error = caught.value
    assert error.error_code == ErrorCode.VALIDATION
    assert error.where == "settings.schema"
    assert error.why == "cleanup_instructions"
    assert sentinel not in str(error)
    assert sentinel not in error.why
    assert sentinel not in "".join(traceback.format_exception(error))


@pytest.mark.unit
def test_T_SET_005_settings_value_is_frozen() -> None:
    settings = schema().default_settings()
    with pytest.raises(ValidationError):
        settings.theme = "dark"
    assert settings.theme == "light"


@pytest.mark.unit
@pytest.mark.parametrize(
    "microphone_id", ["", "m" * 257], ids=["empty", "257-characters"]
)
def test_T_SET_005_microphone_id_length_is_bounded(microphone_id: str) -> None:
    assert_error({**valid_data(), "microphone_id": microphone_id}, ErrorCode.VALIDATION)


@pytest.mark.unit
@pytest.mark.parametrize(
    "microphone_id", [None, "m", "m" * 256], ids=["default", "one", "256-characters"]
)
def test_T_SET_005_microphone_id_length_boundaries_are_valid(
    microphone_id: str | None,
) -> None:
    parsed = schema().parse_settings(
        {**valid_data(), "microphone_id": microphone_id}, TestCatalog()
    )
    assert parsed.microphone_id == microphone_id


@pytest.mark.unit
def test_T_SET_020_discovered_models_validate_by_role() -> None:
    from wispr_clone.models.registry import default_registry

    parse = schema().parse_settings
    registry = default_registry()
    picked = parse(
        {
            **valid_data(),
            "stt_model_id": "deepgram/nova-3",
            "cleanup_model_id": "qwen/qwen3-8b",
        },
        registry,
    )
    assert (picked.stt_model_id, picked.cleanup_model_id) == (
        "deepgram/nova-3",
        "qwen/qwen3-8b",
    )
    with pytest.raises(WisprError) as caught:
        parse({**valid_data(), "stt_model_id": "no-vendor"}, registry)
    assert caught.value.error_code == ErrorCode.VALIDATION
    with pytest.raises(WisprError) as caught:
        parse(
            {**valid_data(), "cleanup_model_id": "openai/whisper-large-v3-turbo"},
            registry,
        )
    assert caught.value.error_code == ErrorCode.VALIDATION
