"""Persistent, validated settings backed by the application database."""

import asyncio
import json
from collections.abc import Mapping

from wispr_clone.contracts.common import ErrorCode, WisprError
from wispr_clone.settings.schema import (
    UPGRADE_STEPS,
    ModelCatalog,
    Settings,
    UpgradeStep,
    default_settings,
    parse_settings,
    settings_to_data,
)
from wispr_clone.storage import Connection, Database

MAX_SETTINGS_BACKUPS = 5


class SettingsStore:
    """Load and atomically update a single validated settings row."""

    def __init__(
        self,
        db: Database,
        catalog: ModelCatalog,
        *,
        upgrade_steps: Mapping[int, UpgradeStep] = UPGRADE_STEPS,
    ) -> None:
        self._db = db
        self._catalog = catalog
        self._upgrade_steps = upgrade_steps
        self._settings: Settings | None = None
        self._lock = asyncio.Lock()

    def current(self) -> Settings:
        """Return the last loaded or updated settings snapshot."""
        if self._settings is None:
            raise WisprError(ErrorCode.STORAGE_ERROR, "settings.store", "not loaded")
        return self._settings

    async def load(self) -> Settings:
        """Read settings, upgrading valid old data or recovering a corrupt row."""
        async with self._lock:
            defaults = default_settings()
            defaults_json = _encode(defaults)

            def load_row(conn: Connection) -> Settings:
                row = conn.execute("SELECT data FROM settings WHERE id = 1").fetchone()
                if row is None:
                    conn.execute(
                        "INSERT INTO settings (id, data) VALUES (1, ?)",
                        (defaults_json,),
                    )
                    return defaults

                raw = str(row[0])
                try:
                    decoded = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    return _recover(conn, raw, "invalid json", defaults_json, defaults)
                if not isinstance(decoded, dict):
                    return _recover(conn, raw, "invalid json", defaults_json, defaults)

                try:
                    parsed = parse_settings(
                        decoded, self._catalog, upgrade_steps=self._upgrade_steps
                    )
                except WisprError:
                    return _recover(
                        conn, raw, "invalid settings", defaults_json, defaults
                    )

                if decoded.get("schema_version") != parsed.schema_version:
                    conn.execute(
                        "UPDATE settings SET data = ? WHERE id = 1",
                        (_encode(parsed),),
                    )
                return parsed

            loaded = await self._db.write(load_row)
            self._settings = loaded
            return loaded

    async def update(self, patch: Mapping[str, object]) -> Settings:
        """Merge and validate a patch in the same serialized write as persistence."""
        if "schema_version" in patch:
            raise WisprError(ErrorCode.VALIDATION, "settings.schema", "schema_version")

        async with self._lock:
            defaults = default_settings()

            def update_row(conn: Connection) -> Settings:
                row = conn.execute("SELECT data FROM settings WHERE id = 1").fetchone()
                if row is None:
                    stored = settings_to_data(defaults)
                else:
                    try:
                        decoded = json.loads(str(row[0]))
                    except (json.JSONDecodeError, TypeError):
                        raise WisprError(
                            ErrorCode.VALIDATION, "settings.schema", "settings"
                        ) from None
                    if not isinstance(decoded, dict):
                        raise WisprError(
                            ErrorCode.VALIDATION, "settings.schema", "settings"
                        )
                    stored = decoded

                merged = {**stored, **patch}
                updated = parse_settings(
                    merged, self._catalog, upgrade_steps=self._upgrade_steps
                )
                serialized = _encode(updated)
                conn.execute(
                    "INSERT INTO settings (id, data) VALUES (1, ?) "
                    "ON CONFLICT(id) DO UPDATE SET data = excluded.data",
                    (serialized,),
                )
                return updated

            updated = await self._db.write(update_row)
            self._settings = updated
            return updated


def _encode(settings: Settings) -> str:
    """Serialize validated settings without exposing user values on failure."""
    return json.dumps(settings_to_data(settings), separators=(",", ":"))


def _recover(
    conn: Connection,
    raw: str,
    reason: str,
    defaults_json: str,
    defaults: Settings,
) -> Settings:
    """Back up only the damaged settings row and replace it with defaults."""
    conn.execute(
        "INSERT INTO settings_backup (reason, data) VALUES (?, ?)", (reason, raw)
    )
    conn.execute(
        "DELETE FROM settings_backup WHERE id NOT IN "
        "(SELECT id FROM settings_backup ORDER BY id DESC LIMIT ?)",
        (MAX_SETTINGS_BACKUPS,),
    )
    conn.execute("UPDATE settings SET data = ? WHERE id = 1", (defaults_json,))
    return defaults
