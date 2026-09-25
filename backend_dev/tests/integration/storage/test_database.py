"""Real-file contracts for the single SQLite writer (WO-feat-storage)."""

import ast
import asyncio
import importlib
import sqlite3
import threading
from contextlib import closing
from pathlib import Path
from typing import get_type_hints

import pytest

from wispr_clone.contracts.common import ErrorCode, WisprError


def test_T_STO_001_migrations_export_connection_type() -> None:
    from wispr_clone.storage import migrations

    assert migrations.Connection is sqlite3.Connection


def test_T_STO_001_migration_modules_do_not_import_sqlite3() -> None:
    from wispr_clone.storage import migrations

    migration_files = sorted(Path(migrations.__file__).parent.glob("m*.py"))
    assert migration_files
    for path in migration_files:
        syntax = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports = (
            node
            for node in ast.walk(syntax)
            if isinstance(node, (ast.Import, ast.ImportFrom))
        )
        for node in imports:
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            else:
                names = [node.module or ""]
            assert all(name.split(".")[0] != "sqlite3" for name in names), path


def test_T_STO_001_base_migration_uses_connection_type() -> None:
    from wispr_clone.storage.migrations import m001_base

    assert get_type_hints(m001_base.apply)["conn"] is sqlite3.Connection


def test_T_STO_001_order_discovery_and_idempotent_migrations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from wispr_clone.storage import Migration
    from wispr_clone.storage import migrations as runner

    applied: list[int] = []

    def migration(version: int) -> Migration:
        def apply(conn: sqlite3.Connection) -> None:
            applied.append(version)
            conn.execute(f"CREATE TABLE migration_{version} (id INTEGER)")

        return Migration(version, f"test_{version}", apply)

    with closing(
        sqlite3.connect(tmp_path / "ordered.db", isolation_level=None)
    ) as conn:
        assert runner.apply_migrations(conn, [migration(1), migration(2)]) == 2
        assert applied == [1, 2]
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
        assert runner.apply_migrations(conn, [migration(1), migration(2)]) == 2
        assert applied == [1, 2]

    discovered = runner.discover_migrations()
    assert [item.version for item in discovered] == [1]
    assert [item.name for item in discovered] == ["base"]

    # Use disposable migration modules to exercise discovery without altering source.
    for case, filenames in [
        ("duplicate", ["m001_one.py", "m001_two.py"]),
        ("gap", ["m001_one.py", "m003_gap.py"]),
    ]:
        package_dir = tmp_path / case
        package_dir.mkdir()
        for filename in filenames:
            version = int(filename[1:4])
            (package_dir / filename).write_text(
                f"VERSION = {version}\nNAME = {filename!r}\n"
                "def apply(conn):\n    pass\n",
                encoding="utf-8",
            )
        with monkeypatch.context() as scoped:
            scoped.setattr(runner, "__path__", [str(package_dir)])
            importlib.invalidate_caches()
            with pytest.raises(WisprError, match="storage_error") as caught:
                runner.discover_migrations()
            assert caught.value.error_code == ErrorCode.STORAGE_ERROR
            assert caught.value.where == "storage.migrations"
            assert caught.value.why == (
                "duplicate version" if case == "duplicate" else "missing version"
            )


@pytest.mark.asyncio
async def test_T_STO_002_open_sets_sqlite_pragmas(tmp_path: Path) -> None:
    from wispr_clone.storage import Database

    async with Database(tmp_path / "pragmas.db") as db:
        pragmas = await db.read(
            lambda conn: tuple(
                conn.execute(f"PRAGMA {name}").fetchone()[0]
                for name in ("journal_mode", "foreign_keys", "synchronous")
            )
        )
    assert pragmas == ("wal", 1, 2)


@pytest.mark.asyncio
@pytest.mark.invariant("one SQLite writer thread serializes every write")
async def test_T_STO_003_concurrent_writes_are_serial_on_one_thread(
    tmp_path: Path,
) -> None:
    from wispr_clone.storage import Database

    loop_thread = threading.get_ident()
    thread_ids: set[int] = set()
    markers: list[str] = []
    count = 48
    async with Database(tmp_path / "counter.db") as db:
        await db.write(
            lambda conn: conn.execute("CREATE TABLE counter (value INTEGER)")
        )
        await db.write(lambda conn: conn.execute("INSERT INTO counter VALUES (0)"))

        def increment(conn: sqlite3.Connection) -> None:
            thread_ids.add(threading.get_ident())
            markers.append("enter")
            value = conn.execute("SELECT value FROM counter").fetchone()[0]
            conn.execute("UPDATE counter SET value = ?", (value + 1,))
            markers.append("exit")

        async def submit_batch(size: int) -> None:
            await asyncio.gather(*(db.write(increment) for _ in range(size)))

        await asyncio.gather(*(submit_batch(12) for _ in range(4)))
        final = await db.read(
            lambda conn: conn.execute("SELECT value FROM counter").fetchone()[0]
        )
    assert final == count
    assert markers == [marker for _ in range(count) for marker in ("enter", "exit")]
    assert len(thread_ids) == 1
    assert loop_thread not in thread_ids


