"""Pure personal-dictionary behavior from WO-feat-dictionary-core."""

import itertools
import json

import pytest


@pytest.mark.unit
def test_T_DIC_001_replaces_whole_terms_and_preserves_surroundings() -> None:
    from wispr_clone.dictionary.apply import DictionaryEntry, apply_dictionary

    entries = (
        DictionaryEntry("OpenWhispr", ("open whisper",)),
        DictionaryEntry("Wispr", ("위스퍼",)),
    )
    examples = {
        "I pushed to open whisper today": "I pushed to OpenWhispr today",
        "Open  Whisper": "OpenWhispr",
        "OPEN\t\nWHISPER": "OpenWhispr",
        "open whisper": "OpenWhispr",
        "openwhispr": "OpenWhispr",
        "OPENWHISPR": "OpenWhispr",
        "open whisper. Next": "OpenWhispr. Next",
        "open whisper, next": "OpenWhispr, next",
        "open whisper? Next": "OpenWhispr? Next",
        'Say "open whisper" (위스퍼).': 'Say "OpenWhispr" (Wispr).',
        "위스퍼": "Wispr",
    }
    for original, expected in examples.items():
        assert apply_dictionary(original, entries) == expected, original


@pytest.mark.unit
@pytest.mark.invariant("Dictionary matches never alter unrelated tokens")
def test_T_DIC_002_does_not_replace_inside_identifiers_paths_or_numbers() -> None:
    from wispr_clone.dictionary.apply import DictionaryEntry, apply_dictionary

    entries = (
        DictionaryEntry("OpenWhispr", ("open whisper", "openwhisper")),
        DictionaryEntry("Configuration", ("config",)),
        DictionaryEntry("Three", ("3",)),
    )
    text = (
        "reopen whispers | openwhisperer | open_whisper | open-whisper | "
        "src/open whisper | open whisper.py | config.yaml | "
        "config:value | config,name | config;name | 3.5"
    )
    assert apply_dictionary(text, entries) == text


@pytest.mark.unit
def test_T_DIC_003_leftmost_longest_is_independent_of_entry_order() -> None:
    from wispr_clone.dictionary.apply import DictionaryEntry, apply_dictionary

    entries = (
        DictionaryEntry("New York", ("new york",)),
        DictionaryEntry("NYC", ("new york city",)),
    )
    original = "new york city hall; new york state"
    for ordered in itertools.permutations(entries):
        assert apply_dictionary(original, ordered) == "NYC hall; New York state"


@pytest.mark.unit
def test_T_DIC_003_longest_uses_matched_source_span_after_normalization() -> None:
    from wispr_clone.dictionary.apply import DictionaryEntry, apply_dictionary

    # The ligature occupies one source character but normalizes to three letters.
    entries = (
        DictionaryEntry("Short", ("ffi",)),
        DictionaryEntry("Long", ("ffi x",)),
    )
    for ordered in itertools.permutations(entries):
        assert apply_dictionary("ﬃ x; ﬃ", ordered) == "Long; Short"


@pytest.mark.unit
@pytest.mark.invariant("Dictionary adjustment preserves its original input")
def test_T_DIC_004_keeps_original_and_entries_and_is_idempotent() -> None:
    from wispr_clone.dictionary.apply import DictionaryEntry, apply_dictionary

    original = "open whisper and 위스퍼"
    entries = (
        DictionaryEntry("OpenWhispr", ("open whisper",), "synthetic note"),
        DictionaryEntry("Wispr", ("위스퍼",)),
    )
    snapshot = tuple((e.spelling, e.aliases, e.note) for e in entries)
    original_object = original

    adjusted = apply_dictionary(original, entries)

    assert adjusted == "OpenWhispr and Wispr"
    assert adjusted != original
    assert original is original_object
    assert original == "open whisper and 위스퍼"
    assert tuple((e.spelling, e.aliases, e.note) for e in entries) == snapshot
    assert apply_dictionary(adjusted, entries) == adjusted


