# WO-feat-dictionary-core — Dictionary matching, validation, import/export (pure)

```text
Work-order ID: WO-feat-dictionary-core
Role file / requested model: RED + verify: sol-feature-test-author.md / gpt-6-sol
                             GREEN: luna-core-programmer.md / gpt-6-luna
Pipeline branch or P0/M stage: Wave 1, branch feat/dictionary-core
Outcome and observable acceptance:
  Pure, deterministic dictionary logic: whole-word alias replacement that never touches unrelated
  words, identifiers or paths; entry validation (duplicates, conflicting aliases); a JSON
  import/export format whose import validates the whole input before accepting anything.
  No storage (feat/dictionary-repo adds persistence in wave 2).
Base revision / worktree / branch: f884cf6 / ~/projects/wc-dictionary-core / feat/dictionary-core
Relevant sections: feature spec "Personal dictionary"; CODEMAP.md §3 (dictionary row: "matching
  remains a pure text operation"), §4 step 3 (dictionary-adjusted candidate is separate from the
  immutable original), §5 (dictionary row), §7 G6; dev_pipeline.md §6 Wave 1 row
  feat/dictionary-core.
Prerequisites: P0 merged.
Exact writable paths (under backend_dev/):
  Sol:  tests/unit/dictionary/**
  Luna: src/wispr_clone/dictionary/__init__.py (docstring only), src/wispr_clone/dictionary/apply.py,
        src/wispr_clone/dictionary/import_export.py
Read-only: everything else.
Allowed imports: dictionary -> contracts, config, util + stdlib only (re, unicodedata, json,
  dataclasses). No pydantic here (keeps the pydantic impact fragment untouched).
Required tiers: S, U on ubuntu and windows.
Check commands (from backend_dev/, UV_LINK_MODE=copy):
  uv sync --locked; uv run ruff check .; uv run ruff format --check .;
  uv run mypy src scripts tests/_attribution tests/fakes; uv run python scripts/check_imports.py;
  uv run pytest -q -W error
Authorization: edit only writable paths; no git writes; no PRs; the coordinator commits, pushes,
  opens the PR. No new dependencies.
Privacy: dictionary text is user data. Error `why` strings name entry indexes and rule names only,
  never spellings, aliases or notes. Nothing is logged.
Handoff: coordinator. Sol: RED command/output. Luna: GREEN outputs. Sol: verification findings.
```

## Pinned API (use these exact names)

`wispr_clone.dictionary.apply`:

```python
@dataclass(frozen=True, slots=True)
class DictionaryEntry:
    spelling: str                   # preferred spelling, e.g. "OpenWhispr"
    aliases: tuple[str, ...] = ()   # recognition alternatives, e.g. ("open whisper",)
    note: str = ""

def normalize(text: str) -> str
    # unicodedata.normalize("NFKC", text).casefold(), leading/trailing whitespace stripped,
    # internal whitespace runs collapsed to one space. Used for uniqueness and matching.

def validate_entries(entries: Sequence[DictionaryEntry]) -> None
    # Raises WisprError(ErrorCode.VALIDATION, where="dictionary", why=...) on the FIRST rule broken:
    #   spelling empty after strip, or > 100 chars            -> why "entry <i>: spelling"
    #   an alias empty after strip, or > 100 chars, > 20 aliases -> why "entry <i>: alias"
    #   note > 500 chars                                         -> why "entry <i>: note"
    #   two entries with the same normalized spelling            -> why "entry <j>: duplicate of entry <i>"
    #   a normalized alias (or spelling) of one entry equal to a normalized alias or spelling of
    #   ANOTHER entry                                            -> why "entry <j>: conflicts with entry <i>"
    # An alias equal to its own entry's spelling is allowed (redundant, ignored).

def apply_dictionary(text: str, entries: Sequence[DictionaryEntry]) -> str
    # Calls validate_entries first. Returns a NEW string; never changes `text` or `entries`.
```

Matching rules for `apply_dictionary` (the heart of T-DIC-001..004):

1. Terms: every alias AND the spelling itself of each entry (so "openwhispr" becomes
   "OpenWhispr"). Replacement is always the entry's exact `spelling`.
2. Case-insensitive via `normalize`-equivalent comparison (NFKC + casefold). A single space in a
   term matches one or more whitespace characters in the text.
