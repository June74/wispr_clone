"""A deterministic clock with cancellable scheduled callbacks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass
class _Handle:
    cancelled: bool = False

    def cancel(self) -> None:
        self.cancelled = True


@dataclass
class _Scheduled:
    when: float
    sequence: int
    callback: Callable[[], None]
    handle: _Handle


class FakeClock:
    """Clock whose time advances only when explicitly requested."""

    def __init__(self, start: float = 0.0) -> None:
        self._now = start
        self._sequence = 0
        self._scheduled: list[_Scheduled] = []

    def now(self) -> float:
        return self._now

    def call_at(self, when: float, callback: Callable[[], None]) -> _Handle:
        handle = _Handle()
        self._sequence += 1
        self._scheduled.append(_Scheduled(when, self._sequence, callback, handle))
        return handle

    def call_later(self, delay: float, callback: Callable[[], None]) -> _Handle:
        return self.call_at(self._now + delay, callback)

    def advance(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("clock cannot move backwards")
        target = self._now + seconds
        while True:
            due = min(
                (
                    entry
                    for entry in self._scheduled
                    if not entry.handle.cancelled and entry.when <= target
                ),
                key=lambda entry: (entry.when, entry.sequence),
                default=None,
            )
            if due is None:
                break
            self._scheduled.remove(due)
            self._now = max(self._now, due.when)
            due.callback()
        self._scheduled = [
            entry for entry in self._scheduled if not entry.handle.cancelled
        ]
        self._now = target
