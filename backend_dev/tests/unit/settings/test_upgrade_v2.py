"""Versioned upgrades preserve settings through obsolete local-only removal."""

import json
from pathlib import Path

import pytest

from wispr_clone.contracts.common import ErrorCode, WisprError
from wispr_clone.models.registry import default_registry
from wispr_clone.settings.schema import (
    SETTINGS_SCHEMA_VERSION,
    default_settings,
    parse_settings,
)
from wispr_clone.settings.store import SettingsStore
from wispr_clone.storage import Database

WHISPER = "openai/whisper-large-v3-turbo"


@pytest.mark.unit
def test_T_SET_021_defaults_and_registry() -> None:
    settings = default_settings()
    assert SETTINGS_SCHEMA_VERSION == 4
    assert settings.stt_model_id == WHISPER
    assert "local_only" not in settings.model_dump()
    stt, cleanup = default_registry().list_models()
    assert (stt.model_id, stt.role, stt.local, stt.endpoint) == (
        WHISPER,
        "stt",
        False,
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
    assert (upgraded.schema_version, upgraded.stt_model_id) == (4, WHISPER)
    assert "local_only" not in upgraded.model_dump()
    assert (upgraded.recording_mode, upgraded.theme, upgraded.cleanup_instructions) == (
        "hold",
        "dark",
        "Keep medical terms",
    )
    assert old["schema_version"] == 1
    assert old["stt_model_id"] == "voxtral-mini-4b-realtime-2602"


@pytest.mark.unit
@pytest.mark.parametrize("old_value", [True, False])
def test_T_SET_023_v2_upgrade_removes_local_only(old_value: bool) -> None:
    old: dict[str, object] = {
        "schema_version": 2,
        "local_only": old_value,
        "recording_mode": "hold",
        "theme": "dark",
        "cleanup_instructions": "Keep medical terms",
        "microphone_id": "2",
    }
    parsed = parse_settings(old, default_registry())
    assert parsed.schema_version == 4
    assert "local_only" not in parsed.model_dump()
    assert (parsed.recording_mode, parsed.theme, parsed.cleanup_instructions) == (
        "hold",
        "dark",
        "Keep medical terms",
    )
    assert parsed.microphone_id == "2"
    assert old["schema_version"] == 2 and old["local_only"] is old_value
    defaults = default_settings().model_dump()
    assert defaults["schema_version"] == 4 and "local_only" not in defaults


@pytest.mark.unit
@pytest.mark.asyncio
async def test_T_SET_022_real_v1_row_upgrade(tmp_path: Path) -> None:
    old = {
        "schema_version": 1,
        "stt_model_id": "voxtral-mini-4b-realtime-2602",
        "local_only": True,
        "recording_mode": "hold",
        "theme": "dark",
        "cleanup_instructions": "Keep medical terms",
    }
    async with Database(tmp_path / "upgrade-v1.db") as db:
        await db.write(
            lambda conn: conn.execute(
                "INSERT INTO settings (id, data) VALUES (1, ?)", (json.dumps(old),)
            )
        )
        store = SettingsStore(db, default_registry())
        upgraded = await store.load()
        assert (upgraded.schema_version, upgraded.stt_model_id) == (4, WHISPER)
        assert (
            upgraded.recording_mode,
            upgraded.theme,
            upgraded.cleanup_instructions,
        ) == (
            "hold",
            "dark",
            "Keep medical terms",
        )
        persisted = await db.read(
            lambda conn: conn.execute(
                "SELECT data FROM settings WHERE id = 1"
            ).fetchone()
        )
        assert persisted is not None
        assert json.loads(persisted[0]) == upgraded.model_dump(mode="json")


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("old_value", [True, False])
async def test_T_SET_024_real_v2_row_and_patch_rejection(
    tmp_path: Path, old_value: bool
) -> None:
    old = {
        "schema_version": 2,
        "local_only": old_value,
        "recording_mode": "hold",
        "theme": "dark",
        "cleanup_instructions": "Keep medical terms",
        "microphone_id": "0",
    }
    async with Database(tmp_path / "upgrade-v2.db") as db:
        await db.write(
            lambda conn: conn.execute(
                "INSERT INTO settings (id, data) VALUES (1, ?)", (json.dumps(old),)
            )
        )
        store = SettingsStore(db, default_registry())
        loaded = await store.load()
        assert loaded.schema_version == 4
        assert "local_only" not in loaded.model_dump()
        assert (loaded.recording_mode, loaded.theme, loaded.microphone_id) == (
            "hold",
            "dark",
            "0",
        )
        assert loaded.cleanup_instructions == "Keep medical terms"
        row = await db.read(
            lambda conn: conn.execute(
                "SELECT data FROM settings WHERE id = 1"
            ).fetchone()
        )
        assert row is not None and json.loads(row[0]) == loaded.model_dump(mode="json")
        backups = await db.read(
            lambda conn: conn.execute("SELECT COUNT(*) FROM settings_backup").fetchone()
        )
        assert backups == (0,)
        with pytest.raises(WisprError) as caught:
            await store.update({"local_only": old_value})
        assert caught.value.error_code == ErrorCode.VALIDATION
        assert store.current() == loaded
