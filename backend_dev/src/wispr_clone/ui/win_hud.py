"""Native, non-activating visibility controls for the Windows HUD."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import Any, Callable, cast

_GWL_EXSTYLE = -20
_WS_EX_APPWINDOW = 0x00040000
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_TRANSPARENT = 0x00000020
_WS_EX_LAYERED = 0x00080000
_WS_EX_NOACTIVATE = 0x08000000
_LWA_ALPHA = 0x00000002
_DWMWA_WINDOW_CORNER_PREFERENCE = 33
_DWMWCP_ROUND = 2
_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_FRAMECHANGED = 0x0020
_SWP_NOACTIVATE = 0x0010
_SWP_ASYNCWINDOWPOS = 0x4000
_HWND_TOPMOST = ctypes.c_void_p(-1)


def _apis() -> tuple[Any, Any]:
    """Load isolated DLL handles and declare every function signature."""
    windll = cast(Any, getattr(ctypes, "WinDLL"))
    user32 = windll("user32", use_last_error=True)
    dwmapi = windll("dwmapi", use_last_error=True)
    _declare(user32, "FindWindowW", [wintypes.LPCWSTR, wintypes.LPCWSTR], wintypes.HWND)
    _declare(
        user32,
        "GetWindowLongPtrW",
        [wintypes.HWND, ctypes.c_int],
        ctypes.c_ssize_t,
    )
    _declare(
        user32,
        "SetWindowLongPtrW",
        [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t],
        ctypes.c_ssize_t,
    )
    _declare(
        user32,
        "SetLayeredWindowAttributes",
        [wintypes.HWND, ctypes.c_uint32, ctypes.c_ubyte, wintypes.DWORD],
        wintypes.BOOL,
    )
    _declare(user32, "GetForegroundWindow", [], wintypes.HWND)
    _declare(user32, "SetForegroundWindow", [wintypes.HWND], wintypes.BOOL)
    _declare(
        user32,
        "SetWindowPos",
        [
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ],
        wintypes.BOOL,
    )
    _declare(
        dwmapi,
        "DwmSetWindowAttribute",
        [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD],
        ctypes.c_long,
    )
    return user32, dwmapi


def _declare(dll: Any, name: str, argtypes: list[Any], restype: Any) -> None:
    """Set a native signature when present; minimal fake seams may omit APIs."""
    function = getattr(dll, name, None)
    if function is not None:
        function.argtypes = argtypes
        function.restype = restype


def _set_style(user32: Any, hwnd: int) -> bool:
    old_style = user32.GetWindowLongPtrW(hwnd, _GWL_EXSTYLE)
    style = (
        old_style
        | _WS_EX_LAYERED
        | _WS_EX_TOOLWINDOW
        | _WS_EX_TRANSPARENT
        | _WS_EX_NOACTIVATE
    ) & ~_WS_EX_APPWINDOW
    cast(Any, getattr(ctypes, "set_last_error"))(0)
    previous = user32.SetWindowLongPtrW(hwnd, _GWL_EXSTYLE, style)
    return bool(previous) or cast(Any, getattr(ctypes, "get_last_error"))() == 0


def _set_alpha(user32: Any, hwnd: int, alpha: int) -> bool:
    return bool(user32.SetLayeredWindowAttributes(hwnd, 0, alpha, _LWA_ALPHA))


def prepare(title: str, make_visible: Callable[[], None]) -> int | None:
    """Prepare a layered non-activating HUD; return None when unavailable."""
    if sys.platform != "win32":
        return None
    try:
        user32, dwmapi = _apis()
        hwnd = user32.FindWindowW(None, title)
        if not hwnd or not _set_style(user32, hwnd) or not _set_alpha(user32, hwnd, 0):
            return None
        previous_foreground = user32.GetForegroundWindow()
        make_visible()
        if user32.GetForegroundWindow() == hwnd and previous_foreground:
            user32.SetForegroundWindow(previous_foreground)
        if not _set_style(user32, hwnd) or not _set_alpha(user32, hwnd, 0):
            return None
        if not user32.SetWindowPos(
            hwnd,
            _HWND_TOPMOST,
            0,
            0,
            0,
            0,
            _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE | _SWP_FRAMECHANGED,
        ):
            return None
        preference = wintypes.DWORD(_DWMWCP_ROUND)
        dwmapi.DwmSetWindowAttribute(
            hwnd,
            _DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(preference),
            ctypes.sizeof(preference),
        )
        return hwnd
    except Exception:
        return None


def show(hwnd: int | None) -> bool:
    """Show the HUD at full alpha without activating it."""
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        user32, _ = _apis()
        return _set_alpha(user32, hwnd, 255) and bool(
            user32.SetWindowPos(
                hwnd,
                _HWND_TOPMOST,
                0,
                0,
                0,
                0,
                _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE | _SWP_ASYNCWINDOWPOS,
            )
        )
    except Exception:
        return False


def hide(hwnd: int | None) -> bool:
    """Hide the HUD with zero alpha without activating it."""
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        user32, _ = _apis()
        return _set_alpha(user32, hwnd, 0)
    except Exception:
        return False
