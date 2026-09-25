"""WO-P0.6 contracts for the cross-job attribution summary (T-CI-003..006).

Required Python API: build_report(inputs: list[Path]) -> str.
Required CLI: python scripts/attribution_report.py OUT.md INPUT.json [...].
"""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
SCRIPT = BACKEND / "scripts" / "attribution_report.py"


def _row(
    nodeid: str,
    *,
    verdict: str = "OURS",
    dist: str | None = None,
    category: str | None = "logic",
    probes: list[str] | None = None,
) -> dict[str, object]:
    """Use the failure-row fields actually emitted by the attribution plugin."""
    return {
        "nodeid": nodeid,
        "dist": dist,
        "version": "1.2.3" if dist else None,
        "where": "src/wispr_clone/pipeline/run_controller.py:42 in run",
        "probes": probes or [],
        "verdict": verdict,
        "category": category,
        "symptom": "AssertionError: safe summary",
        "phase": "call",
    }


def _input(tmp_path: Path, job: str, rows: list[dict[str, object]]) -> Path:
    path = tmp_path / f"attribution-{job}.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


def _build_report(inputs: list[Path]) -> str:
    """Call build_report(inputs: list[Path]) -> str from the script module."""
    spec = importlib.util.spec_from_file_location("attribution_report", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    report: str = module.build_report(inputs)
    return report


def _cli(out: Path, *inputs: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(out), *(str(path) for path in inputs)],
        cwd=BACKEND,
        env={**os.environ, "PYTHONUTF8": "1"},
        text=True,
        capture_output=True,
        check=False,
    )


def test_T_CI_003_clean_missing_and_empty_reports(tmp_path: Path) -> None:
    clean = _input(tmp_path, "unit-linux", [])
    empty = tmp_path / "attribution-probes-windows.json"
    empty.write_text("", encoding="utf-8")
    missing = tmp_path / "attribution-probes-linux.json"
    inputs = [clean, empty, missing]

    markdown = _build_report(inputs)
    assert "0 failures" in markdown
    for job in ("probes-windows", "probes-linux"):
        assert any(
            job in line and "no report" in line.lower()
            for line in markdown.splitlines()
        )

    out = tmp_path / "summary.md"
    result = _cli(out, *inputs)
    assert result.returncode == 0, result.stderr
    assert out.read_text(encoding="utf-8") == markdown


def test_T_CI_004_merged_tables_show_each_failure_and_reproduction(
    tmp_path: Path,
) -> None:
    logic = "tests/unit/test_logic.py::test_T_LOG_001"
    service = "tests/integration/test_cleanup.py::test_T_CLE_002"
    inputs = [
        _input(tmp_path, "unit-linux", [_row(logic)]),
        _input(
            tmp_path,
            "unit-windows",
            [
                _row(logic),
                _row(service, verdict="NOT OURS", dist="lmstudio", category="service"),
            ],
        ),
    ]
    out = tmp_path / "summary.md"
    result = _cli(out, *inputs)
    assert result.returncode == 0, result.stderr
    markdown = out.read_text(encoding="utf-8")
    assert markdown == _build_report(inputs)
    for nodeid in (logic, service):
        assert markdown.count(nodeid) == 1
        path, name = nodeid.split("::")
        assert f"uv run pytest {path} -k {name}" in markdown
    assert "OURS" in markdown
    assert "NOT OURS" in markdown
    assert "logic" in markdown
    assert "lmstudio" in markdown and "service" in markdown
    assert "run_controller.py:42 in run" in markdown


def test_T_CI_005_cross_job_probe_outcomes(tmp_path: Path) -> None:
    dependency = "synthetic-dist"
    adapter = "tests/conformance/test_adapter.py::test_T_ADP_001[real]"
    unknown = _row(adapter, verdict="UNDETERMINED", dist=dependency, category=None)
    unknown["missing_probe"] = f"probe({dependency}) did not run"

    failed_inputs = [
        _input(tmp_path, "unit-linux", [unknown]),
        _input(
            tmp_path,
            "probes-windows",
            [
                _row(
                    "tests/probes/test_dependency.py::test_P_DEP_001",
                    verdict="NOT OURS",
                    dist=dependency,
                    category="library",
                )
            ],
        ),
    ]
    failed = _build_report(failed_inputs)
    adapter_line = next(line for line in failed.splitlines() if adapter in line)
    assert "NOT OURS" in adapter_line

    passed_dir = tmp_path / "passed"
    passed_dir.mkdir()
    passed_inputs = [
        _input(passed_dir, "unit-linux", [unknown]),
        _input(
            passed_dir,
            "unit-windows",
            [
                _row(
                    "tests/unit/test_other.py::test_T_OTH_001",
                    dist=dependency,
                    probes=["tests/probes/test_dependency.py::test_P_DEP_002"],
                )
            ],
        ),
    ]
    passed = _build_report(passed_inputs)
    adapter_line = next(line for line in passed.splitlines() if adapter in line)
    assert "UNDETERMINED" in adapter_line
    assert "probe passed in unit-windows" in passed


def test_T_CI_006_private_fields_and_captured_text_never_enter_markdown(
    tmp_path: Path,
) -> None:
    row = _row("tests/unit/test_privacy.py::test_T_PRI_001")
    row["symptom"] = "AssertionError: PRIVATE_SYMPTOM_001"
    row["captured_output"] = "PRIVATE_CAPTURED_OUTPUT_002"
    row["stdout"] = "PRIVATE_STDOUT_003"
    row["private_fixture"] = {"transcript": "PRIVATE_TRANSCRIPT_004"}
    source = _input(tmp_path, "unit-linux", [row])

    markdown = _build_report([source])
    out = tmp_path / "summary.md"
    result = _cli(out, source)
    assert result.returncode == 0, result.stderr
    assert out.read_text(encoding="utf-8") == markdown
    assert "test_T_PRI_001" in markdown
    for sentinel in (
        "PRIVATE_SYMPTOM_001",
        "PRIVATE_CAPTURED_OUTPUT_002",
        "PRIVATE_STDOUT_003",
        "PRIVATE_TRANSCRIPT_004",
    ):
        assert sentinel not in markdown
