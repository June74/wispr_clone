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


@pytest.mark.parametrize(
    ("scenario", "outcomes"),
    [
        ("real_teardown", {"passed": 3, "errors": 1}),
        ("fake_teardown", {"passed": 2, "failed": 1, "errors": 1}),
        ("no_fake_twin", {"passed": 1, "failed": 1}),
    ],
)
def test_T_DIAG_008_fake_drift_requires_real_call_failure_and_passing_twin(
    pytester: pytest.Pytester,
    scenario: str,
    outcomes: dict[str, int],
) -> None:
    tests_dir = Path(__file__).resolve().parents[1]
    report = pytester.path / "attribution.json"
    pytester.makeini(
        """[pytest]
addopts = --strict-markers
markers =
    probe(dist): isolated dependency probe
    adapter(dist): project adapter
"""
    )
    pytester.makeconftest(
        "import sys\n"
        f"sys.path.insert(0, {str(tests_dir)!r})\n"
        "pytest_plugins = ('_attribution.plugin',)\n"
    )
    pytester.makepyfile(
        test_drift_edges=f"""
import pytest

SCENARIO = {scenario!r}

@pytest.fixture
def completed_case(request):
    yield
    case_id = request.node.callspec.id
    if SCENARIO == "fake_teardown" and case_id.endswith("[fake]"):
        pytest.fail("fake teardown failed")
    if SCENARIO == "real_teardown" and case_id.endswith("[real]"):
        pytest.fail("real teardown failed")

@pytest.mark.probe("pytest")
def test_probe():
    assert True

cases = [pytest.param("wrong", marks=pytest.mark.adapter("pytest"), id="sample[real]")]
if SCENARIO != "no_fake_twin":
    cases.insert(0, pytest.param("expected", id="sample[fake]"))

@pytest.mark.parametrize("value", cases)
def test_same_case(value, completed_case):
    if SCENARIO == "real_teardown":
        assert value in ("expected", "wrong")
    else:
        assert value == "expected"
"""
    )
    result = pytester.runpytest_subprocess(
        "test_drift_edges.py", "--attribution-json", str(report)
    )
    result.assert_outcomes(**outcomes)
    rows = json.loads(report.read_text(encoding="utf-8"))
    real_rows = [row for row in rows if "sample[real]" in row["nodeid"]]
    assert len(real_rows) == 1
    assert real_rows[0]["category"] != "fake-drift"
    if scenario == "no_fake_twin":
        assert real_rows[0]["category"] == "adapter-misuse"
