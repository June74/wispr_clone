"""Deletion, orphan cleanup, and schema behavior on real SQLite and WAVs."""

import ast
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from _support import create, database, migrations, repo, wav
from fakes.clock import FakeClock
from fakes.events import FakeEventSink
from fakes.ids import FakeIdFactory

from wispr_clone.contracts.common import ErrorCode, WisprError


@pytest.mark.asyncio
async def test_T_HIS_005_failed_wav_deletion_is_hidden_and_retried(
    tmp_path: Path,
) -> None:
    from wispr_clone.history.repo import HistoryRepo

    clock, events, ids = FakeClock(), FakeEventSink(), FakeIdFactory()
    audio = wav(tmp_path / "run.wav")
    fail = True

    def remove_file(path: Path) -> None:
        if fail:
            raise OSError("synthetic sharing violation")
        path.unlink(missing_ok=True)

    path = tmp_path / "history.db"
    async with database(path) as db:
        history: HistoryRepo = repo(
            db, tmp_path, clock, events, remove_file=remove_file
        )
        run = await create(history, ids, audio_path=str(audio))
        await history.update_run(
            run.id,
            expected_version=1,
            original_text="private original",
            cleaned_text="private clean",
        )
        result = await history.delete_run(run.id)
        assert result.run_ids == (run.id,) and result.audio_pending
        assert await history.list_runs() == () and audio.exists()
        assert (
            await db.read(
                lambda conn: conn.execute("SELECT count(*) FROM runs").fetchone()[0]
            )
            == 0
        )
        assert await db.read(
            lambda conn: conn.execute("SELECT path FROM pending_deletions").fetchall()
        ) == [(str(audio),)]
        with closing(sqlite3.connect(path)) as raw:
            assert (
                raw.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name='pending_deletions'"
                ).fetchone()
                is not None
            )
            assert raw.execute("PRAGMA table_info(pending_deletions)").fetchall() == [
                (0, "path", "TEXT", 0, None, 1)
            ]
        fail = False
        assert await history.retry_pending_deletions() == 0
        assert not audio.exists()
        assert (
            await db.read(
                lambda conn: conn.execute(
                    "SELECT count(*) FROM pending_deletions"
                ).fetchone()[0]
            )
            == 0
        )
        second_audio = wav(tmp_path / "second.wav")
        second = await create(history, ids, audio_path=str(second_audio))
        fail = True
        assert (await history.delete_run(second.id)).audio_pending
    fail = False
    async with database(path) as reopened:
        report = await repo(
            reopened, tmp_path, clock, FakeEventSink(), remove_file=remove_file
        ).recover_on_startup()
        assert report.pending_deletions_left == 0
        assert not second_audio.exists()


@pytest.mark.asyncio
async def test_T_HIS_006_startup_cleans_only_unreferenced_wavs(tmp_path: Path) -> None:
    clock, events, ids = FakeClock(), FakeEventSink(), FakeIdFactory()
    referenced = wav(tmp_path / "referenced.wav")
    orphan = wav(tmp_path / "orphan.wav")
    unrelated = tmp_path / "keep.txt"
    unrelated.write_text("keep", encoding="utf-8")
    async with database(tmp_path / "history.db") as db:
        history = repo(db, tmp_path, clock, events)
        run = await create(history, ids, audio_path=str(referenced))
        report = await history.recover_on_startup()
        assert report.deleted_orphan_wavs == 1
        assert referenced.exists() and not orphan.exists() and unrelated.exists()
        assert (await history.get(run.id)).audio_path == str(referenced)