@pytest.mark.asyncio
async def test_T_STO_003_write_returns_inserted_row_id(tmp_path: Path) -> None:
    from wispr_clone.storage import Database

    async with Database(tmp_path / "return_row_id.db") as db:
        await db.write(
            lambda conn: conn.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")
        )

        def insert(conn: sqlite3.Connection) -> int:
            return conn.execute("INSERT INTO sample DEFAULT VALUES").lastrowid

        row_id = await db.write(insert)
        persisted_ids = await db.read(
            lambda conn: [row[0] for row in conn.execute("SELECT id FROM sample")]
        )

    assert row_id == 1
    assert persisted_ids == [row_id]


@pytest.mark.asyncio
async def test_T_STO_005_write_returns_callback_tuple(tmp_path: Path) -> None:
    from wispr_clone.storage import Database

    result = ("claim", 7)
    async with Database(tmp_path / "return_tuple.db") as db:
        returned = await db.write(lambda conn: result)

    assert returned is result


@pytest.mark.asyncio
async def test_T_STO_004_foreign_key_cascade(tmp_path: Path) -> None:
    from wispr_clone.storage import Database, Migration

    def tables(conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
        conn.execute(
            "CREATE TABLE child (id INTEGER PRIMARY KEY, parent_id INTEGER "
            "REFERENCES parent(id) ON DELETE CASCADE)"
        )

    async with Database(
        tmp_path / "cascade.db", [Migration(1, "tables", tables)]
    ) as db:
        await db.write(lambda conn: conn.execute("INSERT INTO parent VALUES (1)"))
        await db.write(lambda conn: conn.execute("INSERT INTO child VALUES (1, 1)"))
        await db.write(lambda conn: conn.execute("DELETE FROM parent WHERE id = 1"))
        children = await db.read(
            lambda conn: conn.execute("SELECT count(*) FROM child").fetchone()[0]
        )
    assert children == 0


@pytest.mark.asyncio
async def test_T_STO_005_migration_and_write_failures_rollback(tmp_path: Path) -> None:
    from wispr_clone.storage import Database, Migration

    def first(conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE durable (value INTEGER UNIQUE)")

    def broken(conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE half_created (value INTEGER)")
        raise RuntimeError("synthetic migration failure")

    path = tmp_path / "rollback.db"
    db = Database(path, [Migration(1, "first", first), Migration(2, "broken", broken)])
    with pytest.raises(WisprError) as caught:
        await db.open()
    assert caught.value.error_code == ErrorCode.STORAGE_ERROR
    assert caught.value.where == "migration 002"
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
        assert (
            conn.execute(
                "SELECT name FROM sqlite_master WHERE name = 'half_created'"
            ).fetchone()
            is None
        )
    with pytest.raises(WisprError):
        await db.read(lambda conn: None)
    await db.close()

    async with Database(path, [Migration(1, "first", first)]) as working:
        error = sqlite3.IntegrityError("synthetic constraint failure")

        def failed_write(conn: sqlite3.Connection) -> None:
            conn.execute("INSERT INTO durable VALUES (7)")
            raise error

        with pytest.raises(sqlite3.IntegrityError) as reraised:
            await working.write(failed_write)
        assert reraised.value is error
        assert (
            await working.read(
                lambda conn: conn.execute("SELECT count(*) FROM durable").fetchone()[0]
            )
            == 0
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("early_end", ["executescript", "commit"])
async def test_T_STO_005_migration_rejects_ended_transaction(
    tmp_path: Path, early_end: str
) -> None:
    from wispr_clone.storage import Database, Migration

    def first(conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE durable (value INTEGER)")

    def broken(conn: sqlite3.Connection) -> None:
        if early_end == "executescript":
            conn.executescript("CREATE TABLE escaped (value INTEGER);")
        else:
            conn.execute("CREATE TABLE escaped (value INTEGER)")
            conn.commit()

    path = tmp_path / f"migration_{early_end}.db"
    db = Database(path, [Migration(1, "first", first), Migration(2, "broken", broken)])
    try:
        with pytest.raises(WisprError) as caught:
            await db.open()
        assert caught.value.error_code == ErrorCode.STORAGE_ERROR
        assert caught.value.where == "migration 002"
        assert caught.value.why == "transaction ended early"
        with closing(sqlite3.connect(path)) as conn:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
        with pytest.raises(WisprError):
            await db.read(lambda conn: None)
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_T_STO_005_write_rejects_callback_commit(tmp_path: Path) -> None:
    from wispr_clone.storage import Database

    async with Database(tmp_path / "callback_commit.db") as db:
        await db.write(lambda conn: conn.execute("CREATE TABLE sample (value INTEGER)"))

        def premature_commit(conn: sqlite3.Connection) -> None:
            conn.execute("INSERT INTO sample VALUES (1)")
            conn.commit()

        with pytest.raises(WisprError) as caught:
            await db.write(premature_commit)
        assert caught.value.error_code == ErrorCode.STORAGE_ERROR
        assert caught.value.where == "storage.db"
        assert caught.value.why == "transaction ended early"


@pytest.mark.asyncio
async def test_T_STO_003_close_drains_accepted_queued_write(tmp_path: Path) -> None:
    from wispr_clone.storage import Database

    db = Database(tmp_path / "close_queue.db")
    await db.open()
    await db.write(lambda conn: conn.execute("CREATE TABLE sample (value INTEGER)"))
    entered = threading.Event()
    release = threading.Event()

    def blocking_write(conn: sqlite3.Connection) -> None:
        entered.set()
        assert release.wait(timeout=5)
        conn.execute("INSERT INTO sample VALUES (1)")

    first = asyncio.create_task(db.write(blocking_write))
    try:
        assert await asyncio.to_thread(entered.wait, 5)

        def queued_write(conn: sqlite3.Connection) -> None:
            conn.execute("INSERT INTO sample VALUES (2)")

        queued = asyncio.create_task(db.write(queued_write))
        await asyncio.sleep(0)  # submit the write to the single-thread executor
        assert not queued.done()
        closing_task = asyncio.create_task(db.close())
        await asyncio.sleep(0)  # let close() mark the database closed
        release.set()
        results = await asyncio.gather(
            first, queued, closing_task, return_exceptions=True
        )
        assert results == [None, None, None]
        with closing(sqlite3.connect(tmp_path / "close_queue.db")) as conn:
            assert conn.execute(
                "SELECT value FROM sample ORDER BY value"
            ).fetchall() == [
                (1,),
                (2,),
            ]
    finally:
        release.set()
        await db.close()


@pytest.mark.asyncio
async def test_T_STO_005_schema_version_tracks_prior_commits_after_failure(
    tmp_path: Path,
) -> None:
    from wispr_clone.storage import Database, Migration

    def first(conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE durable (value INTEGER)")

    def broken(conn: sqlite3.Connection) -> None:
        raise RuntimeError("synthetic migration failure")

    path = tmp_path / "version_after_failure.db"
    db = Database(path, [Migration(1, "first", first), Migration(2, "broken", broken)])
    try:
        with pytest.raises(WisprError):
            await db.open()
        with closing(sqlite3.connect(path)) as conn:
            durable_version = conn.execute("PRAGMA user_version").fetchone()[0]
        assert durable_version == 1
        assert db.schema_version == durable_version
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_T_STO_005_failed_commit_rolls_back_and_preserves_error(
    tmp_path: Path,
) -> None:
    from wispr_clone.storage import Database

    async with Database(tmp_path / "failed_commit.db") as db:
        await db.write(
            lambda conn: conn.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
        )
        await db.write(
            lambda conn: conn.execute(
                "CREATE TABLE child (parent_id INTEGER REFERENCES parent(id) "
                "DEFERRABLE INITIALLY DEFERRED)"
            )
        )
        with pytest.raises(sqlite3.IntegrityError):
            await db.write(lambda conn: conn.execute("INSERT INTO child VALUES (99)"))
        assert (
            await db.read(
                lambda conn: conn.execute("SELECT count(*) FROM child").fetchone()[0]
            )
            == 0
        )
        await db.write(lambda conn: conn.execute("INSERT INTO parent VALUES (99)"))


@pytest.mark.asyncio
async def test_T_STO_005_open_migration_failure_stops_writer_thread(
    tmp_path: Path,
) -> None:
    from wispr_clone.storage import Database, Migration

    writer_ident: list[int] = []

    def broken(conn: sqlite3.Connection) -> None:
        writer_ident.append(threading.get_ident())
        raise RuntimeError("synthetic migration failure")

    db = Database(tmp_path / "failed_open.db", [Migration(1, "broken", broken)])
    with pytest.raises(WisprError):
        await db.open()
    assert len(writer_ident) == 1
    assert not any(thread.ident == writer_ident[0] for thread in threading.enumerate())
    await db.close()
