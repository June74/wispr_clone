"""Handlers for personal dictionary commands."""

from __future__ import annotations

from collections.abc import Mapping

from wispr_clone.application.api import CommandSpec
from wispr_clone.contracts.common import ErrorCode, WisprError
from wispr_clone.dictionary.apply import DictionaryEntry
from wispr_clone.dictionary.repo import DictionaryRepo, StoredEntry


class DictionaryCommands:
    """Expose dictionary repository operations through the command API."""

    def __init__(self, repo: DictionaryRepo) -> None:
        self._repo = repo

    def specs(self) -> dict[str, CommandSpec]:
        return {
            "dict_list": CommandSpec(self._list, mutating=False),
            "dict_add": CommandSpec(self._add, mutating=True),
            "dict_update": CommandSpec(self._update, mutating=True),
            "dict_delete": CommandSpec(self._delete, mutating=True),
            "dict_import": CommandSpec(self._import, mutating=True),
            "dict_export": CommandSpec(self._export, mutating=False),
        }

    async def _list(self, _: Mapping[str, object]) -> Mapping[str, object]:
        entries = await self._repo.list_entries()
        return {"entries": [_entry_json(item) for item in entries]}

    async def _add(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        return _entry_json(await self._repo.add(_parse_entry(payload.get("entry"))))

    async def _update(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        entry_id = _required_id(payload, "id")
        entry = await self._repo.update(entry_id, _parse_entry(payload.get("entry")))
        return _entry_json(entry)

    async def _delete(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        await self._repo.delete(_required_id(payload, "id"))
        return {}

    async def _import(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        text = payload.get("text")
        if not isinstance(text, str):
            raise _validation("text")
        plan = await self._repo.import_text(text)
        return {
            "added": len(plan.to_add),
            "skipped_duplicates": list(plan.skipped_duplicates),
        }

    async def _export(self, _: Mapping[str, object]) -> Mapping[str, object]:
        return {"text": await self._repo.export_text()}


def _entry_json(item: StoredEntry) -> dict[str, object]:
    return {
        "id": item.id,
        "spelling": item.entry.spelling,
        "aliases": list(item.entry.aliases),
        "note": item.entry.note,
    }


def _required_id(payload: Mapping[str, object], name: str) -> int:
    value = payload.get(name)
    if type(value) is not int:
        raise _validation(name)
    return value


def _parse_entry(value: object) -> DictionaryEntry:
    if not isinstance(value, dict) or set(value) - {"spelling", "aliases", "note"}:
        raise _validation("entry")
    spelling = value.get("spelling")
    aliases = value.get("aliases", [])
    note = value.get("note", "")
    if (
        not isinstance(spelling, str)
        or not isinstance(aliases, list)
        or any(not isinstance(alias, str) for alias in aliases)
        or not isinstance(note, str)
    ):
        raise _validation("entry")
    return DictionaryEntry(spelling, tuple(aliases), note)


def _validation(field: str) -> WisprError:
    return WisprError(ErrorCode.VALIDATION, "dictionary.command", field)
