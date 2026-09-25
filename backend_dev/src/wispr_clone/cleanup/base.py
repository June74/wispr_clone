"""Frozen interface shared by cleanup implementations."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class CleanupRequest:
    """Input data and preferences for one cleanup attempt."""

    text: str
    glossary: tuple[str, ...] = ()
    instructions: str = ""


class CleanupEngine(Protocol):
    """Asynchronous cleanup service boundary."""

    async def clean(self, request: CleanupRequest) -> str:
        """Return cleaned text, raising a normalized dependency error on failure."""

    async def health(self) -> bool:
        """Report whether the pinned model is ready."""
