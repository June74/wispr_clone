# WO-feat-storage — SQLite writer and migration runner

```text
Work-order ID: WO-feat-storage
Role file / requested model: RED + verify: sol-feature-test-author.md (T-STO) and
                             sol-boundary-test-author.md (P-SQLITE, impact fragment) / gpt-6-sol
                             GREEN: luna-core-programmer.md (storage) and, for the one reserved
                             plugin change below, luna-integration-programmer.md / gpt-6-luna
Pipeline branch or P0/M stage: Wave 1, branch feat/storage
Outcome and observable acceptance:
  One async-friendly Database object owns the only SQLite connection, runs every read and write on
  one dedicated writer thread, applies ordered migrations transactionally, and opens with WAL,
  foreign keys and full sync. Wave 2 (settings-store, dictionary-repo, history) builds on it.
Base revision / worktree / branch: 984ab46 / ~/projects/wc-storage / feat/storage
Relevant sections: CODEMAP.md §2 (worker owns the single SQLite writer), §3 (storage row),
  §5 (WAL, single writer, ordered migrations; claims must be durable before dispatch);
  dev_pipeline.md §2.1–2.2, §5.2–5.4 (P-SQLITE), §6 Wave 1 row feat/storage, §7.2 (migration
  single-writer rule).
Prerequisites: P0 merged (contracts v1 frozen, import checker, attribution plugin, CI).
Exact writable paths (under backend_dev/):
  Sol:  tests/unit/storage/**, tests/integration/storage/**, tests/probes/sqlite/**,
        tests/_attribution/impact/sqlite3.toml, tests/diag/test_stdlib_dependency.py (new file)
  Luna: src/wispr_clone/storage/__init__.py, src/wispr_clone/storage/db.py,
        src/wispr_clone/storage/migrations/__init__.py (the runner),
        src/wispr_clone/storage/migrations/m001_base.py,
        tests/_attribution/plugin.py (RESERVED for this order only: the stdlib-dependency change)
Read-only: everything else (contracts/, config.py, util/, tests/conftest.py, tests/fakes/**).
Allowed imports: storage -> contracts, config, util + stdlib (sqlite3, asyncio, threading,
  concurrent.futures, importlib, pkgutil, pathlib). No third-party packages.
Test IDs and expected assertions: see "Pinned API" and "Tests" below.
Probe IDs / impact fragment: P-SQLITE-001..004; tests/_attribution/impact/sqlite3.toml (Sol).
Required tiers: S, U, I (real SQLite files in tmp_path), P (probes) on ubuntu and windows.
Check commands (from backend_dev/, UV_LINK_MODE=copy):
  uv sync --locked; uv run ruff check .; uv run ruff format --check .;
  uv run mypy src scripts tests/_attribution tests/fakes; uv run python scripts/check_imports.py;
  uv run pytest -q -W error
Authorization: edit only writable paths; no git writes; no PRs; the coordinator commits, pushes
  and opens the PR. No new dependencies.
Handoff: coordinator. Sol: RED command/output and why each failure is the right one.
  Luna: GREEN output for every check. Sol: verification result and findings.
```

## Pinned API (use these exact names)

Module names: Python cannot import a module whose name starts with a digit, so migration files are
`m001_base.py`, `m002_settings.py`, `m003_dictionary.py`, `m004_history.py` (pipeline §7.2's
"001_base.py" etc. means these files).

`wispr_clone.storage.migrations` (the runner, in `__init__.py`):

```python
@dataclass(frozen=True, slots=True)
class Migration:
    version: int                                  # 1, 2, 3 ... contiguous, no gaps
    name: str
    apply: Callable[[sqlite3.Connection], None]   # DDL/DML only; never commits itself

def discover_migrations() -> tuple[Migration, ...]
    # Finds modules m<NNN>_<name>.py in this package; each defines VERSION: int and
    # def apply(conn) -> None. Returned sorted by version. Duplicate or missing versions
    # (gaps) raise WisprError(ErrorCode.STORAGE_ERROR, where="storage.migrations", why=...).

def apply_migrations(conn: sqlite3.Connection, migrations: Sequence[Migration]) -> int
    # Reads PRAGMA user_version; applies every migration with version > current, in order,
    # each in its OWN transaction: BEGIN IMMEDIATE; apply(conn); PRAGMA user_version = N; COMMIT.
    # On any exception: ROLLBACK (schema and user_version return to the previous version),
    # stop, and raise WisprError(ErrorCode.STORAGE_ERROR, where=f"migration {version:03d}",
    # why=type(exc).__name__). Earlier successful migrations stay applied.
    # A database whose user_version is higher than the highest known migration raises
    # WisprError(STORAGE_ERROR, where="storage.migrations", why="newer schema").
    # Returns the resulting user_version. Re-running with nothing new is a no-op
    # (no apply() call, version unchanged).
```

`m001_base.py`: `VERSION = 1`; creates `app_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)`.
Nothing else. Later tables belong to wave-2 migrations.

`wispr_clone.storage.db`:

