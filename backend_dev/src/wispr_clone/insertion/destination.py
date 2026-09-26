"""Capture and serialize a privacy-safe destination identity."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Mapping

from wispr_clone.contracts.common import ErrorCode, WisprError

from .uia import RuntimeId, UiaApi
from .win32 import Win32Api


@dataclass(frozen=True, slots=True)
class DestinationSnapshot:
    hwnd: int
    pid: int
    exe: str
    title_hash: str
    tab: RuntimeId | None
    field: RuntimeId | None
    field_type: str | None
    langid: int

    def to_json(self) -> dict[str, object]:
        return {
            "hwnd": self.hwnd,
            "pid": self.pid,
            "exe": self.exe,
            "title_hash": self.title_hash,
            "tab": list(self.tab) if self.tab is not None else None,
            "field": list(self.field) if self.field is not None else None,
            "field_type": self.field_type,
            "langid": self.langid,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, object]) -> DestinationSnapshot:
        def bad() -> WisprError:
            return WisprError(ErrorCode.VALIDATION, "insertion.destination", "snapshot")

        def rid(value: object) -> RuntimeId | None:
            if value is None:
                return None
            if (
                not isinstance(value, list)
                or not value
                or any(type(v) is not int for v in value)
            ):
                raise bad()
            return tuple(value)

        try:
            if set(data) != {
                "hwnd",
                "pid",
                "exe",
                "title_hash",
                "tab",
                "field",
                "field_type",
                "langid",
            }:
                raise bad()
            hwnd, pid, exe = data["hwnd"], data["pid"], data["exe"]
            digest, langid = data["title_hash"], data["langid"]
            field_type = data["field_type"]
            if (
                type(hwnd) is not int
                or hwnd <= 0
                or type(pid) is not int
                or pid <= 0
                or not isinstance(exe, str)
                or not exe
                or exe != exe.lower()
                or not isinstance(digest, str)
                or len(digest) != 64
                or any(c not in "0123456789abcdef" for c in digest)
                or type(langid) is not int
                or not 0 <= langid <= 0xFFFF
                or (field_type is not None and not isinstance(field_type, str))
            ):
                raise bad()
            return cls(
                hwnd,
                pid,
                exe,
                digest,
                rid(data["tab"]),
                rid(data["field"]),
                field_type,
                langid,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise bad() from error


def capture(
    win32: Win32Api,
    uia: UiaApi,
    *,
    exclude_pids: frozenset[int] = frozenset(),
) -> DestinationSnapshot:
    hwnd = win32.foreground_window()
    if hwnd == 0 or not win32.is_window(hwnd):
        raise WisprError(ErrorCode.DESTINATION_UNVERIFIABLE, "insertion", "no window")
    pid, exe = win32.window_process(hwnd)
    if pid in exclude_pids:
        raise WisprError(ErrorCode.DESTINATION_UNVERIFIABLE, "insertion", "own window")
    title_hash = sha256(win32.window_title(hwnd).encode("utf-8")).hexdigest()
    field = uia.focused_element()
    snapshot = DestinationSnapshot(
        hwnd=hwnd,
        pid=pid,
        exe=exe.lower(),
        title_hash=title_hash,
        tab=uia.selected_tab(hwnd),
        field=field,
        field_type=uia.element_control_type(field) if field is not None else None,
        langid=win32.keyboard_layout(hwnd),
    )
    if not win32.is_window(hwnd):
        raise WisprError(ErrorCode.DESTINATION_UNVERIFIABLE, "insertion", "no window")
    return snapshot
