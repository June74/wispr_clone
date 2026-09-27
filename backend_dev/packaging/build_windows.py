"""Build the Windows onedir bundle and smoke-test it (P-PYI-001).

Run with the Windows venv: ``uv.exe run --locked python packaging/build_windows.py``.
Outputs go to %LOCALAPPDATA%\\wispr_clone\\{build,dist}, never to the WSL share.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = HERE / "wispr_clone.spec"


def output_root() -> Path:
    return Path(os.environ["LOCALAPPDATA"]) / "wispr_clone"


def main() -> int:
    if sys.platform != "win32":
        print("build_windows.py must run on Windows", file=sys.stderr)
        return 2
    root = output_root()
    dist, work = root / "dist", root / "build"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            str(SPEC),
            "--noconfirm",
            "--clean",
            "--distpath",
            str(dist),
            "--workpath",
            str(work),
        ],
        check=True,
    )
    exe = dist / "WisprClone" / "WisprClone.exe"
    result = subprocess.run([str(exe), "--self-test"], timeout=60)
    if result.returncode != 0:
        print(f"self-test failed with exit code {result.returncode}", file=sys.stderr)
        return 1
    digest = hashlib.sha256(exe.read_bytes()).hexdigest()
    print(f"built {exe}")
    print(f"sha256 {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
