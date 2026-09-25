"""Persistent dictionary contracts for WO-feat-dictionary-repo."""

import ast
import asyncio
import itertools
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from wispr_clone.contracts.common import ErrorCode, WisprError
from wispr_clone.dictionary.apply import DictionaryEntry


def _migrations(*, history: bool = False):
    from wispr_clone.storage.migrations import (
        Connection,
        Migration,
        m001_base,
        m003_dictionary,
    )

    # Migration runner requires contiguous versions. Settings' real migration is
    # owned by another branch, so reserve its number without depending on it.
    def reserved_settings(conn: Connection) -> None:
        pass

    migrations = [
        Migration(m001_base.VERSION, m001_base.NAME, m001_base.apply),
        Migration(2, "reserved_settings", reserved_settings),
        Migration(m003_dictionary.VERSION, m003_dictionary.NAME, m003_dictionary.apply),
    ]
    if history:

        def stand_in_history(conn: Connection) -> None:
            conn.execute("CREATE TABLE runs (id TEXT PRIMARY KEY)")
            conn.execute(
                "CREATE TABLE insertion_attempts ("
                "id INTEGER PRIMARY KEY, run_id TEXT NOT NULL "
                "REFERENCES runs(id) ON DELETE CASCADE)"
            )

        migrations.append(Migration(4, "stand_in_history", stand_in_history))
    return migrations


def _rows(path: Path) -> list[tuple[object, ...]]:
    with closing(sqlite3.connect(path)) as conn:
        return conn.execute("SELECT * FROM dictionary_entries ORDER BY id").fetchall()


def _document(entries: list[dict[str, object]]) -> str:
    return json.dumps(
        {"format": "wispr-clone-dictionary", "version": 1, "entries": entries},
        ensure_ascii=False,
    )


def _assert_error(error: WisprError, where: str, why: str) -> None:
    assert error.error_code == ErrorCode.VALIDATION
    assert error.where == where
    assert error.why == why


@pytest.mark.asyncio
@pytest.mark.integration
async def test_T_DIC_010_crud_reopen_and_plain_entries(tmp_path: Path) -> None:
    from wispr_clone.dictionary.repo import DictionaryRepo

    from wispr_clone.storage import Database

    path = tmp_path / "dictionary.db"
    clock = itertools.count(1000.0)
    first = DictionaryEntry("OpenWhispr", ("open whisper",), "first note")
    korean = DictionaryEntry("위스퍼", ("wispr Korean",), "한국어 메모")
    revised = DictionaryEntry("OpenWhispr", ("open whispr",), "revised note")
    async with Database(path, _migrations()) as db:
        repo = DictionaryRepo(db, clock=lambda: next(clock))
        one = await repo.add(first)
        two = await repo.add(korean)
        assert (one.id, one.entry, one.created_at, one.updated_at) == (
            1,
            first,
            1000.0,
            1000.0,
        )
        assert (two.id, two.entry, two.created_at, two.updated_at) == (
            2,
            korean,
            1001.0,
            1001.0,
        )
        assert await repo.list_entries() == (one, two)
        assert await repo.entries() == (first, korean)
        changed = await repo.update(one.id, revised)
        assert (changed.id, changed.entry, changed.created_at, changed.updated_at) == (
            one.id,
            revised,
            1000.0,
            1002.0,
        )
        assert await repo.list_entries() == (changed, two)
        await repo.delete(one.id)
        assert await repo.entries() == (korean,)
        for operation in (
            repo.update(999, revised),
            repo.delete(999),
        ):
            with pytest.raises(WisprError) as caught:
                await operation
            _assert_error(caught.value, "dictionary.repo", "not found")

    async with Database(path, _migrations()) as reopened:
        repo = DictionaryRepo(reopened, clock=lambda: next(clock))
        assert await repo.list_entries() == (two,)
        assert await repo.entries() == (korean,)
        three = await repo.add(DictionaryEntry("Third"))
        assert three.id > two.id
        assert await repo.entries() == (korean, DictionaryEntry("Third"))


@pytest.mark.asyncio
@pytest.mark.integration
async def test_T_DIC_011_conflict_ids_and_failed_mutations(tmp_path: Path) -> None:
    from wispr_clone.dictionary.repo import DictionaryRepo

    from wispr_clone.storage import Database

    path = tmp_path / "conflicts.db"
    sentinel = "SYNTHETIC_PRIVATE_ENTRY_SENTINEL"
    async with Database(path, _migrations()) as db:
        repo = DictionaryRepo(db, clock=lambda: 42.0)
        first = await repo.add(DictionaryEntry("OpenWhispr", ("open whisper",)))
        second = await repo.add(DictionaryEntry("Elsewhere", ("other name",)))
        before = _rows(path)
        cases = (
            (
                DictionaryEntry("openwhispr", note=sentinel),
                f"new entry: duplicate of id {first.id}",
            ),
            (
                DictionaryEntry("New", ("OPEN WHISPER",), sentinel),
                f"new entry: conflicts with id {first.id}",
            ),
            (
                DictionaryEntry("other name", note=sentinel),
                f"new entry: conflicts with id {second.id}",
            ),
            (DictionaryEntry("Bad", ("",), sentinel), "new entry: alias"),
        )
        for entry, why in cases:
            with pytest.raises(WisprError) as caught:
                await repo.add(entry)
            _assert_error(caught.value, "dictionary.repo", why)
            assert sentinel not in caught.value.why
            assert sentinel not in str(caught.value)
            assert _rows(path) == before

        kept = await repo.update(
            first.id, DictionaryEntry("OpenWhispr", ("open whisper",), "edited")
        )
        assert kept.entry.note == "edited"
        before = _rows(path)
        with pytest.raises(WisprError) as caught:
            await repo.update(
                second.id, DictionaryEntry("Elsewhere", ("open whisper",), sentinel)
            )
        _assert_error(
            caught.value,
            "dictionary.repo",
            f"entry id {second.id}: conflicts with id {first.id}",
        )
        assert sentinel not in caught.value.why
        assert _rows(path) == before


