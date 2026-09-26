"""Per-application input strategy selection."""

from typing import Literal

from .destination import DestinationSnapshot
from .win32 import KOREAN_LANGID

Strategy = Literal["paste", "unicode"]
PASTE_APPS: frozenset[str] = frozenset({"devin.exe", "notepad.exe"})


def choose_strategy(snapshot: DestinationSnapshot) -> Strategy:
    if snapshot.langid == KOREAN_LANGID or snapshot.exe.lower() in PASTE_APPS:
        return "paste"
    return "unicode"