@pytest.mark.asyncio
@pytest.mark.invariant("deleting a run removes audio, transcripts and attempts")
async def test_T_HIS_012_delete_run_and_all_preserve_other_tables(
    tmp_path: Path,
) -> None:
    clock, events, ids = FakeClock(), FakeEventSink(), FakeIdFactory()
    first_audio, second_audio = (
        wav(tmp_path / "first.wav"),
        wav(tmp_path / "second.wav"),
    )
    async with database(tmp_path / "history.db") as db:
        history = repo(db, tmp_path, clock, events)
        await db.write(
            lambda conn: conn.execute("INSERT INTO settings VALUES ('one', 'keep')")
        )
        await db.write(
            lambda conn: conn.execute(
                "INSERT INTO dictionary_entries VALUES ('one', 'keep')"
            )
        )
        first = await create(history, ids, audio_path=str(first_audio))
        second = await create(history, ids, audio_path=str(second_audio))
        for run in (first, second):
            await history.update_run(
                run.id,
                expected_version=1,
                original_text="original",
                adjusted_text="adjusted",
                cleaned_text="cleaned",
            )
            await history.claim_attempt(
                run.id,
                attempt_id=ids.new("attempt"),
                request_id=ids.new("request"),
                kind="explicit",
            )
        deleted = await history.delete_run(first.id)
        assert deleted.run_ids == (first.id,) and not deleted.audio_pending
        assert not first_audio.exists()
        with pytest.raises(WisprError) as absent:
            await history.get(first.id)
        assert absent.value.error_code == ErrorCode.RUN_NOT_FOUND
        assert (
            await db.read(
                lambda conn: conn.execute(
                    "SELECT count(*) FROM insertion_attempts WHERE run_id = ?",
                    (first.id,),
                ).fetchone()[0]
            )
            == 0
        )
        assert (await history.get(second.id)).cleaned_text == "cleaned"
        all_deleted = await history.delete_all()
        assert all_deleted.run_ids == (second.id,) and not all_deleted.audio_pending
        assert not second_audio.exists() and await history.list_runs() == ()
        assert (
            await db.read(
                lambda conn: conn.execute(
                    "SELECT count(*) FROM insertion_attempts"
                ).fetchone()[0]
            )
            == 0
        )
        assert (
            await db.read(
                lambda conn: conn.execute(
                    "SELECT value FROM settings WHERE id='one'"
                ).fetchone()[0]
            )
            == "keep"
        )
        assert (
            await db.read(
                lambda conn: conn.execute(
                    "SELECT word FROM dictionary_entries WHERE id='one'"
                ).fetchone()[0]
            )
            == "keep"
        )


def test_T_HIS_015_migration_version_and_no_direct_sqlite_import() -> None:
    from wispr_clone.history import repo as history_repo
    from wispr_clone.history import retention
    from wispr_clone.storage.migrations import m004_history

    assert (m004_history.VERSION, m004_history.NAME) == (4, "history")
    assert [migration.version for migration in migrations()] == [1, 2, 3, 4]
    for module in (history_repo, retention, m004_history):
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


@pytest.mark.asyncio
async def test_T_HIS_015_real_dictionary_migration_survives_delete_all(
    tmp_path: Path,
) -> None:
    from wispr_clone.storage import Database, Migration
    from wispr_clone.storage.migrations import m001_base, m003_dictionary, m004_history

    real = [
        Migration(m001_base.VERSION, m001_base.NAME, m001_base.apply),
        Migration(2, "placeholder", lambda conn: None),
        Migration(m003_dictionary.VERSION, m003_dictionary.NAME, m003_dictionary.apply),
        Migration(m004_history.VERSION, m004_history.NAME, m004_history.apply),
    ]
    async with Database(tmp_path / "real_dictionary.db", real) as db:
        names = await db.read(
            lambda conn: {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        )
        assert "dictionary_entries" in names
        await db.write(
            lambda conn: conn.execute(
                "INSERT INTO dictionary_entries "
                "(spelling, normalized, aliases, note, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("PyTest", "pytest", "[]", "synthetic note", 1.0, 1.0),
            )
        )
        history = repo(db, tmp_path, FakeClock(), FakeEventSink())
        await create(history, FakeIdFactory())
        assert len((await history.delete_all()).run_ids) == 1
        assert await db.read(
            lambda conn: conn.execute(
                "SELECT spelling, normalized, aliases, note FROM dictionary_entries"
            ).fetchall()
        ) == [("PyTest", "pytest", "[]", "synthetic note")]


@pytest.mark.asyncio
async def test_T_HIS_005_delete_result_ignores_another_pending_wav(
    tmp_path: Path,
) -> None:
    clock, events, ids = FakeClock(), FakeEventSink(), FakeIdFactory()
    locked = wav(tmp_path / "locked.wav")
    removable = wav(tmp_path / "removable.wav")

    def remove_file(path: Path) -> None:
        if path == locked:
            raise OSError("synthetic sharing violation")
        path.unlink(missing_ok=True)

    async with database(tmp_path / "history.db") as db:
        history = repo(db, tmp_path, clock, events, remove_file=remove_file)
        first = await create(history, ids, audio_path=str(locked))
        second = await create(history, ids, audio_path=str(removable))
        assert (await history.delete_run(first.id)).audio_pending
        result = await history.delete_run(second.id)
        assert result.run_ids == (second.id,)
        assert not result.audio_pending
        assert locked.exists() and not removable.exists()


@pytest.mark.asyncio
async def test_T_HIS_012_unknown_delete_and_empty_delete_all(tmp_path: Path) -> None:
    async with database(tmp_path / "history.db") as db:
        history = repo(db, tmp_path, FakeClock(), FakeEventSink())
        with pytest.raises(WisprError) as unknown:
            await history.delete_run("unknown-run")
        assert unknown.value.error_code == ErrorCode.RUN_NOT_FOUND
        assert unknown.value.where == "history"
        assert unknown.value.why == "run"
        assert (await history.delete_all()).run_ids == ()
