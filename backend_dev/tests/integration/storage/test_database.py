"""Real-file contracts for the single SQLite writer (WO-feat-storage)."""

import asyncio
import importlib
import sqlite3
import threading
from pathlib import Path

import pytest

from wispr_clone.contracts.common import ErrorCode, WisprError


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

    conn = sqlite3.connect(tmp_path / "ordered.db", isolation_level=None)
    try:
        assert runner.apply_migrations(conn, [migration(1), migration(2)]) == 2
        assert applied == [1, 2]
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
        assert runner.apply_migrations(conn, [migration(1), migration(2)]) == 2
        assert applied == [1, 2]
    finally:
        conn.close()

    discovered = runner.discover_migrations()
    assert [item.version for item in discovered] == [1]

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
                f"VERSION = {version}\ndef apply(conn):\n    pass\n", encoding="utf-8"
            )
        with monkeypatch.context() as scoped:
            scoped.setattr(runner, "__path__", [str(package_dir)])
            importlib.invalidate_caches()
            with pytest.raises(WisprError, match="storage_error") as caught:
                runner.discover_migrations()
            assert caught.value.error_code == ErrorCode.STORAGE_ERROR
            assert caught.value.where == "storage.migrations"


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
    with sqlite3.connect(path) as conn:
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
