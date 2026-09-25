"""Public speech-to-text interfaces shared by the application and adapters."""

import array
from pathlib import Path
from typing import Callable, Protocol

SAMPLE_RATE = 16_000
CHUNK_SAMPLES = 1_280

TextCallback = Callable[[str, str], None]


class SttSession(Protocol):
    """A non-blocking audio input session with asynchronous finalization."""

    def push_audio(self, samples: array.array[float]) -> None: ...

    async def finish(self) -> str: ...

    def cancel(self) -> None: ...


class SttEngine(Protocol):
    """Lifecycle and replay interface for a speech recognition engine."""

    @property
    def ready(self) -> bool: ...

    async def start(self) -> None: ...

    def start_session(self, on_text: TextCallback | None = None) -> SttSession: ...

    async def transcribe_file(self, path: Path) -> str: ...

    async def close(self) -> None: ...
