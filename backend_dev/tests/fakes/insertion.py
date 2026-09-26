"""Recording in-memory Windows boundaries; never access the desktop or clipboard."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class FakeWin32Api:
    foreground: int = 10
    windows: set[int] = field(default_factory=lambda: {10, 20})
    processes: dict[int, tuple[int, str]] = field(
        default_factory=lambda: {10: (101, "target.exe"), 20: (202, "other.exe")}
    )
    titles: dict[int, str] = field(default_factory=lambda: {10: "PRIVATE TITLE"})
    layouts: dict[int, int] = field(default_factory=lambda: {10: 0x0409})
    clipboard: str | None = None
    accepted: int | None = None
    switch_foreground: bool = True
    idle_values: list[int] = field(default_factory=list)
    on_send: Callable[[], None] | None = None
    send_error: Exception | None = None
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = field(
        default_factory=list
    )

    def _call(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((name, args, kwargs))

    def foreground_window(self) -> int:
        self._call("foreground_window")
        return self.foreground

    def is_window(self, hwnd: int) -> bool:
        self._call("is_window", hwnd)
        return hwnd in self.windows

    def window_process(self, hwnd: int) -> tuple[int, str]:
        self._call("window_process", hwnd)
        return self.processes[hwnd]

    def window_title(self, hwnd: int) -> str:
        self._call("window_title", hwnd)
        return self.titles[hwnd]

    def keyboard_layout(self, hwnd: int) -> int:
        self._call("keyboard_layout", hwnd)
        return self.layouts[hwnd]

    def set_foreground(self, hwnd: int) -> bool:
        self._call("set_foreground", hwnd)
        if self.switch_foreground:
            self.foreground = hwnd
        return self.switch_foreground

    def idle_ms(self) -> int:
        self._call("idle_ms")
        return self.idle_values.pop(0) if self.idle_values else 10_000

    def send_inputs(self, inputs: Any) -> int:
        self._call("send_inputs", tuple(inputs))
        if self.send_error is not None:
            raise self.send_error
        if self.on_send is not None:
            self.on_send()
        return len(inputs) if self.accepted is None else self.accepted

    def clipboard_text(self) -> str | None:
        self._call("clipboard_text")
        return self.clipboard

    def set_clipboard(self, text: str, *, exclusion_formats: bool) -> None:
        self._call("set_clipboard", text, exclusion_formats=exclusion_formats)
        self.clipboard = text

    def clear_clipboard(self) -> None:
        self._call("clear_clipboard")
        self.clipboard = None


@dataclass
class FakeUiaApi:
    focused: tuple[int, ...] | None = (1, 2)
    types: dict[tuple[int, ...], str] = field(default_factory=lambda: {(1, 2): "Edit"})
    tabs: dict[int, tuple[int, ...] | None] = field(
        default_factory=lambda: {10: (10, 1), 20: (20, 1)}
    )
    texts: dict[tuple[int, ...], str | None] = field(
        default_factory=lambda: {(1, 2): "before"}
    )
    visible: dict[tuple[int, ...], bool] = field(default_factory=lambda: {(1, 2): True})
    calls: list[tuple[str, tuple[Any, ...]]] = field(default_factory=list)

    def _call(self, name: str, *args: Any) -> None:
        self.calls.append((name, args))

    def focused_element(self) -> tuple[int, ...] | None:
        self._call("focused_element")
        return self.focused

    def element_control_type(self, rid: tuple[int, ...]) -> str | None:
        self._call("element_control_type", rid)
        return self.types.get(rid)

    def selected_tab(self, hwnd: int) -> tuple[int, ...] | None:
        self._call("selected_tab", hwnd)
        return self.tabs.get(hwnd)

    def select_tab(self, hwnd: int, tab: tuple[int, ...]) -> bool:
        self._call("select_tab", hwnd, tab)
        self.tabs[hwnd] = tab
        return True

    def focus_element(self, rid: tuple[int, ...]) -> bool:
        self._call("focus_element", rid)
        self.focused = rid
        return True

    def element_text(self, rid: tuple[int, ...]) -> str | None:
        self._call("element_text", rid)
        return self.texts.get(rid)

    def is_on_screen(self, rid: tuple[int, ...]) -> bool:
        self._call("is_on_screen", rid)
        return self.visible.get(rid, False)