```python
class Database:
    def __init__(self, path: Path, migrations: Sequence[Migration] | None = None) -> None
        # No I/O in __init__. migrations=None means discover_migrations().
    async def open(self) -> None
        # On the writer thread: sqlite3.connect(path, isolation_level=None) (explicit
        # transactions; the connection is created on the writer thread and only ever used there,
        # so check_same_thread stays at its default); PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;
        # PRAGMA synchronous=FULL; PRAGMA busy_timeout=5000; then apply_migrations.
        # Connect/pragma failures raise ThirdPartyError("sqlite3", "open", <exception type name>,
        # ErrorCode.STORAGE_ERROR). Migration failures propagate the WisprError above and leave
        # the Database closed. Opening twice raises WisprError(STORAGE_ERROR, "storage.db", ...).
    async def write(self, fn: Callable[[sqlite3.Connection], T]) -> T
        # Runs fn(conn) on the writer thread inside BEGIN IMMEDIATE ... COMMIT. If fn raises,
        # ROLLBACK and re-raise the SAME exception unchanged (callers such as history rely on
        # sqlite3.IntegrityError for UNIQUE checks). Returns fn's result.
    async def read(self, fn: Callable[[sqlite3.Connection], T]) -> T
        # Runs fn(conn) on the writer thread, no explicit transaction.
    async def close(self) -> None       # idempotent; closes the connection and stops the thread
    @property
    def schema_version(self) -> int     # last known user_version (0 before open)
    async def __aenter__(self) -> "Database"   # open()
    async def __aexit__(self, *exc) -> None      # close()
```

- Exactly one writer thread per Database (a `concurrent.futures.ThreadPoolExecutor(max_workers=1)`
  or an equivalent single thread). Calls submitted from any number of asyncio tasks run one at a
  time, in submission order, never on the event loop thread.
- `write`/`read` before `open` or after `close` raise WisprError(STORAGE_ERROR, "storage.db", ...).
- No logging of SQL parameters or row contents (they will hold transcripts later).
- Export `Database`, `Migration` from `wispr_clone.storage`.

## Tests (Sol; test IDs in function names; `@pytest.mark.asyncio` for async tests)

| ID | Location | Must assert |
|---|---|---|
| T-STO-001 | tests/integration/storage/ | migrations apply in version order (recorded apply order); `user_version` equals the last version; a second `apply_migrations`/`open` is a no-op (no apply call, same version); `discover_migrations()` finds `m001_base` and rejects a duplicate or gap (injected lists) |
| T-STO-002 | tests/integration/storage/ | after `open()`, `PRAGMA journal_mode` is `wal`, `foreign_keys` is 1, `synchronous` is 2 (FULL), read through `db.read` |
| **T-STO-003** (invariant) | tests/integration/storage/ | many `db.write` calls from several concurrent asyncio tasks never overlap (enter/exit markers), all run on ONE thread that is not the loop thread, and a read-modify-write counter ends exactly at N |
| T-STO-004 | tests/integration/storage/ | with an injected test migration creating parent/child tables `ON DELETE CASCADE`, deleting a parent removes its children |
| T-STO-005 | tests/integration/storage/ | an injected migration 2 that creates a table then raises: `WisprError` with `STORAGE_ERROR` and `where == "migration 002"`; `user_version` is 1; the half-created table does not exist; the Database is not open. Also: `write()` whose fn raises rolls back its changes and re-raises the same exception object type (e.g. `sqlite3.IntegrityError`) |
| T-STO-006 | tests/unit/storage/ | `write`/`read` before open and after close raise WisprError(STORAGE_ERROR); `close()` twice is fine; a DB with `user_version` above the known migrations is rejected with "newer schema" |

Probes (Sol boundary; `@pytest.mark.probe("sqlite3")`; they call `sqlite3` directly, no wispr_clone
code), in tests/probes/sqlite/:

- P-SQLITE-001 `sqlite3.sqlite_version` is at least 3.37 (records the value).
- P-SQLITE-002 WAL mode persists: set on a file DB, reopen, still `wal`.
- P-SQLITE-003 inserting a duplicate into a `UNIQUE` column raises `sqlite3.IntegrityError`.
- P-SQLITE-004 `ON DELETE CASCADE` deletes children when `PRAGMA foreign_keys=ON` (and not when OFF).
- Also pin what our runner relies on: `PRAGMA user_version` set inside a transaction is undone by
  ROLLBACK, and DDL inside a transaction is rolled back (can be P-SQLITE-005 in the same folder).

Impact fragment `tests/_attribution/impact/sqlite3.toml` (Sol boundary):
`dependency = "sqlite3"`, `kind = "library"`, `modules = ["storage.db"]` (plus the runner module if
it imports sqlite3), features = settings/dictionary/history persistence, `error_codes =
["storage_error"]`, action = check the SQLite version and disk/permissions, not a wispr_clone fix.

## Reserved plugin change (stdlib dependency support)

Today `check_impact_map_sync` ignores standard-library imports, so a fragment for `sqlite3` would be
reported as "lists storage.db, which does not import it", and a failing `probe("sqlite3")` would
report version "not installed". SQLite is a real third-party C library shipped inside Python, so:

- T-DIAG-009 (Sol, tests/diag/test_stdlib_dependency.py, pytester or direct call):
  (a) a fragment whose `dependency` is a stdlib module name (`sqlite3`) is in sync when its listed
  modules import that module, and out of sync when they do not; (b) stdlib imports WITHOUT a
  fragment are still ignored (no fragment needed for `json`, `asyncio` ...); (c) a failing
  `probe("sqlite3")` reports a version string containing the SQLite library version
  (`sqlite3.sqlite_version`), not "not installed".
- Luna changes only `check_impact_map_sync` and `_dist_version` in tests/_attribution/plugin.py to
  satisfy T-DIAG-009, keeping every existing T-DIAG test green. For other stdlib names the version
  is `"Python <platform.python_version()> stdlib"`.
</content>
