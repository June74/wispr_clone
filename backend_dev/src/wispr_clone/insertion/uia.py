"""Lazy UI Automation boundary, intended for a single COM-owning thread."""

from __future__ import annotations

import ctypes
import importlib
import sys
from collections import OrderedDict, deque
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
        self._controls: OrderedDict[RuntimeId, Any] = OrderedDict()

    def _remember(self, control: Any) -> RuntimeId | None:
        rid = self._runtime_id(control)
        if rid is not None:
            self._controls[rid] = control
            self._controls.move_to_end(rid)
            while len(self._controls) > 32:
                self._controls.popitem(last=False)
        return rid

    @staticmethod
    def _runtime_id(control: Any) -> RuntimeId | None:
        try:
            value = control.GetRuntimeId()
            return tuple(int(part) for part in value) if value else None
        except Exception:
            return None

    def _find(self, rid: RuntimeId) -> Any | None:
        cached = self._controls.get(rid)
        if cached is not None:
            self._controls.move_to_end(rid)
            return cached
        try:
            hwnd = getattr(ctypes, "windll").user32.GetForegroundWindow()
            if not hwnd:
                return None
            root = self._automation.ControlFromHandle(hwnd)
        except Exception:
            return None
        queue = deque([(root, 0)])
        visited = 0
        while queue:
            control, depth = queue.popleft()
            visited += 1
            if visited > 2000:
                break
            if self._runtime_id(control) == rid:
                self._remember(control)
                return control
            if depth < 12:
                try:
                    queue.extend((child, depth + 1) for child in control.GetChildren())
                except Exception:
                    pass
        return None

    def focused_element(self) -> RuntimeId | None:
        try:
            control = self._automation.GetFocusedControl()
        except Exception:
            return None
        return self._remember(control) if control else None

    def element_control_type(self, rid: RuntimeId) -> str | None:
        control = self._find(rid)
        if control is None:
            return None
        try:
            value = control.ControlTypeName
        except Exception:
            return None
        return str(value) if isinstance(value, str) else None

    def selected_tab(self, hwnd: int) -> RuntimeId | None:
        try:
            root = self._automation.ControlFromHandle(hwnd)
        except Exception:
            return None
        queue = deque([(root, 0)])
        visited = 0
        while queue:
            control, depth = queue.popleft()
            visited += 1
            if visited > 2000:
                break
            try:
                control_type = control.ControlTypeName
            except Exception:
                control_type = None
            if control_type == "TabItemControl":
                try:
                    selected = bool(control.GetSelectionItemPattern().IsSelected)
                except Exception:
                    selected = False
                if selected:
                    return self._remember(control)
            if depth < 12:
                try:
                    queue.extend((child, depth + 1) for child in control.GetChildren())
                except Exception:
                    pass
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
        if control is None:
            return False
        try:
            return control.IsOffscreen is False
        except Exception:
            return False
