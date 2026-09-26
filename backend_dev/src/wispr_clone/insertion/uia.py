"""Lazy UI Automation boundary, intended for a single COM-owning thread."""

from __future__ import annotations

import importlib
import sys
from typing import Any, Protocol

RuntimeId = tuple[int, ...]


class UiaApi(Protocol):
    def focused_element(self) -> RuntimeId | None: ...
    def element_control_type(self, rid: RuntimeId) -> str | None: ...
    def selected_tab(self, hwnd: int) -> RuntimeId | None: ...
    def select_tab(self, hwnd: int, tab: RuntimeId) -> bool: ...
    def focus_element(self, rid: RuntimeId) -> bool: ...
    def element_text(self, rid: RuntimeId) -> str | None: ...
    def is_on_screen(self, rid: RuntimeId) -> bool: ...


class RealUia:
    """uiautomation-backed implementation with no import-time platform dependency."""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise OSError("UI Automation is available only on Windows")
        self._automation: Any = importlib.import_module("uiautomation")

    @staticmethod
    def _runtime_id(control: Any) -> RuntimeId | None:
        value = getattr(control, "GetRuntimeId", lambda: None)()
        return tuple(int(part) for part in value) if value else None

    def _find(self, rid: RuntimeId) -> Any | None:
        root = self._automation.GetRootControl()
        queue = [root]
        while queue:
            control = queue.pop()
            if self._runtime_id(control) == rid:
                return control
            try:
                queue.extend(control.GetChildren())
            except Exception:
                continue
        return None

    def focused_element(self) -> RuntimeId | None:
        control = self._automation.GetFocusedControl()
        return self._runtime_id(control) if control else None

    def element_control_type(self, rid: RuntimeId) -> str | None:
        control = self._find(rid)
        value = getattr(control, "ControlTypeName", None) if control else None
        return str(value) if isinstance(value, str) else None

    def selected_tab(self, hwnd: int) -> RuntimeId | None:
        root = self._automation.ControlFromHandle(hwnd)
        queue = [root]
        while queue:
            control = queue.pop()
            if getattr(control, "ControlTypeName", "") == "TabItemControl":
                if bool(getattr(control, "IsSelected", False)):
                    return self._runtime_id(control)
            try:
                queue.extend(control.GetChildren())
            except Exception:
                continue
        return None

    def select_tab(self, hwnd: int, tab: RuntimeId) -> bool:
        del hwnd
        control = self._find(tab)
        if control is None:
            return False
        try:
            control.Select()
            return True
        except Exception:
            return False

    def focus_element(self, rid: RuntimeId) -> bool:
        control = self._find(rid)
        if control is None:
            return False
        try:
            control.SetFocus()
            return True
        except Exception:
            return False

    def element_text(self, rid: RuntimeId) -> str | None:
        control = self._find(rid)
        if control is None:
            return None
        try:
            value = control.GetValuePattern().Value
            return str(value)
        except Exception:
            try:
                return str(control.GetTextPattern().DocumentRange.GetText(-1))
            except Exception:
                return None

    def is_on_screen(self, rid: RuntimeId) -> bool:
        control = self._find(rid)
        return bool(control and getattr(control, "IsOffscreen", True) is False)
