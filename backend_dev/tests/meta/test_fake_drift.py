"""T-DIAG-008: attribution compares the same conformance case in one run."""

import json
from pathlib import Path

import pytest


def test_T_DIAG_008_real_failure_fake_pass_and_probe_pass_is_fake_drift(
    pytester: pytest.Pytester,
) -> None:
    tests_dir = Path(__file__).resolve().parents[1]
    report = pytester.path / "attribution.json"
    pytester.makeini(
        """[pytest]
addopts = --strict-markers
markers =
    probe(dist): isolated dependency probe
    adapter(dist): project adapter
    conformance: shared adapter cases
"""
    )
    pytester.makeconftest(
        "import sys\n"
        f"sys.path.insert(0, {str(tests_dir)!r})\n"
        f"sys.path.insert(0, {str(pytester.path / 'tests')!r})\n"
        "pytest_plugins = ('_attribution.plugin',)\n"
    )
    fake_dir = pytester.path / "tests" / "fakes"
    fake_dir.mkdir(parents=True)
    (fake_dir / "__init__.py").write_text("", encoding="utf-8")
    (fake_dir / "sample.py").write_text(
        "def make_fake():\n    return 'expected'\n", encoding="utf-8"
    )
    pytester.makepyfile(
        sample_real="def make_real():\n    return 'wrong-real-result'\n"
    )
    pytester.makepyfile(
        test_conformance="""
import pytest
from conformance.harness import implementation_params
from fakes.sample import make_fake

@pytest.mark.probe("pytest")
def test_P_PYTEST_008_probe_passes():
    assert True

@pytest.mark.conformance
@pytest.mark.parametrize("make", implementation_params(
    "sample", make_fake, "sample_real", "make_real", "pytest"))
def test_T_DIAG_008_same_case(make):
    assert make() == "expected", "synthetic conformance difference"
"""
    )
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setenv("PYTHONUTF8", "1")
        result = pytester.runpytest_subprocess(
            "-v", "test_conformance.py", "--attribution-json", str(report)
        )
    result.assert_outcomes(passed=2, failed=1)
    output = result.stdout.str()
    assert "sample[fake]" in output
    assert "sample[real]" in output
    assert "[ATTRIBUTION] OURS · fake-drift" in output
    assert "test_T_DIAG_008_same_case" in output
    assert "tests/fakes/" in output

    rows = json.loads(report.read_text(encoding="utf-8"))
    assert len(rows) == 1
    row = rows[0]
    assert row["verdict"] == "OURS"
    assert row["category"] == "fake-drift"
    assert row["dist"] == "pytest"
    assert "test_P_PYTEST_008_probe_passes" in str(row["probes"])
    assert "test_T_DIAG_008_same_case" in str(row["nodeid"])
    assert "sample[real]" in str(row["nodeid"])
    assert "tests/fakes/" in json.dumps(row)
