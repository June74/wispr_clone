# WO-feat-dictionary-repo — Persistent personal dictionary

```text
Work-order ID: WO-feat-dictionary-repo
Role file / requested model: RED + verify: sol-feature-test-author.md / gpt-6-sol
                             GREEN: luna-core-programmer.md / gpt-6-luna
Pipeline branch or P0/M stage: Wave 2, branch feat/dictionary-repo (needs storage + dictionary-core,
  both merged; migration 003 merges after m002_settings from feat/settings-store)
Outcome and observable acceptance:
  Dictionary entries persist in SQLite with CRUD, unique normalized spellings, the same
  conflict rules as dictionary-core, atomic import (an invalid import changes nothing) and
  export, and they survive deletion of temporary history.
Base revision / worktree / branch: a94db2d / ~/projects/wc-dictionary-repo / feat/dictionary-repo
  (the coordinator rebases onto main after feat/settings-store merges, before GREEN)
Relevant sections: feature spec "Personal dictionary"; CODEMAP.md §3 (dictionary -> storage), §5
  (dictionary row: unique normalized preferred spelling, aliases, note, timestamps; persistent);
  dev_pipeline.md §6 Wave 2 row feat/dictionary-repo, §7.2 migration rules; WO-feat-dictionary-core
  (DictionaryEntry, normalize, validate_entries, parse_import, export_dictionary);
  WO-feat-settings-store (storage re-exports Connection, IntegrityError; merge order).
Exact writable paths (under backend_dev/):
  Sol:  tests/integration/dictionary/**
  Luna: src/wispr_clone/dictionary/repo.py, src/wispr_clone/storage/migrations/m003_dictionary.py
Read-only: everything else (apply.py, import_export.py, storage/**, sqlite3.toml).
Allowed imports: dictionary.repo -> dictionary.apply, dictionary.import_export, storage (Database,
  Connection, IntegrityError), contracts + stdlib (json, dataclasses, asyncio). Never
  `import sqlite3` in dictionary/ or in the migration.
Required tiers: S, U, I (real SQLite in tmp_path) on ubuntu and windows.
Check commands (from backend_dev/, UV_LINK_MODE=copy):
  uv sync --locked; uv run ruff check .; uv run ruff format --check .;
  uv run mypy src scripts tests/_attribution tests/fakes; uv run python scripts/check_imports.py;
  uv run pytest -q -W error
Authorization: edit only writable paths; no git writes; no PRs; no new dependencies.
Privacy: dictionary text is user data; error `why` names ids, rules and indexes only.
Handoff: coordinator. Sol: RED command/output. Luna: GREEN outputs. Sol: verification findings.
```

## Pinned API (use these exact names)

`m003_dictionary.py`: `VERSION = 3`, `NAME = "dictionary"`; imports `Connection` from
`wispr_clone.storage.migrations`; creates:

```sql
CREATE TABLE dictionary_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    spelling TEXT NOT NULL,
    normalized TEXT NOT NULL UNIQUE,     -- dictionary.apply.normalize(spelling)
    aliases TEXT NOT NULL,               -- JSON list of strings
    note TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
```

`wispr_clone.dictionary.repo`:

```python
@dataclass(frozen=True, slots=True)
class StoredEntry:
    id: int
    entry: DictionaryEntry
    created_at: float
    updated_at: float

class DictionaryRepo:
    def __init__(self, db: Database, *, clock: Callable[[], float]) -> None   # no I/O
    async def list_entries(self) -> tuple[StoredEntry, ...]     # ordered by id
    async def entries(self) -> tuple[DictionaryEntry, ...]      # snapshot for apply_dictionary
    async def add(self, entry: DictionaryEntry) -> StoredEntry
    async def update(self, entry_id: int, entry: DictionaryEntry) -> StoredEntry
    async def delete(self, entry_id: int) -> None
    async def import_text(self, text: str) -> ImportPlan
    async def export_text(self) -> str
```

Rules (all errors `WisprError(ErrorCode.VALIDATION, where="dictionary.repo", why=...)` unless noted):

- Every mutation runs inside ONE `db.write` callback that reads the current rows, validates, and
  writes; any error rolls everything back.