@pytest.mark.unit
def test_T_DIC_005_import_validates_all_before_returning_and_skips_duplicates() -> None:
    from wispr_clone.dictionary.apply import DictionaryEntry
    from wispr_clone.dictionary.import_export import (
        EXPORT_FORMAT,
        MAX_IMPORT_BYTES,
        MAX_IMPORT_ENTRIES,
        parse_import,
    )

    from wispr_clone.contracts.common import ErrorCode, WisprError

    existing = (DictionaryEntry("Existing"),)

    def document(items: list[object], **changes: object) -> str:
        payload = {"format": EXPORT_FORMAT, "version": 1, "entries": items}
        payload.update(changes)
        return json.dumps(payload, ensure_ascii=False)

    duplicate_plan = parse_import(
        document(
            [
                {"spelling": "existing"},
                {"spelling": "Fresh", "aliases": ["fresh phrase"]},
                {"spelling": "FRESH"},
                {"spelling": "Last"},
            ]
        ),
        existing,
    )
    assert duplicate_plan.skipped_duplicates == (0, 2)
    assert duplicate_plan.to_add == (
        DictionaryEntry("Fresh", ("fresh phrase",)),
        DictionaryEntry("Last"),
    )

    secret = "SYNTHETIC_PRIVATE_ENTRY_SENTINEL"
    invalid_documents = (
        (
            document([{"spelling": "Fresh"}, {"spelling": secret, "note": 3}]),
            "entry 1: shape",
        ),
        (
            document(
                [{"spelling": "Fresh"}, {"spelling": "Bad", "aliases": [secret, ""]}]
            ),
            "entry 1: alias",
        ),
        (
            document([{"spelling": "Fresh", "aliases": ["Existing"]}]),
            "entry 0: conflicts with existing entry 0",
        ),
        (
            document(
                [
                    {"spelling": "First", "aliases": ["shared"]},
                    {"spelling": "Second", "aliases": ["SHARED"]},
                ]
            ),
            "entry 1: conflicts with entry 0",
        ),
        ("{", "invalid json"),
        ("{" + " " * MAX_IMPORT_BYTES, "too large"),
        (document([], format="wrong-format"), "format"),
        (document([], version=2), "format"),
        (json.dumps({"format": EXPORT_FORMAT, "version": 1}), "format"),
        (
            document([{"spelling": f"Term{i}"} for i in range(MAX_IMPORT_ENTRIES + 1)]),
            "too many entries",
        ),
        (
            document([{"spelling": "Fresh", "note": "한" * (MAX_IMPORT_BYTES // 3)}]),
            "too large",
        ),
    )
    for raw, expected_why in invalid_documents:
        with pytest.raises(WisprError) as caught:
            parse_import(raw, existing)
        error = caught.value
        assert error.error_code == ErrorCode.VALIDATION
        assert error.where == "dictionary.import"
        assert error.why == expected_why
        assert secret not in error.why
        assert secret not in str(error)


@pytest.mark.unit
def test_T_DIC_006_validates_conflicts_and_length_limits() -> None:
    from wispr_clone.dictionary.apply import DictionaryEntry, validate_entries

    from wispr_clone.contracts.common import ErrorCode, WisprError

    cases = (
        (
            (
                DictionaryEntry("First", ("shared",)),
                DictionaryEntry("Second", ("SHARED",)),
            ),
            "entry 1: conflicts with entry 0",
        ),
        (
            (DictionaryEntry("First", ("second",)), DictionaryEntry("Second")),
            "entry 1: conflicts with entry 0",
        ),
        (
            (DictionaryEntry("OpenWhispr"), DictionaryEntry("openwhispr")),
            "entry 1: duplicate of entry 0",
        ),
        ((DictionaryEntry(" "),), "entry 0: spelling"),
        ((DictionaryEntry("x" * 101),), "entry 0: spelling"),
        ((DictionaryEntry("Valid", (" ",)),), "entry 0: alias"),
        ((DictionaryEntry("Valid", ("a" * 101,)),), "entry 0: alias"),
        (
            (DictionaryEntry("Valid", tuple(f"alias{i}" for i in range(21))),),
            "entry 0: alias",
        ),
        ((DictionaryEntry("Valid", note="n" * 501),), "entry 0: note"),
    )
    for entries, expected_why in cases:
        with pytest.raises(WisprError) as caught:
            validate_entries(entries)
        error = caught.value
        assert error.error_code == ErrorCode.VALIDATION
        assert error.where == "dictionary"
        assert error.why == expected_why

    validate_entries((DictionaryEntry("OpenWhispr", ("openwhispr",)),))
    validate_entries((DictionaryEntry("x" * 100, ("a" * 100,), "n" * 500),))


@pytest.mark.unit
def test_T_DIC_007_export_import_round_trip_preserves_order_and_unicode() -> None:
    from wispr_clone.dictionary.apply import DictionaryEntry
    from wispr_clone.dictionary.import_export import (
        EXPORT_FORMAT,
        EXPORT_VERSION,
        export_dictionary,
        parse_import,
    )

    entries = (
        DictionaryEntry("Wispr", ("위스퍼",), "한국어 synthetic note"),
        DictionaryEntry("OpenWhispr", ("open whisper",), "synthetic note"),
    )
    exported = export_dictionary(entries)
    payload = json.loads(exported)

    assert exported.endswith("\n")
    assert "위스퍼" in exported
    assert set(payload) == {"format", "version", "entries"}
    assert payload["format"] == EXPORT_FORMAT == "wispr-clone-dictionary"
    assert payload["version"] == EXPORT_VERSION == 1
    assert payload["entries"] == [
        {"spelling": e.spelling, "aliases": list(e.aliases), "note": e.note}
        for e in entries
    ]
    plan = parse_import(exported, [])
    assert plan.to_add == entries
    assert plan.skipped_duplicates == ()
