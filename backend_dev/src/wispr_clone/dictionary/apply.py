"""Validation and whole-token dictionary replacement."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Sequence

from wispr_clone.contracts.common import ErrorCode, WisprError


@dataclass(frozen=True, slots=True)
class DictionaryEntry:
    """A preferred spelling and the recognition alternatives that map to it."""

    spelling: str
    aliases: tuple[str, ...] = ()
    note: str = ""


def normalize(text: str) -> str:
    """Normalize text for dictionary comparison."""
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _validation(why: str, where: str = "dictionary") -> WisprError:
    return WisprError(ErrorCode.VALIDATION, where=where, why=why)


def validate_entries(entries: Sequence[DictionaryEntry]) -> None:
    """Validate entry lengths, uniqueness, and cross-entry ambiguity."""
    seen_spellings: dict[str, int] = {}
    seen_terms: dict[str, int] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, DictionaryEntry):
            raise _validation(f"entry {index}: spelling")
        spelling = entry.spelling.strip()
        if not spelling or len(entry.spelling) > 100:
            raise _validation(f"entry {index}: spelling")
        if len(entry.aliases) > 20 or any(
            not alias.strip() or len(alias) > 100 for alias in entry.aliases
        ):
            raise _validation(f"entry {index}: alias")
        if len(entry.note) > 500:
            raise _validation(f"entry {index}: note")
        normalized_spelling = normalize(entry.spelling)
        prior = seen_spellings.get(normalized_spelling)
        if prior is not None:
            raise _validation(f"entry {index}: duplicate of entry {prior}")
        terms = {normalized_spelling, *(normalize(alias) for alias in entry.aliases)}
        for term in terms:
            prior = seen_terms.get(term)
            if prior is not None and prior != index:
                raise _validation(f"entry {index}: conflicts with entry {prior}")
        seen_spellings[normalized_spelling] = index
        for term in terms:
            seen_terms.setdefault(term, index)


_OPEN = frozenset("([{\"'“‘")
_CLOSE = frozenset(".!?,;:) ]}\"'”’".replace(" ", ""))
_CONDITIONAL = frozenset(".,:;")


def _before_ok(text: str, index: int) -> bool:
    return index == 0 or text[index - 1].isspace() or text[index - 1] in _OPEN


def _after_ok(text: str, index: int) -> bool:
    if index == len(text):
        return True
    char = text[index]
    if char.isspace():
        return True
    if char not in _CLOSE:
        return False
    return (
        char not in _CONDITIONAL or index + 1 == len(text) or text[index + 1].isspace()
    )


def _normalized_with_spans(
    text: str,
) -> tuple[str, list[int], list[int], set[int], set[int]]:
    chars: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    cluster_starts: set[int] = set()
    cluster_ends: set[int] = set()
    pending_space: tuple[int, int] | None = None
    source_index = 0
    while source_index < len(text):
        source_char = text[source_index]
        if source_char.isspace():
            if chars and pending_space is None:
                pending_space = (source_index, source_index + 1)
            elif pending_space is not None:
                pending_space = (pending_space[0], source_index + 1)
            source_index += 1
            continue
        if pending_space is not None:
            chars.append(" ")
            starts.append(pending_space[0])
            ends.append(pending_space[1])
            cluster_starts.add(len(chars) - 1)
            cluster_ends.add(len(chars))
            pending_space = None
        cluster_end = source_index + 1
        while cluster_end < len(text) and unicodedata.combining(text[cluster_end]) != 0:
            cluster_end += 1
        cluster_starts.add(len(chars))
        cluster = text[source_index:cluster_end]
        folded = unicodedata.normalize("NFKC", cluster).casefold()
        for char in folded:
            chars.append(char)
            starts.append(source_index)
            ends.append(cluster_end)
        cluster_ends.add(len(chars))
        source_index = cluster_end
    return "".join(chars), starts, ends, cluster_starts, cluster_ends


@dataclass(slots=True)
class _TrieNode:
    children: dict[str, _TrieNode]
    replacement: str | None = None

    def __init__(self) -> None:
        self.children = {}
        self.replacement = None


def apply_dictionary(text: str, entries: Sequence[DictionaryEntry]) -> str:
    """Replace leftmost-longest whole-token matches, preserving other source text."""
    validate_entries(entries)
    trie = _TrieNode()
    for entry in entries:
        for term in (entry.spelling, *entry.aliases):
            normalized = normalize(term)
            node = trie
            for char in normalized:
                node = node.children.setdefault(char, _TrieNode())
            node.replacement = entry.spelling

    folded, starts, ends, cluster_starts, cluster_ends = _normalized_with_spans(text)
    replacements: list[tuple[int, int, str]] = []
    source_cursor = 0
    folded_index = 0
    while folded_index < len(folded):
        source_start = starts[folded_index]
        if (
            folded_index not in cluster_starts
            or source_start < source_cursor
            or not _before_ok(text, source_start)
        ):
            folded_index += 1
            continue
        node = trie
        cursor = folded_index
        best: tuple[int, str, int] | None = None
        while cursor < len(folded) and folded[cursor] in node.children:
            node = node.children[folded[cursor]]
            cursor += 1
            replacement = node.replacement
            if replacement is not None:
                source_end = ends[cursor - 1]
                if cursor in cluster_ends and _after_ok(text, source_end):
                    candidate = (source_end - source_start, replacement, source_end)
                    if best is None or candidate[0] > best[0]:
                        best = candidate
        if best is None:
            folded_index += 1
            continue
        best_end = best[2]
        replacements.append((source_start, best_end, best[1]))
        source_cursor = best_end
        while folded_index < len(folded) and ends[folded_index] <= best_end:
            folded_index += 1
    if not replacements:
        return text
    parts: list[str] = []
    cursor = 0
    for start, end, replacement in replacements:
        parts.extend((text[cursor:start], replacement))
        cursor = end
    parts.append(text[cursor:])
    return "".join(parts)
