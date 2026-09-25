"""SQLite repository for persistent personal dictionary entries."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from wispr_clone.contracts.common import ErrorCode, WisprError
from wispr_clone.dictionary.apply import (
    DictionaryEntry,
    normalize,
    validate_entries,
)
from wispr_clone.dictionary.import_export import (
    ImportPlan,
    export_dictionary,
    parse_import,
)
from wispr_clone.storage import Connection, Database, IntegrityError


@dataclass(frozen=True, slots=True)
class StoredEntry:
    """A dictionary entry and its persistent identity and timestamps."""

    id: int
    entry: DictionaryEntry
    created_at: float
    updated_at: float


class DictionaryRepo:
    """Load and mutate dictionary rows through serialized database callbacks."""

    def __init__(self, db: Database, *, clock: Callable[[], float]) -> None:
        self._db = db
        self._clock = clock

    async def list_entries(self) -> tuple[StoredEntry, ...]:
        return await self._db.read(_select_entries)

    async def entries(self) -> tuple[DictionaryEntry, ...]:
        return tuple(item.entry for item in await self.list_entries())

    async def add(self, entry: DictionaryEntry) -> StoredEntry:
        def add_row(conn: Connection) -> StoredEntry:
            current = _select_entries(conn)
            _validate_candidate(entry, current, "new entry")
            timestamp = self._clock()
            try:
                cursor = conn.execute(
                    "INSERT INTO dictionary_entries "
                    "(spelling, normalized, aliases, note, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    _values(entry, timestamp, timestamp),
                )
            except IntegrityError:
                raise _validation("new entry: duplicate") from None
            if cursor.lastrowid is None:
                raise WisprError(ErrorCode.STORAGE_ERROR, "dictionary.repo", "insert")
            return StoredEntry(cursor.lastrowid, entry, timestamp, timestamp)

        return await self._db.write(add_row)

    async def update(self, entry_id: int, entry: DictionaryEntry) -> StoredEntry:
        def update_row(conn: Connection) -> StoredEntry:
            current = _select_entries(conn)
            existing = next((item for item in current if item.id == entry_id), None)
            if existing is None:
                raise _validation("not found")
            others = tuple(item for item in current if item.id != entry_id)
            _validate_candidate(entry, others, f"entry id {entry_id}")
            timestamp = self._clock()
            try:
                conn.execute(
                    "UPDATE dictionary_entries SET spelling = ?, normalized = ?, "
                    "aliases = ?, note = ?, updated_at = ? WHERE id = ?",
                    (
                        *_values(entry, existing.created_at, timestamp)[:4],
                        timestamp,
                        entry_id,
                    ),
                )
            except IntegrityError:
                raise _validation(f"entry id {entry_id}: duplicate") from None
            return StoredEntry(entry_id, entry, existing.created_at, timestamp)

        return await self._db.write(update_row)

    async def delete(self, entry_id: int) -> None:
        def delete_row(conn: Connection) -> None:
            cursor = conn.execute(
                "DELETE FROM dictionary_entries WHERE id = ?", (entry_id,)
            )
            if cursor.rowcount == 0:
                raise _validation("not found")

        await self._db.write(delete_row)

    async def import_text(self, text: str) -> ImportPlan:
        def import_rows(conn: Connection) -> ImportPlan:
            current = _select_entries(conn)
            plan = parse_import(text, tuple(item.entry for item in current))
            for entry in plan.to_add:
                timestamp = self._clock()
                conn.execute(
                    "INSERT INTO dictionary_entries "
                    "(spelling, normalized, aliases, note, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    _values(entry, timestamp, timestamp),
                )
            return plan

        return await self._db.write(import_rows)

    async def export_text(self) -> str:
        current = await self.list_entries()
        return export_dictionary(tuple(item.entry for item in current))


def _select_entries(conn: Connection) -> tuple[StoredEntry, ...]:
    rows = conn.execute(
        "SELECT id, spelling, aliases, note, created_at, updated_at "
        "FROM dictionary_entries ORDER BY id"
    ).fetchall()
    return tuple(
        StoredEntry(
            int(row[0]),
            DictionaryEntry(str(row[1]), tuple(json.loads(str(row[2]))), str(row[3])),
            float(row[4]),
            float(row[5]),
        )
        for row in rows
    )


def _values(
    entry: DictionaryEntry, created_at: float, updated_at: float
) -> tuple[str, str, str, str, float, float]:
    return (
        entry.spelling,
        normalize(entry.spelling),
        json.dumps(entry.aliases, ensure_ascii=False),
        entry.note,
        created_at,
        updated_at,
    )


def _validate_candidate(
    entry: DictionaryEntry, existing: Sequence[StoredEntry], prefix: str
) -> None:
    entries = [item.entry for item in existing]
    entries.append(entry)
    try:
        validate_entries(entries)
    except WisprError as error:
        rule = error.why.partition(": ")[2]
        if rule.startswith("duplicate of entry "):
            index = int(rule.rpartition(" ")[2])
            why = f"{prefix}: duplicate of id {existing[index].id}"
        elif rule.startswith("conflicts with entry "):
            index = int(rule.rpartition(" ")[2])
            why = f"{prefix}: conflicts with id {existing[index].id}"
        else:
            why = f"{prefix}: {rule}"
        raise _validation(why) from None


def _validation(why: str) -> WisprError:
    return WisprError(ErrorCode.VALIDATION, "dictionary.repo", why)
