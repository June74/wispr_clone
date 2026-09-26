"""T-DIAG-010: explicit import names map unavailable distributions."""

from pathlib import Path

import pytest
from _attribution.plugin import check_impact_map_sync


def _case(
    tmp_path: Path, source: str, *, import_names: str = ""
) -> tuple[Path, Path, Path]:
    src = tmp_path / "src" / "wispr_clone" / "insertion"
    src.mkdir(parents=True)
    module = src / "win32.py"
    module.write_text(source, encoding="utf-8")
    impact = tmp_path / "impact"
    impact.mkdir()
    fragment = impact / "pywin32.toml"
    fragment.write_text(
        'dependency = "pywin32"\nkind = "library"\nmodules = ["insertion.win32"]\n'
        + import_names
        + 'features = ["synthetic insertion"]\nerror_codes = ["insertion_failed"]\n'
        'action = "check synthetic package"\n',
        encoding="utf-8",
    )
    return src.parents[1], impact, module


def test_T_DIAG_010_explicit_name_maps_missing_package(tmp_path: Path) -> None:
    root, impact, _ = _case(
        tmp_path,
        "import synthetic_win32_api_name\n",
        import_names='import_names = ["synthetic_win32_api_name"]\n',
    )
    check_impact_map_sync(root, impact)


def test_T_DIAG_010_unused_listed_module_still_fails(tmp_path: Path) -> None:
    root, impact, _ = _case(
        tmp_path,
        "import json\n",
        import_names='import_names = ["synthetic_win32_api_name"]\n',
    )
    with pytest.raises(ValueError, match="pywin32|insertion.win32"):
        check_impact_map_sync(root, impact)


def test_T_DIAG_010_uncovered_import_still_fails(tmp_path: Path) -> None:
    root, impact, module = _case(
        tmp_path,
        "import synthetic_win32_api_name\n",
        import_names='import_names = ["synthetic_win32_api_name"]\n',
    )
    module.write_text(
        "import synthetic_win32_api_name\nimport uncovered_synthetic_package\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="uncovered_synthetic_package"):
        check_impact_map_sync(root, impact)


def test_T_DIAG_010_fragments_without_key_keep_old_behavior(tmp_path: Path) -> None:
    root, impact, _ = _case(tmp_path, "import synthetic_win32_api_name\n")
    with pytest.raises(ValueError, match="synthetic_win32_api_name"):
        check_impact_map_sync(root, impact)
