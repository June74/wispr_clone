"""Black-box contracts for the failure-attribution pytest plugin (WO-P0.4)."""

import importlib.metadata
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = TESTS_DIR.parent
PLUGIN = TESTS_DIR / "_attribution" / "plugin.py"
CAPTURE_SECRET = "PRIVATE_CAPTURED_TRANSCRIPT_71"
ASSERTION_SECRET = "PRIVATE_ASSERTION_SECOND_LINE_72"


def _suite(pytester: pytest.Pytester) -> Path:
    """Give a disposable suite the production plugin when it exists."""
    pytester.makeini(
        """[pytest]
addopts = --strict-markers
markers =
    probe(dist): isolated dependency probe
    adapter(dist): project adapter
    invariant(text): core invariant
    quarantine(issue, since): temporary quarantine
"""
    )
    pytester.makeconftest(
        "import sys\n"
        f"sys.path.insert(0, {str(TESTS_DIR)!r})\n"
        f"sys.path.insert(0, {str(pytester.path / 'src')!r})\n"
        + ("pytest_plugins = ('_attribution.plugin',)\n" if PLUGIN.is_file() else "")
    )
    return pytester.path / "attribution.json"


def _run(pytester: pytest.Pytester, report: Path, *args: str) -> pytest.RunResult:
    command = ["-q", *args]
    if PLUGIN.is_file():
        command.extend(["--attribution-json", str(report)])
    return pytester.runpytest_subprocess(*command)


