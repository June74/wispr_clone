"""Caption-less native frame for the settings window on Windows.

The page draws its own title bar. The native caption is removed with a
WM_NCCALCSIZE subclass so the resize border, Snap and the maximize work area
stay native. Everything here runs on the window's GUI thread except the
PostMessage/ShowWindowAsync entry points, which are thread-safe.
"""

from __future__ import annotations

import ctypes
import sys
from collections.abc import Callable
from ctypes import wintypes
from typing import Any, cast

_WM_QUERYENDSESSION = 0x0011
_WM_WINDOWPOSCHANGING = 0x0046
_WM_WINDOWPOSCHANGED = 0x0047
_WM_NCCALCSIZE = 0x0083
_WM_NCLBUTTONDOWN = 0x00A1
_WM_APP_DRAG = 0x8000 + 0x31
_WM_APP_SHOW = 0x8000 + 0x32
_HTCAPTION = 2
_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_NOZORDER = 0x0004
_SWP_NOACTIVATE = 0x0010
_SWP_FRAMECHANGED = 0x0020
_SW_MAXIMIZE = 3
_SW_MINIMIZE = 6
_SW_RESTORE = 9
_SM_CYFRAME = 33
_SM_CXPADDEDBORDER = 92
_SUBCLASS_ID = 0x57435446

_apis_cache: tuple[Any, Any] | None = None
_subclass_proc: Any = None
# Window size to keep while WinForms reacts to WM_WINDOWPOSCHANGED. WinForms
# recomputes the restored size from a caption it no longer has and would grow
# the window by the caption height on every restore.
_settled_size: dict[int, tuple[int, int]] = {}
# Per-window callbacks, run on the GUI thread; they must return quickly.
_on_show: dict[int, Callable[[], None]] = {}
_on_session_end: dict[int, Callable[[], None]] = {}


class _NcCalcSizeParams(ctypes.Structure):
    _fields_ = [("rgrc", wintypes.RECT * 3), ("lppos", ctypes.c_void_p)]


class _WindowPos(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("insert_after", wintypes.HWND),
        ("x", ctypes.c_int),
        ("y", ctypes.c_int),
        ("cx", ctypes.c_int),
        ("cy", ctypes.c_int),
        ("flags", wintypes.UINT),
    ]


def _declare(dll: Any, name: str, argtypes: list[Any], restype: Any) -> None:
    function = getattr(dll, name)
    function.argtypes = argtypes
    function.restype = restype


def _apis() -> tuple[Any, Any]:
    """Load isolated DLL handles and declare every function signature."""
    global _apis_cache
    if _apis_cache is not None:
        return _apis_cache
    windll = cast(Any, getattr(ctypes, "WinDLL"))
    user32 = windll("user32", use_last_error=True)
    comctl32 = windll("comctl32", use_last_error=True)
    hwnd, uint, wparam, lparam = (
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    )
    _declare(
        comctl32, "DefSubclassProc", [hwnd, uint, wparam, lparam], ctypes.c_ssize_t
    )
    _declare(user32, "IsZoomed", [hwnd], wintypes.BOOL)
    _declare(user32, "IsIconic", [hwnd], wintypes.BOOL)
    _declare(
        user32, "GetWindowRect", [hwnd, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL
    )
    _declare(user32, "GetCursorPos", [ctypes.POINTER(wintypes.POINT)], wintypes.BOOL)
    _declare(user32, "GetDpiForWindow", [hwnd], uint)
    _declare(user32, "GetSystemMetricsForDpi", [ctypes.c_int, uint], ctypes.c_int)
    _declare(user32, "ReleaseCapture", [], wintypes.BOOL)
    _declare(user32, "PostMessageW", [hwnd, uint, wparam, lparam], wintypes.BOOL)
    _declare(user32, "ShowWindowAsync", [hwnd, ctypes.c_int], wintypes.BOOL)
    _declare(user32, "SetForegroundWindow", [hwnd], wintypes.BOOL)
    _declare(user32, "FindWindowW", [wintypes.LPCWSTR, wintypes.LPCWSTR], hwnd)
    _declare(
        user32,
        "GetWindowThreadProcessId",
        [hwnd, ctypes.POINTER(wintypes.DWORD)],
        wintypes.DWORD,
    )
    _declare(user32, "AllowSetForegroundWindow", [wintypes.DWORD], wintypes.BOOL)
    _declare(
        user32,
        "SetWindowPos",
        [hwnd, hwnd, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, uint],
        wintypes.BOOL,
    )
    _apis_cache = (user32, comctl32)
    return _apis_cache


def _window_proc(
    hwnd: int, msg: int, wparam: int, lparam: int, _id: int, _data: int
) -> int:
    user32, comctl32 = _apis()
    if msg == _WM_NCCALCSIZE and wparam:
        params = ctypes.cast(lparam, ctypes.POINTER(_NcCalcSizeParams)).contents
        top = params.rgrc[0].top
        result = comctl32.DefSubclassProc(hwnd, msg, wparam, lparam)
        # Keep the side and bottom resize borders; drop only the caption.
        params.rgrc[0].top = top
        if user32.IsZoomed(hwnd):
            # A maximized window overhangs the monitor by its frame thickness.
            dpi = user32.GetDpiForWindow(hwnd)
            params.rgrc[0].top += user32.GetSystemMetricsForDpi(
                _SM_CYFRAME, dpi
            ) + user32.GetSystemMetricsForDpi(_SM_CXPADDEDBORDER, dpi)
        return int(result)
    if msg == _WM_WINDOWPOSCHANGED and not (
        user32.IsZoomed(hwnd) or user32.IsIconic(hwnd)
    ):
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        _settled_size[hwnd] = (rect.right - rect.left, rect.bottom - rect.top)
        try:
            return int(comctl32.DefSubclassProc(hwnd, msg, wparam, lparam))
        finally:
            _settled_size.pop(hwnd, None)
    if msg == _WM_WINDOWPOSCHANGING and hwnd in _settled_size:
        result = comctl32.DefSubclassProc(hwnd, msg, wparam, lparam)
        pos = ctypes.cast(lparam, ctypes.POINTER(_WindowPos)).contents
        if not pos.flags & _SWP_NOSIZE:
            pos.cx, pos.cy = _settled_size[hwnd]
        return int(result)
    if msg in (_WM_APP_SHOW, _WM_QUERYENDSESSION):
        callbacks = _on_show if msg == _WM_APP_SHOW else _on_session_end
        callback = callbacks.get(hwnd)
        if callback is not None:
            try:
                callback()
            except Exception:
                pass
        if msg == _WM_APP_SHOW:
            return 0
    if msg == _WM_APP_DRAG:
        # Hand the pressed mouse button to the native move loop (Snap included).
        point = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(point))
        user32.ReleaseCapture()
        packed = ((point.y & 0xFFFF) << 16) | (point.x & 0xFFFF)
        user32.PostMessageW(hwnd, _WM_NCLBUTTONDOWN, _HTCAPTION, packed)
        return 0
    return int(comctl32.DefSubclassProc(hwnd, msg, wparam, lparam))