- `add`/`update` validate the would-be full set with `validate_entries`. The repo translates the
  core wording into ids: `"new entry: <rule>"` for length/shape rules (`spelling`, `alias`,
  `note`), `"new entry: duplicate of id <k>"`, `"new entry: conflicts with id <k>"`
  (`update` uses `"entry id <entry_id>: ..."` instead of `"new entry: ..."`). An `update` may keep
  its own spelling/aliases (it is compared against the OTHER entries only).
- A UNIQUE violation on `normalized` that slips past validation (e.g. a concurrent writer) →
  caught as `IntegrityError` → `"new entry: duplicate"`; never a raw sqlite error.
- `update`/`delete` of an unknown id → why `"not found"`. `update` keeps `created_at` and sets
  `updated_at = clock()`; `add` sets both to `clock()`.
- `import_text(text)`: `parse_import(text, current entries)` (errors propagate unchanged, with
  `where="dictionary.import"`), then inserts every `plan.to_add` in the same transaction; returns
  the plan. An invalid import leaves the table byte-for-byte unchanged.
- `export_text()` = `export_dictionary(entries in id order)`.
- Nothing is logged.

## Tests (Sol, tests/integration/dictionary/; real SQLite in tmp_path; `@pytest.mark.asyncio`;
## a counter-based fake clock, e.g. `itertools.count(1000.0)`)

| ID | Must assert |
|---|---|
| T-DIC-010 | add → list → update → delete round trip with ids, timestamps (created kept, updated advanced), aliases/notes/Unicode (Korean) preserved; data survives closing and reopening the `Database`; `entries()` returns plain `DictionaryEntry` values in id order; unknown id update/delete → `"not found"` |
| T-DIC-011 | adding `"openwhispr"` after `"OpenWhispr"` → `"new entry: duplicate of id <k>"`; an alias equal to another entry's spelling/alias → `"new entry: conflicts with id <k>"`; `update` that keeps its own terms is accepted, one that collides with another entry is rejected with the `"entry id <n>: ..."` wording; failed mutations leave the table unchanged; no sentinel entry text appears in any error |
| T-DIC-012 | an import with one bad entry, a conflicting alias, or malformed JSON raises and leaves the table byte-for-byte unchanged (compare a full `SELECT * ORDER BY id` before/after); a valid import inserts `to_add` atomically and reports `skipped_duplicates`; export → import into a fresh DB reproduces the entries |
| **T-DIC-013** (invariant) | dictionary rows survive deletion of temporary history: with a test migration that creates stand-in `runs` / `insertion_attempts` tables, deleting all their rows (and dropping them) leaves every dictionary row intact. (Re-checked against the real history tables when feat/history lands.) |
| T-DIC-014 | `m003_dictionary` is version 3, name `"dictionary"`; `dictionary/repo.py` and the migration never import `sqlite3` (ast scan); a raced duplicate (two concurrent `add` calls with the same normalized spelling) yields exactly one row and one `VALIDATION` error |

## Coordinator review of GREEN (binding)

1. Rule for every migration test from now on: assert that a migration's own tables/version are
   present, never that the database's LATEST version equals a fixed number (that breaks with each
   new migration, as T-STO-001 and now T-SET-014 did). RESERVED for Sol in this order:
   `tests/integration/settings/test_store.py` T-SET-014 → assert `db.schema_version >= 2` plus the
   settings tables. Sol also fixes the ruff import-order findings in its own new dictionary tests.
2. `import_text` must also map a raced UNIQUE violation (`IntegrityError`) to
   `WisprError(VALIDATION, "dictionary.repo", "import: duplicate")`, never a raw sqlite error.

## Coordinator decisions after verification

3. A stored row that cannot be read (aliases not a JSON list of strings, etc.) →
   `WisprError(VALIDATION, "dictionary.repo", "stored entry id <k>: corrupt")`; a stored row that
   fails `validate_entries` on its own → `"stored entry id <k>: <rule>"`. Neither is ever reported
   as `"new entry: ..."`, and no stored text appears in the error. Reads never modify the table.
4. Review item 2 confirmed by Sol's test (raced UNIQUE in `import_text` → `"import: duplicate"`,
   table unchanged).
