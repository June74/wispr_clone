"""Readable deterministic ID factory for tests."""

from collections import defaultdict


class FakeIdFactory:
    """Generate independent, per-prefix IDs such as ``run-1``."""

    def __init__(self) -> None:
        self._counts: defaultdict[str, int] = defaultdict(int)

    def new(self, prefix: str) -> str:
        self._counts[prefix] += 1
        return f"{prefix}-{self._counts[prefix]}"
