"""Cloud cleanup preferences remain ordered, immutable and secret-free."""

import json
from pathlib import Path

import pytest

from wispr_clone import config
from wispr_clone.contracts.common import ErrorCode, WisprError
from wispr_clone.models.registry import default_registry
from wispr_clone.settings.schema import (
    SETTINGS_SCHEMA_VERSION,
    parse_settings,
    settings_to_data,
)
from wispr_clone.settings.store import SettingsStore
from wispr_clone.storage import Database


@pytest.mark.unit
def test_nvidia_json_order_is_immutable_and_round_trips() -> None:
    selected = ["z-ai/glm-5.3", "moonshotai/kimi-k3", "deepseek-ai/deepseek-v4.1-flash"]
    payload = {
        "schema_version": SETTINGS_SCHEMA_VERSION,
        "cleanup_provider": "nvidia",
        "nvidia_cleanup_model_ids": selected,
    }
    settings = parse_settings(payload, default_registry())
    original_order = tuple(selected)
    selected.reverse()
    assert settings.nvidia_cleanup_model_ids == original_order
    assert settings.cleanup_provider == "nvidia"
    saved = settings_to_data(settings)
    assert saved["nvidia_cleanup_model_ids"] == list(original_order)
    assert parse_settings(json.loads(json.dumps(saved)), default_registry()) == settings
    assert "nvidia_api_key" not in saved


@pytest.mark.unit
@pytest.mark.parametrize(
    "value",
    [
        [],
        ["z-ai/glm-5.3"] * 2,
        "z-ai/glm-5.3",
        [True],
        [12],
        [None],
        ["no-vendor"],
        ["vendor/model with space"],
        ["vendor/../../secret"],
        ["vendor/model/extra"],
        ["vendor/" + "m" * 200],
        [f"vendor/model-{number}" for number in range(13)],
    ],
)
def test_nvidia_chain_rejects_invalid_or_unbounded_arrays(value: object) -> None:
    with pytest.raises(WisprError) as caught:
        parse_settings(
            {
                "schema_version": SETTINGS_SCHEMA_VERSION,
                "nvidia_cleanup_model_ids": value,
            },
            default_registry(),
        )
    assert caught.value.error_code == ErrorCode.VALIDATION
    assert caught.value.why == "nvidia_cleanup_model_ids"


@pytest.mark.unit
def test_nvidia_chain_allows_twelve_custom_models_and_provider_is_strict() -> None:
    models = [f"vendor/model-{number}" for number in range(12)]
    settings = parse_settings(
        {"schema_version": SETTINGS_SCHEMA_VERSION, "nvidia_cleanup_model_ids": models},
        default_registry(),
    )
    assert settings.nvidia_cleanup_model_ids == tuple(models)
    with pytest.raises(WisprError):
        parse_settings(
            {"schema_version": SETTINGS_SCHEMA_VERSION, "cleanup_provider": "unknown"},
            default_registry(),
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_v3_row_upgrade_preserves_local_cleanup_and_preferences(
    tmp_path: Path,
) -> None:
    old = {
        "schema_version": 3,
        "cleanup_model_id": "qwen/qwen3-8b",
        "cleanup_instructions": "Preserve C++ identifiers",
        "cleanup_enabled": False,
        "recording_mode": "hold",
        "theme": "dark",
    }
    async with Database(tmp_path / "v3.db") as db:
        await db.write(
            lambda conn: conn.execute(
                "INSERT INTO settings (id, data) VALUES (1, ?)", (json.dumps(old),)
            )
        )
        store = SettingsStore(db, default_registry())
        settings = await store.load()
        assert settings.schema_version == 4
        assert settings.cleanup_provider == "lmstudio"
        assert settings.nvidia_cleanup_model_ids == config.NVIDIA_CLEANUP_MODEL_IDS
        assert settings.cleanup_model_id == old["cleanup_model_id"]
        assert settings.cleanup_instructions == old["cleanup_instructions"]
        assert settings.cleanup_enabled is False
        assert settings.recording_mode == "hold" and settings.theme == "dark"
        stored = await db.read(
            lambda conn: conn.execute("SELECT data FROM settings WHERE id=1").fetchone()
        )
        assert json.loads(stored[0]) == settings_to_data(settings)
        assert await db.read(
            lambda conn: conn.execute("SELECT COUNT(*) FROM settings_backup").fetchone()
        ) == (0,)
        changed = await store.update(
            {
                "cleanup_provider": "nvidia",
                "nvidia_cleanup_model_ids": ["moonshotai/kimi-k3", "z-ai/glm-5.3"],
            }
        )
        assert changed.nvidia_cleanup_model_ids == (
            "moonshotai/kimi-k3",
            "z-ai/glm-5.3",
        )
        assert changed.cleanup_model_id == old["cleanup_model_id"]
