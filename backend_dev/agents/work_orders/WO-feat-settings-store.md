# WO-feat-settings-store — Persistent settings on SQLite

```text
Work-order ID: WO-feat-settings-store
Role file / requested model: RED + verify: sol-feature-test-author.md / gpt-6-sol
                             GREEN: luna-core-programmer.md / gpt-6-luna
Pipeline branch or P0/M stage: Wave 2, branch feat/settings-store (needs storage + settings-models,
  both merged)
Outcome and observable acceptance:
  Settings persist in one validated JSON row, survive restart, upgrade older stored versions,
  recover from a corrupted row by backing up only that row and falling back to defaults, and
  apply patches atomically (all or nothing).
Base revision / worktree / branch: b6a5cb3 / ~/projects/wc-settings-store / feat/settings-store
Relevant sections: CODEMAP.md §5 (settings row; "settings corruption recovery backs up only settings
  data"), §3 (settings -> storage, contracts); dev_pipeline.md §6 Wave 2 row feat/settings-store,
  §7.2 migration single-writer rule; WO-feat-storage (Database API, decisions 9-10);
  WO-feat-settings-models (parse_settings, settings_to_data, ModelCatalog).
Exact writable paths (under backend_dev/):
  Sol:  tests/integration/settings/**
  Luna: src/wispr_clone/settings/store.py, src/wispr_clone/storage/migrations/m002_settings.py,
        src/wispr_clone/storage/__init__.py (RESERVED for this order: two re-exports, below)
Read-only: everything else (schema.py, db.py, the runner, sqlite3.toml).
Allowed imports: settings.store -> settings.schema, storage, contracts, config, util + stdlib
  (json, asyncio). NEVER `import sqlite3` in settings/ or in a migration module (the sqlite3 impact
  fragment is single-owner; see WO-feat-storage decision 10).
Required tiers: S, U, I (real SQLite files in tmp_path) on ubuntu and windows.
Check commands (from backend_dev/, UV_LINK_MODE=copy):
  uv sync --locked; uv run ruff check .; uv run ruff format --check .;
  uv run mypy src scripts tests/_attribution tests/fakes; uv run python scripts/check_imports.py;
  uv run pytest -q -W error
Authorization: edit only writable paths; no git writes; no PRs; no new dependencies.
Deferred: T-SET-002 (shortcut validation) still waits for feat/hotkeys.
Handoff: coordinator. Sol: RED command/output. Luna: GREEN outputs. Sol: verification findings.
```

## Migration order rule (coordinator decision, applies to all of wave 2)

The runner requires contiguous versions, so wave-2 migrations merge in number order:
`m002_settings` (this order) → `m003_dictionary` (feat/dictionary-repo) → `m004_history`
(feat/history). A later-numbered branch may be developed in parallel but is merged only after the
lower numbers are on `main`.

## Reserved storage re-exports

`wispr_clone.storage` additionally exports `Connection` (the runner's alias for
`sqlite3.Connection`) and `IntegrityError = sqlite3.IntegrityError`, so wave-2 code can type
callbacks and catch UNIQUE violations without importing `sqlite3` itself.
`__all__ = ["Connection", "Database", "IntegrityError", "Migration"]`.

## Pinned API (use these exact names)

`m002_settings.py`: `VERSION = 2`, `NAME = "settings"`, creates:

```sql
CREATE TABLE settings (id INTEGER PRIMARY KEY CHECK (id = 1), data TEXT NOT NULL);
CREATE TABLE settings_backup (id INTEGER PRIMARY KEY AUTOINCREMENT,
                              reason TEXT NOT NULL, data TEXT NOT NULL);
```

`wispr_clone.settings.store`:

```python
MAX_SETTINGS_BACKUPS = 5

class SettingsStore:
    def __init__(self, db: Database, catalog: ModelCatalog, *,
                 upgrade_steps: Mapping[int, UpgradeStep] = UPGRADE_STEPS) -> None   # no I/O
    async def load(self) -> Settings
    def current(self) -> Settings
    async def update(self, patch: Mapping[str, object]) -> Settings
```

- `load()`:
  - no row → write `settings_to_data(default_settings())` and return defaults;
  - row holds valid data (possibly an older `schema_version`) → `parse_settings(data, catalog,
    upgrade_steps=...)`; if it was upgraded, write the upgraded data back in the same step;
  - row is corrupted (not JSON, not a JSON object, or `parse_settings` raises `WisprError`) →
    in ONE write transaction: insert the raw row text into `settings_backup` with reason
    `"invalid json"` or `"invalid settings"`, delete the oldest backups beyond
    `MAX_SETTINGS_BACKUPS`, replace the row with defaults; return defaults. Nothing else in the
    database is touched. A `CLOUD_MODEL_FORBIDDEN` stored row counts as invalid settings.
- `current()` returns the last loaded/updated value; before `load()` →
  `WisprError(ErrorCode.STORAGE_ERROR, "settings.store", "not loaded")`.
- `update(patch)`:
  - `patch` containing `schema_version` → `WisprError(VALIDATION, "settings.schema",
    "schema_version")`;
  - inside ONE `db.write` callback: read the stored row, merge `patch` over it, validate the
    whole result with `parse_settings`, write it; any error → the transaction rolls back, the
    stored row and `current()` are unchanged, and the `WisprError` propagates unchanged;
  - two concurrent `update` calls on different fields both take effect (the merge happens
    inside the serialized write, not from a stale cache);
  - returns and caches the new `Settings`.
- Error text never includes setting values (cleanup instructions are user text).

## Tests (Sol, tests/integration/settings/; real SQLite in tmp_path; `@pytest.mark.asyncio`)

| ID | Must assert |
|---|---|
| T-SET-010 | a fresh DB `load()`s defaults and stores them; `update({"theme": "dark"})` then close, reopen a new `Database` + `SettingsStore` on the same file → `load()` returns theme dark; `current()` before `load()` → `STORAGE_ERROR` |
| T-SET-011 | a corrupted row (invalid JSON; valid JSON that is not an object; a valid object with a bad field; a cloud model under local-only with the default registry) → `load()` returns defaults, the row now holds defaults, `settings_backup` gained exactly one row with the raw text and the pinned reason; another table created by a test migration is untouched; after 7 corruptions only the 5 newest backups remain |
| T-SET-012 | an invalid patch (bad type, unknown key, cloud model under local-only, `schema_version`) raises `WisprError` and leaves the stored row and `current()` byte-for-byte unchanged; a valid multi-field patch is applied all at once; two concurrent `update` calls on different fields both persist |
| T-SET-013 | a stored version-0 row plus injected `upgrade_steps={0: fn}` loads as version 1 and the row is rewritten at version 1 |
| T-SET-014 | `wispr_clone.storage` exports `Connection is sqlite3.Connection` and `IntegrityError is sqlite3.IntegrityError`; `settings/store.py` and `m002_settings.py` do not import `sqlite3` (ast scan) |

## Coordinator review of GREEN (binding)

1. `IntegrityError` is defined next to `Connection` in `storage/migrations/__init__.py`
   (`IntegrityError = sqlite3.IntegrityError`; that module already imports sqlite3 and is listed in
   `sqlite3.toml`) and re-exported from `storage/__init__.py`. No `type: ignore` re-export of
   `sqlite3` through `db.py`.
2. `tests/integration/storage/test_database.py::test_T_STO_001...` asserts discovery returns only
   version 1; that breaks for every wave-2 migration. RESERVED for Sol in this order: change it to
   assert the discovered versions are exactly `1..N` (contiguous, starting at 1, `m001_base` first).
