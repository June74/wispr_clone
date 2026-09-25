"""Conservative lexical checks for obvious meaning changes in cleanup output."""

import re
from collections import Counter
from dataclasses import dataclass

_WORD_RE = re.compile(r"[\w']+", re.UNICODE)
_NUMBER_RE = re.compile(r"\d+(?:[.,:]\d+)*")
_NUMBER_WORDS = frozenset(
    "zero one two three four five six seven eight nine ten eleven twelve "
    "thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty "
    "thirty forty fifty sixty seventy eighty ninety hundred thousand million".split()
)
_NEGATIONS = frozenset(
    {"not", "no", "never", "none", "nothing", "nobody", "nor", "cannot", "without"}
)
_PATH_RE = re.compile(r"(?:[\w.-]*[/\\][\w./\\-]+|\w+\.[A-Za-z0-9]{1,8})")
_IDENTIFIER_RE = re.compile(
    r"(?:\w*_\w+|[a-z][A-Za-z0-9]*[A-Z]\w*|[A-Za-z]+\.[A-Za-z]+)"
)
_TOKEN_RE = re.compile(r"\S+")


@dataclass(frozen=True, slots=True)
class GuardVerdict:
    """Whether output passed lexical checks and the names of failed rules."""

    accepted: bool
    reasons: tuple[str, ...]


def _words(text: str) -> list[str]:
    return [match.group(0).lower() for match in _WORD_RE.finditer(text)]


def _negation(word: str) -> bool:
    return word in _NEGATIONS or word.endswith("n't")


def _sentence_first_word_positions(text: str) -> set[int]:
    starts = {0}
    for match in re.finditer(r"[.!?]\s+", text):
        starts.add(match.end())
    first_words: set[int] = set()
    for match in _WORD_RE.finditer(text):
        if any(
            match.start() >= start and not _WORD_RE.search(text[start : match.start()])
            for start in starts
        ):
            first_words.add(match.start())
    return first_words


def _protected_tokens(text: str, pattern: re.Pattern[str]) -> Counter[str]:
    return Counter(
        match.group(0)
        for token in _TOKEN_RE.findall(text)
        for match in pattern.finditer(token)
    )


def _missing(original: Counter[str], cleaned: Counter[str]) -> bool:
    return any(cleaned[token] < count for token, count in original.items())


def check(original: str, cleaned: str) -> GuardVerdict:
    """Reject loss of protected lexical content or any newly introduced word."""
    reasons: set[str] = set()
    if original.strip() and not cleaned.strip():
        reasons.add("empty")

    original_words = _words(original)
    cleaned_words = _words(cleaned)
    original_negations = Counter(word for word in original_words if _negation(word))
    cleaned_negations = Counter(word for word in cleaned_words if _negation(word))
    if _missing(original_negations, cleaned_negations):
        reasons.add("negation")

    original_numbers = Counter(
        _NUMBER_RE.findall(original) + [w for w in original_words if w in _NUMBER_WORDS]
    )
    cleaned_numbers = Counter(
        _NUMBER_RE.findall(cleaned) + [w for w in cleaned_words if w in _NUMBER_WORDS]
    )
    if _missing(original_numbers, cleaned_numbers):
        reasons.add("number")

    if _missing(
        _protected_tokens(original, _PATH_RE), _protected_tokens(cleaned, _PATH_RE)
    ):
        reasons.add("path")
    if _missing(
        _protected_tokens(original, _IDENTIFIER_RE),
        _protected_tokens(cleaned, _IDENTIFIER_RE),
    ):
        reasons.add("identifier")

    first_positions = _sentence_first_word_positions(original)
    names = Counter(
        match.group(0)
        for match in _WORD_RE.finditer(original)
        if match.start() not in first_positions
        and match.group(0)[:1].isupper()
        and match.group(0)[1:].islower()
    )
    cleaned_names = Counter(
        match.group(0)
        for match in _WORD_RE.finditer(cleaned)
        if match.group(0)[:1].isupper() and match.group(0)[1:].islower()
    )
    if _missing(names, cleaned_names):
        reasons.add("name")

    if _missing(Counter(cleaned_words), Counter(original_words)):
        reasons.add("added")
    ordered = tuple(sorted(reasons))
    return GuardVerdict(not ordered, ordered)
