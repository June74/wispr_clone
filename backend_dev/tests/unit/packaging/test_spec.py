"""T-PKG-003: inspect the PyInstaller spec without running a build."""

import ast
from pathlib import Path


def test_T_PKG_003_spec_bundles_runtime_and_uses_onedir_settings() -> None:
    backend = Path(__file__).resolve().parents[3]
    spec = backend / "packaging" / "wispr_clone.spec"
    tree = ast.parse(spec.read_text(encoding="utf-8"), filename=str(spec))

    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    assert any(
        isinstance(call.func, ast.Name)
        and call.func.id == "collect_submodules"
        and call.args
        and isinstance(call.args[0], ast.Constant)
        and call.args[0].value == "wispr_clone"
        for call in calls
    )
    assert any(
        isinstance(call.func, ast.Name)
        and call.func.id == "collect_data_files"
        and call.args
        and isinstance(call.args[0], ast.Constant)
        and call.args[0].value == "uiautomation"
        and any(
            keyword.arg == "includes" and "bin/*.dll" in ast.literal_eval(keyword.value)
            for keyword in call.keywords
        )
        for call in calls
    )

    comprehensions = [node for node in ast.walk(tree) if isinstance(node, ast.ListComp)]
    assert any(
        "WEB.rglob('*')" in ast.unparse(comp)
        and "'tests' not in path.relative_to(WEB).parts" in ast.unparse(comp)
        and "Path('web')" in ast.unparse(comp)
        for comp in comprehensions
    )

    def kwargs(name: str) -> dict[str, ast.expr]:
        call = next(
            call
            for call in calls
            if isinstance(call.func, ast.Name) and call.func.id == name
        )
        return {keyword.arg: keyword.value for keyword in call.keywords if keyword.arg}

    analysis = kwargs("Analysis")
    assert ast.unparse(analysis["datas"]) == "web_datas"
    assert ast.unparse(analysis["binaries"]) == "uia_binaries"
    assert ast.unparse(analysis["hiddenimports"]) == (
        "collect_submodules('wispr_clone')"
    )
    exe = kwargs("EXE")
    assert ast.literal_eval(exe["console"]) is False
    assert ast.literal_eval(exe["upx"]) is False
    assert ast.literal_eval(exe["name"]) == "WisprClone"
    assert ast.literal_eval(exe["exclude_binaries"]) is True
    assert any(
        isinstance(call.func, ast.Name) and call.func.id == "COLLECT" for call in calls
    )
