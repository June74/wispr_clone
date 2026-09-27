"""T-PKG-001: resource paths work in source and frozen distributions."""

import ast
import sys
from pathlib import Path

from wispr_clone import config


def test_T_PKG_001_resource_root_in_source_and_frozen(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    root = config.resource_root()
    assert root == Path(config.__file__).resolve().parents[2]
    assert (root / "web" / "index.html").is_file()

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert config.resource_root() == tmp_path


def test_T_PKG_002_web_paths_do_not_use_module_file() -> None:
    source_root = Path(config.__file__).resolve().parent
    for path in source_root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Div):
                continue
            if not isinstance(node.right, ast.Constant) or node.right.value != "web":
                continue
            assert not any(
                isinstance(part, ast.Name) and part.id == "__file__"
                for part in ast.walk(node.left)
            ), f"web path computed from __file__: {path}:{node.lineno}"
