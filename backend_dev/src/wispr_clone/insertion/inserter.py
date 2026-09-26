"""Focus management, one-shot input dispatch and UIA read-back confirmation."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Literal

from .app_strategies import Strategy, choose_strategy
from .destination import DestinationSnapshot
from .uia import RuntimeId, UiaApi
from .win32 import KeyEvent, Win32Api

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
VK_CONTROL = 0x11
VK_V = 0x56


def build_unicode_inputs(text: str) -> list[KeyEvent]:
    events: list[KeyEvent] = []
    encoded = text.encode("utf-16-le", errors="surrogatepass")
    for index in range(0, len(encoded), 2):
        unit = int.from_bytes(encoded[index : index + 2], "little")
        events.extend(
            (
                KeyEvent(scan=unit, flags=KEYEVENTF_UNICODE),
                KeyEvent(scan=unit, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP),
            )
        )
    return events


@dataclass(frozen=True, slots=True)
class PreviousFocus:
    hwnd: int
    tab: RuntimeId | None


def bring_forward(
    snapshot: DestinationSnapshot,
    win32: Win32Api,
    uia: UiaApi,
    *,
    settle_s: float = 0.1,
    timeout_s: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> PreviousFocus | None:
    previous_hwnd = win32.foreground_window()
    previous = PreviousFocus(previous_hwnd, uia.selected_tab(previous_hwnd))
    try:
        win32.set_foreground(snapshot.hwnd)
        if snapshot.tab is not None and not uia.select_tab(snapshot.hwnd, snapshot.tab):
            restore(previous, win32, uia)
            return None
        if snapshot.field is None or not uia.focus_element(snapshot.field):
            restore(previous, win32, uia)
            return None
        start = clock()
        deadline = start + max(0.0, timeout_s)
        stable_since: float | None = None
        while True:
            now = clock()
            settled = (
                win32.foreground_window() == snapshot.hwnd
                and uia.focused_element() == snapshot.field
            )
            if settled:
                if stable_since is None:
                    stable_since = now
                if now - stable_since >= max(0.0, settle_s):
                    return previous
            else:
                stable_since = None
            if now >= deadline:
                restore(previous, win32, uia)
                return None
            sleep(min(0.01, max(0.0, deadline - now)))
    except Exception:
        restore(previous, win32, uia)
        return None


def restore(previous: PreviousFocus, win32: Win32Api, uia: UiaApi) -> None:
    if not win32.is_window(previous.hwnd):
        return
    win32.set_foreground(previous.hwnd)
    if previous.tab is not None:
        uia.select_tab(previous.hwnd, previous.tab)


@dataclass(frozen=True, slots=True)
class DispatchResult:
    strategy: Strategy
    events_accepted: int
    before_text: str | None


def dispatch(
    text: str,
    snapshot: DestinationSnapshot,
    win32: Win32Api,
    uia: UiaApi,
    *,
    paste_settle_s: float = 0.5,
    sleep: Callable[[float], None] = time.sleep,
) -> DispatchResult:
    strategy = choose_strategy(snapshot)
    before_text = (
        uia.element_text(snapshot.field) if snapshot.field is not None else None
    )
    if strategy == "unicode":
        accepted = win32.send_inputs(build_unicode_inputs(text))
    else:
        old_clipboard = win32.clipboard_text()
        try:
            win32.set_clipboard(text, exclusion_formats=True)
            inputs = [
                KeyEvent(vk=VK_CONTROL),
                KeyEvent(vk=VK_V),
                KeyEvent(vk=VK_V, flags=KEYEVENTF_KEYUP),
                KeyEvent(vk=VK_CONTROL, flags=KEYEVENTF_KEYUP),
            ]
            accepted = win32.send_inputs(inputs)
            elapsed = 0.0
            deadline = max(0.0, paste_settle_s)
            while True:
                current = (
                    uia.element_text(snapshot.field)
                    if snapshot.field is not None
                    else None
                )
                if (
                    current is not None
                    and before_text is not None
                    and _one_insertion(before_text, current, text)
                ):
                    break
                if elapsed >= deadline:
                    break
                interval = min(0.01, deadline - elapsed)
                sleep(interval)
                elapsed += interval
        finally:
            if old_clipboard is None:
                win32.clear_clipboard()
            else:
                win32.set_clipboard(old_clipboard, exclusion_formats=False)
    return DispatchResult(strategy, accepted, before_text)


def _one_insertion(before: str, after: str, text: str) -> bool:
    if not text or after.count(text) != before.count(text) + 1:
        return False
    return any(
        after[:index] + after[index + len(text) :] == before
        for index in range(len(after) - len(text) + 1)
        if after[index : index + len(text)] == text
    )


def confirm(
    text: str,
    result: DispatchResult,
    snapshot: DestinationSnapshot,
    uia: UiaApi,
) -> Literal["inserted", "uncertain"]:
    if snapshot.field is None or result.before_text is None:
        return "uncertain"
    after_text = uia.element_text(snapshot.field)
    if after_text is None:
        return "uncertain"
    return (
        "inserted"
        if _one_insertion(result.before_text, after_text, text)
        else "uncertain"
    )
