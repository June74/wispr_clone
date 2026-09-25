"""Black-box checks for the package import-boundary command."""

import re
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
CHECKER = BACKEND / "scripts" / "check_imports.py"


def _tree(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "wispr_clone"
    root.mkdir()
    (root / "__init__.py").write_text("", encoding="utf-8")
    for name, source in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        for parent in path.parents:
            if parent == root:
                break
            (parent / "__init__.py").touch()
        path.write_text(source, encoding="utf-8")
    return root


def _check(root: Path | None = None) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(CHECKER)]
    if root is not None:
        command.extend(("--root", str(root)))
    return subprocess.run(command, cwd=BACKEND, capture_output=True, text=True)


def _diagnostic(result: subprocess.CompletedProcess[str], path: str, line: int) -> str:
    prefix = re.compile(rf"^{re.escape(path)}:{line}: .+ -> .+: .+$")
    matches = [
        output for output in result.stdout.splitlines() if prefix.fullmatch(output)
    ]
    assert matches, (result.returncode, result.stdout, result.stderr)
    return matches[0]


@pytest.mark.unit
@pytest.mark.invariant("The application module import graph is acyclic")
def test_T_ARCH_001_reports_cycle_across_package_modules(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        {
            "pipeline/orchestrator.py": "from wispr_clone.history import entry\n",
            "history/entry.py": "from wispr_clone.pipeline import orchestrator\n",
        },
    )

    result = _check(root)

    assert result.returncode == 1, (result.stdout, result.stderr)
    cycle_lines = [
        line for line in result.stdout.splitlines() if "cycle" in line.lower()
    ]
    assert cycle_lines, result.stdout
    assert any(
        re.fullmatch(
            r"(?:pipeline/orchestrator|history/entry)\.py:1: .+ -> .+: .*[Cc]ycle.*",
            line,
        )
        for line in cycle_lines
    ), result.stdout


@pytest.mark.unit
@pytest.mark.invariant("Packages import only permitted application packages")
def test_T_ARCH_002_clean_package_tree_passes(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        {
            "contracts/common.py": "import pathlib\nimport external_dependency\n",
            "storage/db.py": "from wispr_clone.contracts import common\n",
            "history/repo.py": "from wispr_clone.storage import db\n",
            "pipeline/run.py": "from wispr_clone.history import repo\n",
            "app.py": "from wispr_clone.pipeline import run\n",
        },
    )

    result = _check(root)

    assert result.returncode == 0, (result.stdout, result.stderr)
    assert result.stdout.strip() == ""


@pytest.mark.unit
@pytest.mark.invariant("Packages import only permitted application packages")
@pytest.mark.parametrize(
    ("source", "line"),
    [
        ("\n\nimport wispr_clone.pipeline\n", 3),
        ("\n\n\nfrom ..pipeline import x\n", 4),
    ],
    ids=("absolute", "relative"),
)
def test_T_ARCH_002_reports_hotkeys_to_pipeline_import(
    tmp_path: Path, source: str, line: int
) -> None:
    root = _tree(
        tmp_path,
        {"hotkeys/bad.py": source, "pipeline/__init__.py": "x = 1\n"},
    )

    result = _check(root)

    assert result.returncode == 1, (result.stdout, result.stderr)
    diagnostic = _diagnostic(result, "hotkeys/bad.py", line)
    assert "wispr_clone.hotkeys.bad -> wispr_clone.pipeline:" in diagnostic


@pytest.mark.unit
@pytest.mark.invariant("Packages import only permitted application packages")
def test_T_ARCH_002_allows_sibling_import_from_package_init(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        {
            "hotkeys/__init__.py": "from . import pipeline\n",
            "hotkeys/pipeline.py": "value = 1\n",
            "pipeline/__init__.py": "value = 1\n",
        },
    )

    result = _check(root)

    assert result.returncode == 0, (result.stdout, result.stderr)
    assert result.stdout.strip() == ""


@pytest.mark.unit
@pytest.mark.invariant("Packages import only permitted application packages")
def test_T_ARCH_002_reports_parent_import_from_package_init(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        {
            "hotkeys/__init__.py": "\nfrom ..pipeline import y\n",
            "pipeline/__init__.py": "y = 1\n",
        },
    )

    result = _check(root)

    assert result.returncode == 1, (result.stdout, result.stderr)
    diagnostic = _diagnostic(result, "hotkeys/__init__.py", 2)
    assert "wispr_clone.hotkeys -> wispr_clone.pipeline:" in diagnostic
    assert diagnostic.endswith("package dependency is not allowed")


@pytest.mark.unit
@pytest.mark.invariant("Unknown importers cannot import application packages")
def test_T_ARCH_002_reports_root_init_importing_subpackage(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        {
            "__init__.py": "from . import pipeline\n",
            "pipeline/__init__.py": "value = 1\n",
        },
    )

    result = _check(root)

    assert result.returncode == 1, (result.stdout, result.stderr)
    diagnostic = _diagnostic(result, "__init__.py", 1)
    assert "wispr_clone -> wispr_clone.pipeline:" in diagnostic
    assert diagnostic.endswith("unknown package")


@pytest.mark.unit
@pytest.mark.parametrize(
    ("importer", "imported", "source"),
    [
        (
            "contracts/bad.py",
            "wispr_clone.application",
            "from wispr_clone.application import api",
        ),
        (
            "config.py",
            "wispr_clone.application",
            "from wispr_clone.application import api",
        ),
        (
            "util/bad.py",
            "wispr_clone.pipeline",
            "from wispr_clone.pipeline import run",
        ),
    ],
    ids=("contracts", "config", "util"),
)
def test_T_ARCH_003_reports_upward_base_import(
    tmp_path: Path, importer: str, imported: str, source: str
) -> None:
    root = _tree(
        tmp_path,
        {
            importer: f"\n{source}\n",
            "application/api.py": "value = 1\n",
            "pipeline/run.py": "value = 1\n",
        },
    )

    result = _check(root)

    assert result.returncode == 1, (result.stdout, result.stderr)
    diagnostic = _diagnostic(result, importer, 2)
    module = "wispr_clone." + importer.removesuffix(".py").replace("/", ".")
    assert f"{module} -> {imported}:" in diagnostic


@pytest.mark.unit
def test_T_ARCH_003_real_source_tree_passes() -> None:
    result = _check()

    assert result.returncode == 0, (result.stdout, result.stderr)
    assert result.stdout.strip() == ""