@pytest.mark.asyncio
@pytest.mark.integration
async def test_T_DIC_012_import_atomicity_duplicates_and_export(tmp_path: Path) -> None:
    from wispr_clone.dictionary.repo import DictionaryRepo

    from wispr_clone.storage import Database

    path = tmp_path / "import.db"
    async with Database(path, _migrations()) as db:
        repo = DictionaryRepo(db, clock=itertools.count(1000.0).__next__)
        original = DictionaryEntry("Existing", ("known alias",), "note")
        await repo.add(original)
        before = _rows(path)
        invalid = (
            (
                _document([{"spelling": "Valid"}, {"spelling": "Invalid", "note": 3}]),
                "entry 1: shape",
            ),
            (
                _document(
                    [
                        {"spelling": "Valid"},
                        {"spelling": "Other", "aliases": ["KNOWN ALIAS"]},
                    ]
                ),
                "entry 1: conflicts with existing entry 0",
            ),
            ("{", "invalid json"),
        )
        for raw, why in invalid:
            with pytest.raises(WisprError) as caught:
                await repo.import_text(raw)
            _assert_error(caught.value, "dictionary.import", why)
            assert _rows(path) == before

        added = DictionaryEntry("신규", ("new term",), "한국어 메모")
        last = DictionaryEntry("Last", (), "end")
        plan = await repo.import_text(
            _document(
                [
                    {"spelling": "existing"},
                    {
                        "spelling": added.spelling,
                        "aliases": list(added.aliases),
                        "note": added.note,
                    },
                    {"spelling": "신규"},
                    {"spelling": last.spelling, "note": last.note},
                ]
            )
        )
        assert plan.to_add == (added, last)
        assert plan.skipped_duplicates == (0, 2)
        assert await repo.entries() == (original, added, last)
        exported = await repo.export_text()

    async with Database(tmp_path / "fresh.db", _migrations()) as fresh_db:
        fresh = DictionaryRepo(fresh_db, clock=lambda: 9000.0)
        imported = await fresh.import_text(exported)
        assert imported.to_add == (original, added, last)
        assert imported.skipped_duplicates == ()
        assert await fresh.entries() == (original, added, last)
        assert await fresh.export_text() == exported


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.invariant("History deletion never removes personal dictionary rows")
async def test_T_DIC_013_dictionary_survives_history_deletion(tmp_path: Path) -> None:
    from wispr_clone.dictionary.repo import DictionaryRepo

    from wispr_clone.storage import Database

    path = tmp_path / "history.db"
    async with Database(path, _migrations(history=True)) as db:
        repo = DictionaryRepo(db, clock=lambda: 1000.0)
        await repo.add(DictionaryEntry("Persistent", ("keep me",), "note"))
        before = _rows(path)
        await db.write(
            lambda conn: conn.execute("INSERT INTO runs VALUES ('temporary')")
        )
        await db.write(
            lambda conn: conn.execute(
                "INSERT INTO insertion_attempts VALUES (1, 'temporary')"
            )
        )
        await db.write(lambda conn: conn.execute("DELETE FROM runs"))
        assert (
            await db.read(
                lambda conn: conn.execute(
                    "SELECT count(*) FROM insertion_attempts"
                ).fetchone()[0]
            )
            == 0
        )
        await db.write(lambda conn: conn.execute("DROP TABLE insertion_attempts"))
        await db.write(lambda conn: conn.execute("DROP TABLE runs"))
        assert _rows(path) == before
        assert await repo.entries() == (
            DictionaryEntry("Persistent", ("keep me",), "note"),
        )
    assert _rows(path) == before


@pytest.mark.asyncio
@pytest.mark.integration
async def test_T_DIC_014_migration_import_boundary_and_raced_duplicate(
    tmp_path: Path,
) -> None:
    from wispr_clone.dictionary import repo as repo_module
    from wispr_clone.storage import Database
    from wispr_clone.storage.migrations import m003_dictionary

    assert (m003_dictionary.VERSION, m003_dictionary.NAME) == (3, "dictionary")
    for module in (repo_module, m003_dictionary):
        path = Path(module.__file__)
        syntax = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(syntax):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            assert all(name.split(".")[0] != "sqlite3" for name in names)

    path = tmp_path / "race.db"
    async with Database(path, _migrations()) as db:
        dictionary = repo_module.DictionaryRepo(
            db, clock=itertools.count(1000.0).__next__
        )
        results = await asyncio.gather(
            dictionary.add(DictionaryEntry("OpenWhispr")),
            dictionary.add(DictionaryEntry("openwhispr")),
            return_exceptions=True,
        )
        successes = [
            item for item in results if isinstance(item, repo_module.StoredEntry)
        ]
        errors = [item for item in results if isinstance(item, WisprError)]
        assert len(successes) == len(errors) == 1
        assert errors[0].error_code == ErrorCode.VALIDATION
        assert errors[0].where == "dictionary.repo"
        assert errors[0].why in ("new entry: duplicate of id 1", "new entry: duplicate")
        assert len(_rows(path)) == 1
        assert len(await dictionary.list_entries()) == 1