3. Whole-token only. The character before a match must be the start of the text, whitespace, or
   one of `( [ { " ' “ ‘`. The character after must be the end of the text, whitespace, or one of
   `. , ! ? ; : ) ] } " ' ” ’` — BUT `.`, `,`, `:` and `;` count as a boundary only when followed
   by whitespace or the end of the text (so `config.yaml`, `3.5`, `a:b` stay intact).
   Therefore letters, digits, `_`, `-`, `/`, `\`, `@`, `.` inside a token all block a match:
   "reopen whispers", "open_whisper", "open-whisper", "src/open whisper", "open whisper.py"
   are never changed.
4. Leftmost-longest: scan left to right; at each position take the longest matching term (by
   matched text length); replace it; continue after the match. Replaced text is never rescanned.
   The result does not depend on the order of `entries`.
5. Everything outside matches is copied byte-for-byte (spacing, punctuation, case).

`wispr_clone.dictionary.import_export` (pure; persistence arrives with feat/dictionary-repo):

```python
EXPORT_FORMAT = "wispr-clone-dictionary"
EXPORT_VERSION = 1
MAX_IMPORT_BYTES = 1_000_000
MAX_IMPORT_ENTRIES = 5_000

@dataclass(frozen=True, slots=True)
class ImportPlan:
    to_add: tuple[DictionaryEntry, ...]      # in input order
    skipped_duplicates: tuple[int, ...]      # 0-based input indexes skipped as duplicates

def export_dictionary(entries: Sequence[DictionaryEntry]) -> str
    # JSON text: {"format": EXPORT_FORMAT, "version": 1, "entries": [{"spelling", "aliases", "note"}]}
    # in the given order, ensure_ascii=False, indent=2, trailing newline.

def parse_import(text: str, existing: Sequence[DictionaryEntry]) -> ImportPlan
```

`parse_import` validates EVERYTHING before returning; on any error nothing is accepted
(`WisprError(ErrorCode.VALIDATION, where="dictionary.import", why=...)`, why = rule and index only):

- more than `MAX_IMPORT_BYTES` (UTF-8 length) → why "too large"; invalid JSON → "invalid json";
  wrong `format`/`version` or missing keys → "format"; more than `MAX_IMPORT_ENTRIES` → "too many entries";
- each entry must be an object with exactly `spelling` (str), optional `aliases` (list of str),
  optional `note` (str), no other keys → "entry <i>: shape";
- an entry whose normalized spelling equals an existing entry's spelling, or an earlier entry in
  the same import, is a DUPLICATE: skipped and reported in `skipped_duplicates` (not an error);
- after removing duplicates, `validate_entries(existing + to_add)` must pass (so an imported alias
  that conflicts with an existing entry is an error, reported with the import index).

## Tests (Sol, tests/unit/dictionary/; `@pytest.mark.unit`; IDs in function names)

| ID | Must assert |
|---|---|
| T-DIC-001 | "I pushed to open whisper today" → "I pushed to OpenWhispr today"; "Open  Whisper" (case, double space); at text start/end; before `.`/`,`/`?` + space/end; inside quotes/parentheses; the spelling itself in wrong case is corrected; Korean spelling/alias works (e.g. alias "위스퍼" → "Wispr") |
| **T-DIC-002** (invariant) | no replacement in "reopen whispers", "openwhisperer", "open_whisper", "open-whisper", "src/open whisper", "open whisper.py", "config.yaml" (alias "config"), "3.5" (alias "3") |
| T-DIC-003 | aliases "new york" → "New York" and "new york city" → "NYC": "new york city hall" → "NYC hall", "new york state" → "New York state"; same result for every permutation of the entry list |
| **T-DIC-004** (invariant) | the input string object and every entry are unchanged after `apply_dictionary`; the result differs when a match exists; applying twice equals applying once |
| T-DIC-005 | one invalid entry among valid ones → `VALIDATION`, nothing accepted; duplicates (vs existing and within the file) reported by index and skipped; too large / invalid JSON / wrong format / too many entries rejected; a sentinel string inside a bad entry never appears in `str(error)` or `error.why` |
| T-DIC-006 | `validate_entries`: two entries sharing an alias; an alias equal to another entry's spelling; duplicate normalized spellings (`"OpenWhispr"` vs `"openwhispr"`) → `VALIDATION` with the pinned why wording; alias equal to its own spelling accepted; length limits |
| T-DIC-007 | `parse_import(export_dictionary(entries), [])` returns the same entries in order (Unicode and notes preserved); export is valid JSON with the pinned top-level keys |
