"""T-DIAG-020: retired local STT code and dependencies stay removed."""

import ast
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
TRANSCRIBE_CPP = re.compile(r"transcribe[_-]cpp")


def test_T_DIAG_020_no_local_voxtral_path() -> None:
    violations: list[str] = []
    roots = (
        BACKEND / "src",
        BACKEND / "tests/_attribution/impact",
        REPO / ".github/workflows",
    )
    files = [BACKEND / "pyproject.toml", BACKEND / "uv.lock"]
    for root in roots:
        if root.is_dir():
            files.extend(path for path in root.rglob("*") if path.is_file())

    for path in files:
        relative = (
            path.relative_to(BACKEND)
            if path.is_relative_to(BACKEND)
            else path.relative_to(REPO)
        )
        if "__pycache__" in path.parts:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if TRANSCRIBE_CPP.search(line):
                violations.append(f"{relative}:{number}: transcribe.cpp reference")

    stt = BACKEND / "src/wispr_clone/stt"
    violations.extend(
        f"{path.relative_to(BACKEND)}: voxtral module"
        for path in stt.iterdir()
        if path.name.startswith("voxtral")
    )

    config = BACKEND / "src/wispr_clone/config.py"
    tree = ast.parse(config.read_text(encoding="utf-8"), filename=str(config))
    if any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "stt_model_path"
        for node in tree.body
    ):
        violations.append("src/wispr_clone/config.py: stt_model_path")

    assert not violations, "Local Voxtral path remains:\n" + "\n".join(violations)