def _json(report: Path) -> list[dict[str, object]]:
    assert report.is_file(), "attribution plugin did not write its JSON report"
    data = json.loads(report.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    return data


def _private_text_stays_out(report: Path) -> None:
    serialized = report.read_text(encoding="utf-8")
    assert CAPTURE_SECRET not in serialized
    assert ASSERTION_SECRET not in serialized


def test_T_DIAG_001_fake_failure_is_ours_with_source_frame(
    pytester: pytest.Pytester,
) -> None:
    report = _suite(pytester)
    source = pytester.path / "src" / "wispr_clone" / "diagnostic.py"
    source.parent.mkdir(parents=True)
    source.with_name("__init__.py").write_text("", encoding="utf-8")
    source.write_text(
        f"def fail():\n    assert False, 'safe first line\\n{ASSERTION_SECRET}'\n",
        encoding="utf-8",
    )
    pytester.makepyfile(
        test_case="""
import pytest
from wispr_clone.diagnostic import fail

@pytest.mark.invariant("synthetic invariant")
def test_T_DIAG_001_synthetic_failure():
    print("PRIVATE_CAPTURED_TRANSCRIPT_71")
    fail()
"""
    )
    result = _run(pytester, report, "test_case.py")
    result.assert_outcomes(failed=1)
    output = result.stdout.str()
    assert "[ATTRIBUTION] OURS · logic" in output
    assert re.search(r"diagnostic\.py:\d+.*fail", output)
    assert "synthetic invariant" in output
    rows = _json(report)
    assert len(rows) == 1
    assert rows[0]["verdict"] == "OURS"
    assert rows[0]["category"] == "logic"
    assert "diagnostic.py" in str(rows[0]["where"])
    _private_text_stays_out(report)


def test_T_DIAG_002_failing_probe_reports_dependency_version(
    pytester: pytest.Pytester,
) -> None:
    report = _suite(pytester)
    pytester.makepyfile(
        test_probe="""
import pytest

@pytest.mark.probe("pytest")
def test_P_PYTEST_001_synthetic_probe():
    print("PRIVATE_CAPTURED_TRANSCRIPT_71")
    assert False, "safe first line\\nPRIVATE_ASSERTION_SECOND_LINE_72"

@pytest.mark.adapter("pytest")
def test_T_DIAG_002_adapter_also_fails():
    assert False, "safe first line\\nPRIVATE_ASSERTION_SECOND_LINE_72"
"""
    )
    result = _run(pytester, report, "test_probe.py")
    result.assert_outcomes(failed=2)
    output = result.stdout.str()
    assert output.count("[ATTRIBUTION] NOT OURS · library") == 2
    assert "pytest" in output
    assert importlib.metadata.version("pytest") in output
    rows = _json(report)
    assert len(rows) == 2
    assert all(row["verdict"] == "NOT OURS" for row in rows)
    assert all(row["dist"] == "pytest" for row in rows)
    assert all(row["version"] == importlib.metadata.version("pytest") for row in rows)
    _private_text_stays_out(report)


def test_T_DIAG_003_passed_probe_makes_adapter_failure_ours(
    pytester: pytest.Pytester,
) -> None:
    report = _suite(pytester)
    pytester.makepyfile(
        test_adapter="""
import pytest

@pytest.mark.probe("pytest")
def test_P_PYTEST_002_probe_passes():
    assert True

@pytest.mark.adapter("pytest")
def test_T_DIAG_003_adapter_fails():
    assert False, "safe first line\\nPRIVATE_ASSERTION_SECOND_LINE_72"
"""
    )
    result = _run(pytester, report, "test_adapter.py")
    result.assert_outcomes(passed=1, failed=1)
    output = result.stdout.str()
    assert "[ATTRIBUTION] OURS · adapter-misuse" in output
    assert "probe coverage:" in output
    assert "test_P_PYTEST_002_probe_passes" in output
    rows = _json(report)
    assert len(rows) == 1
    assert rows[0]["category"] == "adapter-misuse"
    assert "test_P_PYTEST_002_probe_passes" in str(rows[0]["probes"])
    _private_text_stays_out(report)


@pytest.mark.parametrize("probe_state", ["skipped", "absent"])
def test_T_DIAG_004_missing_probe_leaves_adapter_undetermined(
    pytester: pytest.Pytester, probe_state: str
) -> None:
    report = _suite(pytester)
    probe = (
        """@pytest.mark.probe("pytest")
@pytest.mark.skip(reason="synthetic runner has no device")
def test_P_PYTEST_003_unavailable():
    assert False
"""
        if probe_state == "skipped"
        else ""
    )
    pytester.makepyfile(
        test_adapter="import pytest\n"
        + probe
        + """
@pytest.mark.adapter("pytest")
def test_T_DIAG_004_adapter_fails():
    assert False, "safe first line\\nPRIVATE_ASSERTION_SECOND_LINE_72"
"""
    )
    result = _run(pytester, report, "test_adapter.py")
    result.assert_outcomes(
        failed=1, **({"skipped": 1} if probe_state == "skipped" else {})
    )
    output = result.stdout.str()
    assert "[ATTRIBUTION] UNDETERMINED" in output
    assert "missing:" in output and "pytest" in output
    assert "decide by:" in output
    rows = _json(report)
    assert len(rows) == 1
    assert rows[0]["verdict"] == "UNDETERMINED"
    assert rows[0]["dist"] == "pytest"
    _private_text_stays_out(report)


def test_T_DIAG_005_each_reproduce_command_selects_one_failure(
    pytester: pytest.Pytester,
) -> None:
    report = _suite(pytester)
    pytester.makepyfile(
        test_two="""
def test_T_DIAG_005_first():
    assert False, "first"

def test_T_DIAG_005_second():
    assert False, "second"
"""
    )
    result = _run(pytester, report, "test_two.py")
    result.assert_outcomes(failed=2)
    output = result.stdout.str()
    commands = re.findall(r"reproduce:\s*(uv run pytest (\S+) -k (\S+))", output)
    assert len(commands) == 2
    assert {name for _, _, name in commands} == {
        "test_T_DIAG_005_first",
        "test_T_DIAG_005_second",
    }
    for _, path, name in commands:
        rerun = pytester.runpytest_subprocess("-q", path, "-k", name)
        rerun.assert_outcomes(failed=1, deselected=1)
    rows = _json(report)
    assert len(rows) == 2
    assert {str(row["nodeid"]).split("::")[-1] for row in rows} == {
        "test_T_DIAG_005_first",
        "test_T_DIAG_005_second",
    }


def test_T_DIAG_006_impact_map_sync_on_temporary_and_real_trees(
    tmp_path: Path,
) -> None:
    from _attribution.plugin import check_impact_map_sync

    source = tmp_path / "src" / "wispr_clone"
    source.mkdir(parents=True)
    module = source / "voice.py"
    module.write_text("import httpx\n", encoding="utf-8")
    impact = tmp_path / "impact"
    impact.mkdir()
    fragment = impact / "httpx.toml"
    fragment.write_text(
        'dependency = "httpx"\nkind = "library"\nmodules = ["voice"]\n'
        'features = ["synthetic dictation"]\nerror_codes = ["stt_unavailable"]\n'
        'action = "inspect synthetic probe"\n',
        encoding="utf-8",
    )
    check_impact_map_sync(source.parent, impact)
    module.write_text("from httpx import Client\n", encoding="utf-8")
    check_impact_map_sync(source.parent, impact)

    fragment.unlink()
    with pytest.raises((AssertionError, ValueError), match="httpx"):
        check_impact_map_sync(source.parent, impact)

    fragment.write_text(
        'dependency = "httpx"\nkind = "library"\nmodules = ["voice"]\n'
        'features = ["synthetic dictation"]\nerror_codes = ["not_a_real_code"]\n'
        'action = "inspect synthetic probe"\n',
        encoding="utf-8",
    )
    with pytest.raises((AssertionError, ValueError), match="not_a_real_code"):
        check_impact_map_sync(source.parent, impact)

    fragment.write_text(
        'dependency = "httpx"\nkind = "library"\nmodules = ["voice"]\n'
        'features = ["synthetic dictation"]\nerror_codes = ["stt_unavailable"]\n'
        'action = "inspect synthetic probe"\n',
        encoding="utf-8",
    )
    module.write_text("import json\n", encoding="utf-8")
    with pytest.raises((AssertionError, ValueError), match="httpx|voice"):
        check_impact_map_sync(source.parent, impact)
    fragment.unlink()
    check_impact_map_sync(source.parent, impact)

    check_impact_map_sync(BACKEND_DIR / "src", TESTS_DIR / "_attribution" / "impact")


def test_T_DIAG_007_quarantine_expiry_and_core_invariant(
    pytester: pytest.Pytester,
) -> None:
    report = _suite(pytester)
    today = datetime.now(timezone.utc).date()
    recent = (today - timedelta(days=7)).isoformat()
    old = (today - timedelta(days=8)).isoformat()
    pytester.makepyfile(
        test_quarantine=f"""
import pytest

@pytest.mark.quarantine(issue="SYN-1", since="{recent}")
def test_T_DIAG_007_recent_quarantine():
    assert False, "known synthetic flake"
"""
    )
    result = _run(pytester, report, "test_quarantine.py", "-rx")
    result.assert_outcomes(xfailed=1)
    assert result.ret == 0
    assert "SYN-1" in result.stdout.str()
    assert _json(report) == []

    invalid_cases = {
        "expired": f'@pytest.mark.quarantine(issue="SYN-2", since="{old}")',
        "missing since": '@pytest.mark.quarantine(issue="SYN-3")',
        "core invariant": (
            '@pytest.mark.invariant("synthetic core rule")\n'
            f'@pytest.mark.quarantine(issue="SYN-4", since="{today.isoformat()}")'
        ),
    }
    for label, marker in invalid_cases.items():
        pytester.makepyfile(
            test_invalid=f"""
import pytest

{marker}
def test_T_DIAG_007_invalid_quarantine():
    assert True
"""
        )
        outcome = pytester.runpytest_subprocess("-q", "test_invalid.py")
        assert outcome.ret != 0, label
        assert "ERROR collecting" in outcome.stdout.str(), label


def test_T_DIAG_probe_first_even_when_collected_after_adapter(
    pytester: pytest.Pytester,
) -> None:
    report = _suite(pytester)
    pytester.makepyfile(
        test_order="""
from pathlib import Path
import pytest

ORDER = Path(__file__).with_name("order.txt")

@pytest.mark.adapter("pytest")
def test_T_DIAG_order_adapter():
    with ORDER.open("a", encoding="utf-8") as stream:
        stream.write("adapter\\n")
    assert False, "safe first line\\nPRIVATE_ASSERTION_SECOND_LINE_72"

@pytest.mark.probe("pytest")
def test_P_PYTEST_004_probe():
    with ORDER.open("a", encoding="utf-8") as stream:
        stream.write("probe\\n")
    assert True
"""
    )
    result = _run(pytester, report, "test_order.py")
    result.assert_outcomes(passed=1, failed=1)
    assert (pytester.path / "order.txt").read_text(encoding="utf-8") == (
        "probe\nadapter\n"
    )
    assert "[ATTRIBUTION] OURS · adapter-misuse" in result.stdout.str()
    rows = _json(report)
    assert len(rows) == 1
    assert rows[0]["category"] == "adapter-misuse"
    _private_text_stays_out(report)
