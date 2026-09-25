"""Pure JSON import and export for personal dictionary entries."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Sequence

from wispr_clone.contracts.common import ErrorCode, WisprError
from wispr_clone.dictionary.apply import (
    DictionaryEntry,
    normalize,
    validate_entries,
)

EXPORT_FORMAT = "wispr-clone-dictionary"
EXPORT_VERSION = 1
MAX_IMPORT_BYTES = 1_000_000
MAX_IMPORT_ENTRIES = 5_000


@dataclass(frozen=True, slots=True)
class ImportPlan:
    """Validated additions and input indexes skipped as duplicates."""

    to_add: tuple[DictionaryEntry, ...]
    skipped_duplicates: tuple[int, ...]


def _error(why: str) -> WisprError:
    return WisprError(ErrorCode.VALIDATION, "dictionary.import", why)


def export_dictionary(entries: Sequence[DictionaryEntry]) -> str:
    """Serialize entries using the versioned dictionary interchange format."""
    payload = {
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "entries": [
            {
                "spelling": item.spelling,
                "aliases": list(item.aliases),
                "note": item.note,
            }
            for item in entries
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def parse_import(text: str, existing: Sequence[DictionaryEntry]) -> ImportPlan:
    """Validate an entire import document and return its duplicate-filtered plan."""
    if len(text.encode("utf-8")) > MAX_IMPORT_BYTES:
        raise _error("too large")
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, UnicodeError):
        raise _error("invalid json") from None
    if (
        not isinstance(payload, dict)
        or payload.get("format") != EXPORT_FORMAT
        or payload.get("version") != EXPORT_VERSION
        or "entries" not in payload
        or not isinstance(payload["entries"], list)
    ):
        raise _error("format")
    raw_entries = payload["entries"]
    if len(raw_entries) > MAX_IMPORT_ENTRIES:
        raise _error("too many entries")

    parsed: list[DictionaryEntry] = []
    for index, raw in enumerate(raw_entries):
        if (
            not isinstance(raw, dict)
            or set(raw) - {"spelling", "aliases", "note"}
            or "spelling" not in raw
            or not isinstance(raw["spelling"], str)
            or (
                "aliases" in raw
                and (
                    not isinstance(raw["aliases"], list)
                    or any(not isinstance(alias, str) for alias in raw["aliases"])
                )
            )
            or ("note" in raw and not isinstance(raw["note"], str))
        ):
            raise _error(f"entry {index}: shape")
        item = DictionaryEntry(
            raw["spelling"], tuple(raw.get("aliases", [])), raw.get("note", "")
        )
        try:
            validate_entries((item,))
        except WisprError as error:
            rule = error.why.partition(": ")[2]
            raise _error(f"entry {index}: {rule}") from None
        parsed.append(item)

    existing_spelling = {normalize(item.spelling): i for i, item in enumerate(existing)}
    imported_spelling: dict[str, int] = {}
    skipped: list[int] = []
    additions: list[tuple[int, DictionaryEntry]] = []
    for index, item in enumerate(parsed):
        key = normalize(item.spelling)
        if key in existing_spelling or key in imported_spelling:
            skipped.append(index)
            continue
        imported_spelling[key] = index
        additions.append((index, item))

    existing_terms: dict[str, int] = {}
    for index, item in enumerate(existing):
        for term in (item.spelling, *item.aliases):
            existing_terms.setdefault(normalize(term), index)
    imported_terms: dict[str, int] = {}
    for index, item in additions:
        terms = {
            normalize(item.spelling),
            *(normalize(alias) for alias in item.aliases),
        }
        for term in terms:
            if term in existing_terms:
                raise _error(
                    f"entry {index}: conflicts with existing entry "
                    f"{existing_terms[term]}"
                )
            if term in imported_terms:
                raise _error(
                    f"entry {index}: conflicts with entry {imported_terms[term]}"
                )
        for term in terms:
            imported_terms.setdefault(term, index)

    return ImportPlan(tuple(item for _, item in additions), tuple(skipped))
