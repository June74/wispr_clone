"""Direct SQLite contracts; no application code is used here."""

import sqlite3
from pathlib import Path

import pytest


@pytest.mark.probe("sqlite3")
def test_P_SQLITE_001_library_version_is_supported(record_property) -> None:
    version = sqlite3.sqlite_version
    record_property("sqlite_version", version)
    assert sqlite3.sqlite_version_info >= (3, 37, 0), version


@pytest.mark.probe("sqlite3")
def test_P_SQLITE_002_wal_persists_after_reopen(tmp_path: Path) -> None:
    path = tmp_path / "wal.db"
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


@pytest.mark.probe("sqlite3")
def test_P_SQLITE_003_unique_violation_is_integrity_error(tmp_path: Path) -> None:
    with sqlite3.connect(tmp_path / "unique.db") as conn:
        conn.execute("CREATE TABLE sample (value TEXT UNIQUE)")
        conn.execute("INSERT INTO sample VALUES ('synthetic')")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO sample VALUES ('synthetic')")


@pytest.mark.probe("sqlite3")
def test_P_SQLITE_004_foreign_key_cascade_requires_enabled_pragma(
    tmp_path: Path,
) -> None:
    for enabled in (False, True):
        with sqlite3.connect(tmp_path / f"cascade_{enabled}.db") as conn:
            conn.execute(f"PRAGMA foreign_keys={'ON' if enabled else 'OFF'}")
            assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == int(enabled)
            conn.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
            conn.execute(
                "CREATE TABLE child (parent_id INTEGER REFERENCES parent(id) "
                "ON DELETE CASCADE)"
            )
            conn.execute("INSERT INTO parent VALUES (1)")
            conn.execute("INSERT INTO child VALUES (1)")
            conn.execute("DELETE FROM parent WHERE id = 1")
            remaining = conn.execute("SELECT count(*) FROM child").fetchone()[0]
            assert remaining == (0 if enabled else 1)


@pytest.mark.probe("sqlite3")
def test_P_SQLITE_005_transaction_rollback_restores_ddl_and_version(
    tmp_path: Path,
) -> None:
    with sqlite3.connect(tmp_path / "rollback.db", isolation_level=None) as conn:
        conn.execute("PRAGMA user_version = 1")
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("CREATE TABLE transient (value INTEGER)")
        conn.execute("PRAGMA user_version = 2")
        conn.execute("ROLLBACK")
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
        assert (
            conn.execute(
                "SELECT name FROM sqlite_master WHERE name='transient'"
            ).fetchone()
            is None
        )
