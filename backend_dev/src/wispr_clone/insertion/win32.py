"""Small, lazily loaded Win32 desktop boundary."""

from __future__ import annotations

import ctypes
import importlib
import sys
from dataclasses import dataclass
from typing import Any, Protocol, Sequence

EXCLUSION_FORMATS = (
    "ExcludeClipboardContentFromMonitorProcessing",
    "CanIncludeInClipboardHistory",
    "CanUploadToCloudClipboard",
)
KOREAN_LANGID = 0x0412


@dataclass(frozen=True, slots=True)
class KeyEvent:
    """One keyboard event in the Win32 SendInput representation."""

    vk: int = 0
    scan: int = 0
    flags: int = 0


class Win32Api(Protocol):
    def foreground_window(self) -> int: ...
    def is_window(self, hwnd: int) -> bool: ...
    def window_process(self, hwnd: int) -> tuple[int, str]: ...
    def window_title(self, hwnd: int) -> str: ...
    def keyboard_layout(self, hwnd: int) -> int: ...
    def set_foreground(self, hwnd: int) -> bool: ...
    def idle_ms(self) -> int: ...
    def send_inputs(self, inputs: Sequence[KeyEvent]) -> int: ...
    def clipboard_text(self) -> str | None: ...
    def set_clipboard(self, text: str, *, exclusion_formats: bool) -> None: ...
    def clear_clipboard(self) -> None: ...


class RealWin32:
    """Win32 implementation; imports pywin32 only when an operation is used."""

    @staticmethod
    def _modules() -> tuple[object, object, object]:
        if sys.platform != "win32":
            raise OSError("Win32 desktop APIs are available only on Windows")
        return (
            importlib.import_module("win32gui"),
            importlib.import_module("win32process"),
            importlib.import_module("win32con"),
        )

    def foreground_window(self) -> int:
        gui, _, _ = self._modules()
        return int(gui.GetForegroundWindow())  # type: ignore[attr-defined]

    def is_window(self, hwnd: int) -> bool:
        gui, _, _ = self._modules()
        return bool(gui.IsWindow(hwnd))  # type: ignore[attr-defined]

    def window_process(self, hwnd: int) -> tuple[int, str]:
        gui, process, _ = self._modules()
        pid = int(gui.GetWindowThreadProcessId(hwnd)[1])  # type: ignore[attr-defined]
        kernel32: Any = getattr(ctypes, "windll").kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)
        try:
            exe = str(getattr(process, "GetModuleFileNameEx")(handle, 0)).replace(
                "\\", "/"
            )
        finally:
            kernel32.CloseHandle(handle)
        return pid, exe.rsplit("/", 1)[-1].lower()

    def window_title(self, hwnd: int) -> str:
        gui, _, _ = self._modules()
        return str(gui.GetWindowText(hwnd))  # type: ignore[attr-defined]

    def keyboard_layout(self, hwnd: int) -> int:
        gui, _, _ = self._modules()
        thread_id = int(gui.GetWindowThreadProcessId(hwnd)[0])  # type: ignore[attr-defined]
        windll = getattr(ctypes, "windll")
        return int(windll.user32.GetKeyboardLayout(thread_id)) & 0xFFFF

    def set_foreground(self, hwnd: int) -> bool:
        gui, _, _ = self._modules()
        try:
            gui.SetForegroundWindow(hwnd)  # type: ignore[attr-defined]
            return self.foreground_window() == hwnd
        except Exception:
            return False

    def idle_ms(self) -> int:
        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

        info = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
        windll = getattr(ctypes, "windll")
        if not windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return 0
        return int(
            (int(windll.kernel32.GetTickCount()) - int(info.dwTime)) & 0xFFFFFFFF
        )

    def send_inputs(self, inputs: Sequence[KeyEvent]) -> int:
        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [
                ("wVk", ctypes.c_ushort),
                ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.c_void_p),
            ]

        class INPUT_UNION(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT)]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", ctypes.c_ulong), ("union", INPUT_UNION)]

        values = (INPUT * len(inputs))()
        for index, event in enumerate(inputs):
            values[index].type = 1
            values[index].union.ki = KEYBDINPUT(
                event.vk, event.scan, event.flags, 0, None
            )
        windll: Any = getattr(ctypes, "windll")
        return int(windll.user32.SendInput(len(inputs), values, ctypes.sizeof(INPUT)))

    def clipboard_text(self) -> str | None:
        clipboard = importlib.import_module("win32clipboard")
        con = importlib.import_module("win32con")
        clipboard.OpenClipboard()
        try:
            if not clipboard.IsClipboardFormatAvailable(con.CF_UNICODETEXT):
                return None
            return str(clipboard.GetClipboardData(con.CF_UNICODETEXT))
        finally:
            clipboard.CloseClipboard()

    def set_clipboard(self, text: str, *, exclusion_formats: bool) -> None:
        clipboard = importlib.import_module("win32clipboard")
        con = importlib.import_module("win32con")
        clipboard.OpenClipboard()
        try:
            clipboard.EmptyClipboard()
            clipboard.SetClipboardData(con.CF_UNICODETEXT, text)
            if exclusion_formats:
                for name in EXCLUSION_FORMATS:
                    clipboard.SetClipboardData(
                        clipboard.RegisterClipboardFormat(name), b"\x00\x00\x00\x00"
                    )
        finally:
            clipboard.CloseClipboard()

    def clear_clipboard(self) -> None:
        clipboard = importlib.import_module("win32clipboard")
        clipboard.OpenClipboard()
        try:
            clipboard.EmptyClipboard()
        finally:
            clipboard.CloseClipboard()
