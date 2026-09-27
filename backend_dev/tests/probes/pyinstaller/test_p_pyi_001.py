"""P-PYI-001: opt-in Windows package build and frozen self-test."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.probe("pyinstaller"), pytest.mark.windows]


def test_P_PYI_001_build_and_self_test() -> None:
    if sys.platform != "win32" or os.environ.get("WISPR_REAL_PACKAGE") != "1":
        pytest.skip("requires Windows and WISPR_REAL_PACKAGE=1")

    backend = Path(__file__).resolve().parents[3]
    build_script = backend / "packaging" / "build_windows.py"
    subprocess.run([sys.executable, str(build_script)], cwd=backend, check=True)

    exe = (
        Path(os.environ["LOCALAPPDATA"])
        / "wispr_clone"
        / "dist"
        / "WisprClone"
        / "WisprClone.exe"
    )
    assert exe.is_file(), f"missing packaged executable: {exe}"
    result = subprocess.run([str(exe), "--self-test"], timeout=60, check=False)
    assert result.returncode == 0
