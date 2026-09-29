"""Recheck a captured destination immediately before an insertion attempt."""

from dataclasses import dataclass
from typing import Literal

from .destination import DestinationSnapshot
from .uia import UiaApi
from .win32 import Win32Api

VerifyStatus = Literal["same", "changed", "closed", "unverifiable"]


@dataclass(frozen=True, slots=True)
class Verification:
    status: VerifyStatus


def verify(snapshot: DestinationSnapshot, win32: Win32Api, uia: UiaApi) -> Verification:
    try:
        if not win32.is_window(snapshot.hwnd):
            return Verification("closed")
        if win32.foreground_window() != snapshot.hwnd:
            return Verification("changed")
        pid, exe = win32.window_process(snapshot.hwnd)
        if pid != snapshot.pid or exe.lower() != snapshot.exe:
            return Verification("changed")
    except Exception:
        return Verification("unverifiable")
    if snapshot.field is None:
        return Verification("unverifiable")
    try:
        if not uia.is_on_screen(snapshot.field):
            return Verification("unverifiable")
        if uia.selected_tab(snapshot.hwnd) != snapshot.tab:
            return Verification("changed")
        if uia.focused_element() != snapshot.field:
            return Verification("changed")
    except Exception:
        return Verification("unverifiable")
    return Verification("same")
