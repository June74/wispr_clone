"""Persistent settings contracts for WO-feat-settings-store."""

import ast
import asyncio
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from wispr_clone.contracts.common import ErrorCode, WisprError
from wispr_clone.models.registry import ModelInfo, ModelRegistry, default_registry
from wispr_clone.settings.schema import default_settings, settings_to_data
from wispr_clone.storage import Database, Migration


def _raw_settings(path: Path) -> str:
    with closing(sqlite3.connect(path)) as conn:
        return conn.execute("SELECT data FROM settings WHERE id = 1").fetchone()[0]


def _catalog_with_cloud() -> ModelRegistry:
    return ModelRegistry(
        (
            *default_registry().list_models(),
            ModelInfo(
                "cloud-cleanup", "cleanup", "Synthetic cloud model", False, "test", None
            ),
        )
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_T_SET_010_defaults_update_and_restart(tmp_path: Path) -> None:
    from wispr_clone.settings.store import SettingsStore

    path = tmp_path / "settings.db"
    async with Database(path) as db:
        store = SettingsStore(db, default_registry())
        with pytest.raises(WisprError) as caught:
            store.current()
        assert (caught.value.error_code, caught.value.where, caught.value.why) == (
            ErrorCode.STORAGE_ERROR,
            "settings.store",
            "not loaded",
        )
        assert await store.load() == default_settings()
        assert store.current() == default_settings()
        assert json.loads(_raw_settings(path)) == settings_to_data(default_settings())
        changed = await store.update({"theme": "dark"})
        assert changed.theme == "dark"
        assert store.current() == changed

    async with Database(path) as reopened:
        fresh_store = SettingsStore(reopened, default_registry())
        assert (await fresh_store.load()).theme == "dark"
        assert fresh_store.current().theme == "dark"
        assert json.loads(_raw_settings(path))["theme"] == "dark"


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(
    "raw,reason",
    [
        ("{broken", "invalid json"),
        ('["not an object"]', "invalid json"),
        ('{"schema_version":1,"theme":"violet"}', "invalid settings"),
        ('{"schema_version":1,"cleanup_model_id":"cloud-cleanup"}', "invalid settings"),
    ],
    ids=["malformed-json", "json-array", "bad-field", "cloud-default-registry"],
)
async def test_T_SET_011_recovers_only_settings_row(
    tmp_path: Path, raw: str, reason: str
) -> None:
    from wispr_clone.settings.store import SettingsStore

    from wispr_clone.storage.migrations import m001_base, m002_settings

    def unrelated(conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE unrelated (value TEXT NOT NULL)")

    path = tmp_path / "corrupt.db"
    migrations = [
        Migration(1, "base", m001_base.apply),
        Migration(2, "settings", m002_settings.apply),
        Migration(3, "test unrelated", unrelated),
    ]
    async with Database(path, migrations) as db:
        await db.write(
            lambda conn: conn.execute("INSERT INTO unrelated VALUES (?)", ("keep me",))
        )
        await db.write(
            lambda conn: conn.execute(
                "INSERT INTO settings (id, data) VALUES (1, ?)", (raw,)
            )
        )
        assert await SettingsStore(db, default_registry()).load() == default_settings()
        assert json.loads(_raw_settings(path)) == settings_to_data(default_settings())
        backup = await db.read(
            lambda conn: conn.execute(
                "SELECT reason, data FROM settings_backup"
            ).fetchall()
        )
        assert backup == [(reason, raw)]
        assert await db.read(
            lambda conn: conn.execute("SELECT value FROM unrelated").fetchall()
        ) == [("keep me",)]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_T_SET_011_known_cloud_row_and_backup_limit(tmp_path: Path) -> None:
    from wispr_clone.settings.store import MAX_SETTINGS_BACKUPS, SettingsStore

    path = tmp_path / "backup_limit.db"
    async with Database(path) as db:
        cloud_raw = '{"schema_version":1,"cleanup_model_id":"cloud-cleanup"}'
        await db.write(
            lambda conn: conn.execute(
                "INSERT INTO settings (id, data) VALUES (1, ?)", (cloud_raw,)
            )
        )
        assert (
            await SettingsStore(db, _catalog_with_cloud()).load() == default_settings()
        )
        assert await db.read(
            lambda conn: conn.execute(
                "SELECT reason, data FROM settings_backup"
            ).fetchall()
        ) == [("invalid settings", cloud_raw)]

        raws = [cloud_raw]
        for index in range(1, 7):
            raw = f"broken-{index}"
            raws.append(raw)
            await db.write(
                lambda conn: conn.execute(
                    "UPDATE settings SET data = ? WHERE id = 1", (raw,)
                )
            )
            assert (
                await SettingsStore(db, default_registry()).load() == default_settings()
            )
        backups = await db.read(
            lambda conn: conn.execute(
                "SELECT reason, data FROM settings_backup ORDER BY id"
            ).fetchall()
        )
        assert MAX_SETTINGS_BACKUPS == 5
        assert backups == [("invalid json", raw) for raw in raws[-5:]]
        assert json.loads(_raw_settings(path)) == settings_to_data(default_settings())


@pytest.mark.asyncio
@pytest.mark.integration
async def test_T_SET_012_patch_rollback_and_concurrent_merge(tmp_path: Path) -> None:
    from wispr_clone.settings.store import SettingsStore

    path = tmp_path / "patch.db"
    async with Database(path) as db:
        store = SettingsStore(db, _catalog_with_cloud())
        await store.load()
        original_row = _raw_settings(path)
        original_current = store.current()
        invalid = [
            ({"cleanup_enabled": "false"}, ErrorCode.VALIDATION, "cleanup_enabled"),
            ({"not_a_setting": True}, ErrorCode.VALIDATION, "not_a_setting"),
            (
                {"cleanup_model_id": "cloud-cleanup"},
                ErrorCode.CLOUD_MODEL_FORBIDDEN,
                "cleanup_model_id",
            ),
            ({"schema_version": 1}, ErrorCode.VALIDATION, "schema_version"),
        ]
        for patch, code, why in invalid:
            with pytest.raises(WisprError) as caught:
                await store.update(patch)
            assert (caught.value.error_code, caught.value.where, caught.value.why) == (
                code,
                "settings.schema",
                why,
            )
            assert _raw_settings(path) == original_row
            assert settings_to_data(store.current()) == settings_to_data(
                original_current
            )

        changed = await store.update({"theme": "dark", "recording_mode": "hold"})
        assert (changed.theme, changed.recording_mode) == ("dark", "hold")
        assert (store.current().theme, store.current().recording_mode) == (
            "dark",
            "hold",
        )
        assert json.loads(_raw_settings(path))["theme"] == "dark"
        assert json.loads(_raw_settings(path))["recording_mode"] == "hold"

        await asyncio.gather(
            store.update({"theme": "light"}),
            store.update({"cleanup_enabled": False}),
        )
        assert (
            store.current().theme,
            store.current().recording_mode,
            store.current().cleanup_enabled,
        ) == (
            "light",
            "hold",
            False,
        )
        stored = json.loads(_raw_settings(path))
        assert (
            stored["theme"],
            stored["recording_mode"],
            stored["cleanup_enabled"],
        ) == ("light", "hold", False)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_T_SET_013_upgrade_is_rewritten(tmp_path: Path) -> None:
    from wispr_clone.settings.store import SettingsStore

    path = tmp_path / "upgrade.db"
    old = '{"schema_version":0,"theme":"dark"}'
    async with Database(path) as db:
        await db.write(
            lambda conn: conn.execute(
                "INSERT INTO settings (id, data) VALUES (1, ?)", (old,)
            )
        )

        def upgrade(data: dict[str, object]) -> dict[str, object]:
            return {**data, "schema_version": 1, "recording_mode": "hold"}

        store = SettingsStore(db, default_registry(), upgrade_steps={0: upgrade})
        loaded = await store.load()
        assert (loaded.schema_version, loaded.theme, loaded.recording_mode) == (
            1,
            "dark",
            "hold",
        )
        assert store.current() == loaded
        assert json.loads(_raw_settings(path)) == settings_to_data(loaded)
        assert _raw_settings(path) != old


@pytest.mark.asyncio
@pytest.mark.integration
async def test_T_SET_014_storage_exports_and_sqlite_import_boundary(
    tmp_path: Path,
) -> None:
    import wispr_clone.settings.store as store_module

    from wispr_clone.storage import Connection, IntegrityError
    from wispr_clone.storage.migrations import m002_settings

    assert Connection is sqlite3.Connection
    assert IntegrityError is sqlite3.IntegrityError
    assert (m002_settings.VERSION, m002_settings.NAME) == (2, "settings")
    for module in (store_module, m002_settings):
        path = Path(module.__file__)
        syntax = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(syntax):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            assert all(name.split(".")[0] != "sqlite3" for name in names), path

    async with Database(tmp_path / "migration.db") as db:
        assert db.schema_version == 2
        tables = await db.read(
            lambda conn: {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        )
        assert {"settings", "settings_backup"} <= tables
