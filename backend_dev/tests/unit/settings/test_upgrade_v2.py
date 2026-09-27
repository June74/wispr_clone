"""Schema v2 adopts cloud STT without losing unrelated preferences."""

import pytest

from wispr_clone.contracts.common import ErrorCode, WisprError
from wispr_clone.models.registry import default_registry
from wispr_clone.settings.schema import (
    SETTINGS_SCHEMA_VERSION,
    default_settings,
    parse_settings,
)

WHISPER = "openai/whisper-large-v3-turbo"


@pytest.mark.unit
def test_T_SET_021_defaults_and_registry() -> None:
    settings = default_settings()
    assert SETTINGS_SCHEMA_VERSION == 2
    assert (settings.stt_model_id, settings.local_only) == (WHISPER, False)
    stt, cleanup = default_registry().list_models()
    assert (
        stt.model_id,
        stt.role,
        stt.display_name,
        stt.local,
        stt.runtime,
        stt.endpoint,
    ) == (
        WHISPER,
        "stt",
        "Whisper Large v3 Turbo (DeepInfra)",
        False,
        "openrouter",
        "https://openrouter.ai/api/v1",
    )
    assert cleanup.model_id == "meta-llama-3.1-8b-instruct"
    assert default_registry().get("voxtral-mini-4b-realtime-2602") is None


@pytest.mark.unit
def test_T_SET_021_v1_upgrade_preserves_other_preferences() -> None:
    old: dict[str, object] = {
        "schema_version": 1,
        "stt_model_id": "voxtral-mini-4b-realtime-2602",
        "local_only": True,
        "recording_mode": "hold",
        "theme": "dark",
        "cleanup_instructions": "Keep medical terms",
    }
    upgraded = parse_settings(old, default_registry())
    assert (upgraded.schema_version, upgraded.stt_model_id, upgraded.local_only) == (
        2,
        WHISPER,
        False,
    )
    assert upgraded.recording_mode == "hold"
    assert upgraded.theme == "dark"
    assert upgraded.cleanup_instructions == "Keep medical terms"
    assert old["schema_version"] == 1
    assert old["stt_model_id"] == "voxtral-mini-4b-realtime-2602"


@pytest.mark.unit
def test_T_SET_021_explicit_local_only_rejects_cloud_stt() -> None:
    with pytest.raises(WisprError) as caught:
        parse_settings(
            {**default_settings().model_dump(), "local_only": True},
            default_registry(),
        )
    assert caught.value.error_code == ErrorCode.CLOUD_MODEL_FORBIDDEN
    assert caught.value.why == "stt_model_id"
