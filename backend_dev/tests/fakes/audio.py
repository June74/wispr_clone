"""Scripted capture that drains queued chunks before ending on stop."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence

from wispr_clone.audio.capture import CaptureChunk


class FakeCapture:
    def __init__(self, chunks: Sequence[CaptureChunk] = ()) -> None:
        self.queued = list(chunks)
        self.started = False
        self.stopped = False
        self.cancelled = False
        self._changed = asyncio.Event()
        self.pumped = asyncio.Event()

    def start(self) -> None:
        self.started = True
        self._changed.set()

    def queue(self, chunk: CaptureChunk) -> None:
        if self.stopped or self.cancelled:
            raise RuntimeError("capture ended")
        self.queued.append(chunk)
        self._changed.set()

    async def chunks(self) -> AsyncIterator[CaptureChunk]:
        if not self.started:
            raise RuntimeError("capture not started")
        while not self.cancelled:
            while self.queued:
                yield self.queued.pop(0)
                self.pumped.set()
            if self.stopped:
                return
            self._changed.clear()
            await self._changed.wait()

    def stop(self) -> None:
        self.stopped = True
        self._changed.set()

    def cancel(self) -> None:
        self.cancelled = True
        self.queued.clear()
        self._changed.set()