def install(
    hwnd: int,
    *,
    on_show: Callable[[], None] | None = None,
    on_session_end: Callable[[], None] | None = None,
) -> bool:
    """Remove the native caption; call on the window's GUI thread.

    ``on_show`` runs when another launch asks this window to appear;
    ``on_session_end`` runs when Windows asks to end the session.
    """
    global _subclass_proc
    if sys.platform != "win32" or not hwnd:
        return False
    if on_show is not None:
        _on_show[hwnd] = on_show
    if on_session_end is not None:
        _on_session_end[hwnd] = on_session_end
    try:
        user32, comctl32 = _apis()
        if _subclass_proc is None:
            factory = cast(Any, getattr(ctypes, "WINFUNCTYPE"))
            proc_type = factory(
                ctypes.c_ssize_t,
                wintypes.HWND,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM,
                ctypes.c_size_t,
                ctypes.c_size_t,
            )
            _declare(
                comctl32,
                "SetWindowSubclass",
                [wintypes.HWND, proc_type, ctypes.c_size_t, ctypes.c_size_t],
                wintypes.BOOL,
            )
            _subclass_proc = proc_type(_window_proc)
        if not comctl32.SetWindowSubclass(hwnd, _subclass_proc, _SUBCLASS_ID, 0):
            return False
        return bool(
            user32.SetWindowPos(
                hwnd,
                None,
                0,
                0,
                0,
                0,
                _SWP_NOSIZE
                | _SWP_NOMOVE
                | _SWP_NOZORDER
                | _SWP_NOACTIVATE
                | _SWP_FRAMECHANGED,
            )
        )
    except Exception:
        return False


def begin_drag(hwnd: int | None) -> bool:
    """Start a native window move from the page's title bar."""
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        user32, _ = _apis()
        return bool(user32.PostMessageW(hwnd, _WM_APP_DRAG, 0, 0))
    except Exception:
        return False


def minimize(hwnd: int | None) -> bool:
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        user32, _ = _apis()
        return bool(user32.ShowWindowAsync(hwnd, _SW_MINIMIZE))
    except Exception:
        return False


def toggle_maximize(hwnd: int | None) -> bool:
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        user32, _ = _apis()
        command = _SW_RESTORE if user32.IsZoomed(hwnd) else _SW_MAXIMIZE
        return bool(user32.ShowWindowAsync(hwnd, command))
    except Exception:
        return False


def bring_to_front(hwnd: int | None) -> bool:
    """Restore a minimized window and give it focus."""
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        user32, _ = _apis()
        if user32.IsIconic(hwnd):
            user32.ShowWindowAsync(hwnd, _SW_RESTORE)
        return bool(user32.SetForegroundWindow(hwnd))
    except Exception:
        return False


def activate_existing(title: str) -> bool:
    """Ask an already-running instance's window to show itself."""
    if sys.platform != "win32":
        return False
    try:
        user32, _ = _apis()
        hwnd = user32.FindWindowW(None, title)
        if not hwnd:
            return False
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        # This launch holds the foreground right; pass it on to the running app.
        user32.AllowSetForegroundWindow(pid.value)
        return bool(user32.PostMessageW(hwnd, _WM_APP_SHOW, 0, 0))
    except Exception:
        return False
