"""Launch-at-login through the current user's Windows Run key.

The registry value is the only record of the preference, so the switch always
shows what Windows will actually do at sign-in. Only an installed copy can be
registered; a source checkout reports the feature as unavailable.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from wispr_clone import config

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "WisprClone"
BACKGROUND_FLAG = "--background"


def command_line() -> str | None:
    """Return the Run command for this install, or None for a source checkout.

    The installed app runs on the signed python.org launcher (pythonw.exe, no
    console) so Windows Smart App Control allows it at sign-in.
    """
    if sys.platform != "win32":
        return None
    if config.resource_root() != Path(config.__file__).resolve().parent:
        return None  # a development checkout, not an installed wheel
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    return f'"{pythonw}" -m wispr_clone {BACKGROUND_FLAG}'


def _winreg() -> Any:
    import winreg

    return winreg


def status() -> dict[str, bool]:
    command = command_line()
    if command is None:
        return {"available": False, "enabled": False}
    winreg = _winreg()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _kind = winreg.QueryValueEx(key, VALUE_NAME)
    except OSError:
        return {"available": True, "enabled": False}
    # A value left by a moved or older install does not start this executable.
    return {"available": True, "enabled": value == command}


def set_enabled(enabled: bool) -> dict[str, bool]:
    command = command_line()
    if command is None:
        return {"available": False, "enabled": False}
    winreg = _winreg()
    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
    ) as key:
        if enabled:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass
    return status()
