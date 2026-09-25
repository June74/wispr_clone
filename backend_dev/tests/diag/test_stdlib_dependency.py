"""T-DIAG-009: explicit stdlib dependencies participate in attribution."""

import json
import sqlite3
from pathlib import Path

import pytest
from _attribution.plugin import check_impact_map_sync


def test_T_DIAG_009_explicit_stdlib_fragment_is_checked(tmp_path: Path) -> None:
    source = tmp_path / "src" / "wispr_clone"
    source.mkdir(parents=True)
    module = source / "storage.py"
    module.write_text("import sqlite3\nimport json\n", encoding="utf-8")
    impact = tmp_path / "impact"
    impact.mkdir()
    fragment = impact / "sqlite3.toml"
    fragment.write_text(
        'dependency = "sqlite3"\nkind = "library"\nmodules = ["storage"]\n'
        'features = ["synthetic persistence"]\nerror_codes = ["storage_error"]\n'
        'action = "check synthetic SQLite environment"\n',
        encoding="utf-8",
    )
    check_impact_map_sync(source.parent, impact)
    module.write_text("import json\n", encoding="utf-8")
    with pytest.raises(ValueError, match="sqlite3|storage"):
        check_impact_map_sync(source.parent, impact)
    fragment.unlink()
    check_impact_map_sync(source.parent, impact)


def test_T_DIAG_009_stdlib_import_after_another_import_is_seen(tmp_path: Path) -> None:
    source = tmp_path / "src" / "wispr_clone"
    source.mkdir(parents=True)
    (source / "storage.py").write_text("import json, sqlite3\n", encoding="utf-8")
    impact = tmp_path / "impact"
    impact.mkdir()
    (impact / "sqlite3.toml").write_text(
        'dependency = "sqlite3"\nkind = "library"\nmodules = ["storage"]\n'
        'features = ["synthetic persistence"]\nerror_codes = ["storage_error"]\n'
        'action = "check synthetic SQLite environment"\n',
        encoding="utf-8",
    )
    check_impact_map_sync(source.parent, impact)


def test_T_DIAG_009_stdlib_fragment_lists_every_importing_module(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src" / "wispr_clone"
    source.mkdir(parents=True)
    (source / "storage.py").write_text("import sqlite3\n", encoding="utf-8")
    (source / "history.py").write_text("import sqlite3\n", encoding="utf-8")
    impact = tmp_path / "impact"
    impact.mkdir()
    (impact / "sqlite3.toml").write_text(
        'dependency = "sqlite3"\nkind = "library"\nmodules = ["storage"]\n'
        'features = ["synthetic persistence"]\nerror_codes = ["storage_error"]\n'
        'action = "check synthetic SQLite environment"\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="sqlite3|history"):
        check_impact_map_sync(source.parent, impact)


def test_T_DIAG_009_failing_sqlite_probe_reports_library_version(
    pytester: pytest.Pytester,
) -> None:
    tests_dir = Path(__file__).resolve().parents[1]
    pytester.makeini(
        "[pytest]\naddopts = --strict-markers\n"
        "markers =\n    probe(dist): isolated dependency probe\n"
    )
    pytester.makeconftest(
        "import sys\n"
        f"sys.path.insert(0, {str(tests_dir)!r})\n"
        "pytest_plugins = ('_attribution.plugin',)\n"
    )
    pytester.makepyfile(
        test_sqlite_probe="""
import pytest

@pytest.mark.probe("sqlite3")
def test_P_SQLITE_009_synthetic_failure():
    assert False, "synthetic SQLite probe failure"
"""
    )
    report = pytester.path / "attribution.json"
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setenv("PYTHONUTF8", "1")
        result = pytester.runpytest_subprocess(
            "-q", "test_sqlite_probe.py", "--attribution-json", str(report)
        )
    result.assert_outcomes(failed=1)
    rows = json.loads(report.read_text(encoding="utf-8"))
    assert len(rows) == 1
    assert rows[0]["verdict"] == "NOT OURS"
    assert rows[0]["dist"] == "sqlite3"
    assert sqlite3.sqlite_version in str(rows[0]["version"])
    assert "not installed" not in str(rows[0]["version"])
    assert sqlite3.sqlite_version in result.stdout.str()
