"""Scripted cleanup boundary for run-controller tests."""

from __future__ import annotations

import asyncio

from wispr_clone.cleanup.base import CleanupEngine, CleanupRequest


class FakeCleanupEngine:
    def __init__(self, *results: str | Exception) -> None:
        self.results = list(results)
        self.requests: list[CleanupRequest] = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()
        self.available = True

    async def clean(self, request: CleanupRequest) -> str:
        self.requests.append(request)
        self.entered.set()
        await self.release.wait()
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    async def health(self) -> bool:
        return self.available


_protocol_check: CleanupEngine = FakeCleanupEngine()
