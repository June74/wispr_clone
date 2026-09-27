"""Install or update Wispr Clone for the current Windows user.

Run with the python.org Python 3.12 (signed by the Python Software Foundation),
from backend_dev:

    py -3.12 packaging\\install_windows.py

The app goes into %LOCALAPPDATA%\\wispr_clone\\app as a venv created by that
Python, so its launchers are signed and Windows Smart App Control allows the
app to start (a freshly built unsigned exe was blocked, which is why the
PyInstaller build was removed).
Dependencies are installed at the versions pinned in uv.lock. Settings and
history stay in %LOCALAPPDATA%\\WisprClone and are not touched.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = Path(os.environ["LOCALAPPDATA"]) / "wispr_clone" / "app"
SCRIPTS = TARGET / "Scripts"
SHORTCUT = (
    Path(os.environ["APPDATA"])
    / "Microsoft"
    / "Windows"
    / "Start Menu"
    / "Programs"
    / "Wispr Clone.lnk"
)
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "WisprClone"
RUN_COMMAND = f'"{SCRIPTS / "pythonw.exe"}" -m wispr_clone --background'


def _run(*command: str | Path) -> None:
    print(">", " ".join(str(part) for part in command), flush=True)
    subprocess.run([str(part) for part in command], check=True)


def _uv() -> str:
    found = os.environ.get("WISPR_UV") or shutil.which("uv")
    if not found:
        raise SystemExit("uv was not found; put it on PATH or set WISPR_UV")
    return found


def _app_is_running() -> bool:
    find = ctypes.windll.user32.FindWindowW  # type: ignore[attr-defined]
    find.restype = ctypes.c_void_p
    return bool(find(None, "Wispr Clone"))


def _write_shortcut() -> None:
    icon = TARGET / "wispr_clone.ico"
    _run(
        SCRIPTS / "python.exe",
        "-c",
        "import sys; from wispr_clone.ui.tray import icon_image; "
        "icon_image(256).save(sys.argv[1], sizes=[(16, 16), (32, 32), (48, 48), "
        "(256, 256)])",
        icon,
    )
    script = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:WC_LNK);"
        "$s.TargetPath=$env:WC_EXE;$s.Arguments='-m wispr_clone';"
        "$s.WorkingDirectory=$env:WC_DIR;$s.IconLocation=$env:WC_ICO;"
        "$s.Description='Wispr Clone voice dictation';$s.Save()"
    )
    env = {
        **os.environ,
        "WC_LNK": str(SHORTCUT),
        "WC_EXE": str(SCRIPTS / "pythonw.exe"),
        "WC_DIR": str(TARGET),
        "WC_ICO": str(icon),
    }
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", script], check=True, env=env
    )
    print(f"shortcut {SHORTCUT}")


def _migrate_login_entry() -> None:
    """Keep launch at login on, pointed at this install, if it was on before."""
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE
        ) as key:
            current, _kind = winreg.QueryValueEx(key, RUN_VALUE)
            if current != RUN_COMMAND:
                winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, RUN_COMMAND)
                print(f"launch at login now starts {SCRIPTS / 'pythonw.exe'}")
    except FileNotFoundError:
        pass  # launch at login is off; the app's System page turns it on


def main() -> int:
    if sys.platform != "win32":
        raise SystemExit("run this with Windows Python")
    if "uv" in Path(sys.base_prefix).parts:
        raise SystemExit(
            "run with the python.org Python (py -3.12), not a uv-managed one: "
            "its launchers are unsigned"
        )
    if _app_is_running():
        raise SystemExit("Wispr Clone is running; quit it from the tray icon first")
    uv = _uv()
    with tempfile.TemporaryDirectory() as temp:
        work = Path(temp)
        _run(uv, "build", "--wheel", "--out-dir", work, "--project", ROOT)
        wheel = next(work.glob("wispr_clone-*.whl"))
        requirements = work / "requirements.txt"
        _run(
            uv,
            "export",
            "--frozen",
            "--no-dev",
            "--no-emit-project",
            "--project",
            ROOT,
            "--output-file",
            requirements,
        )
        if not (SCRIPTS / "python.exe").is_file():
            _run(sys.executable, "-m", "venv", TARGET)
        python = SCRIPTS / "python.exe"
        _run(uv, "pip", "install", "--python", python, "-r", requirements)
        _run(
            uv, "pip", "install", "--python", python, "--reinstall", "--no-deps", wheel
        )
    _run(SCRIPTS / "python.exe", "-m", "wispr_clone", "--self-test")
    _write_shortcut()
    _migrate_login_entry()
    print(f"installed {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
